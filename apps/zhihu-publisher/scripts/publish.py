#!/usr/bin/env python3
"""知乎官方 OpenAPI 发布流程（zhihu-publisher 协议的本地实现）。

实现三阶段：validate（生成 latest.json）-> preview（生成 latest.html）
-> publish（签名并 POST https://openapi.zhihu.com/openapi/publish）。

凭证读取顺序（对齐 zhihu-publisher/reference/auth-info.md）：
  1. 环境变量 ZHIHU_OPENAPI_APP_KEY / ZHIHU_OPENAPI_APP_SECRET
  2. 共享文件 ~/.zhihu/openapi-credentials.json
ZHIHU_OPENAPI_APP_KEY = 知乎个人主页 URL 里的用户名
ZHIHU_OPENAPI_APP_SECRET = 开放平台 https://www.zhihu.com/playground/zhihu-publisher 申请

用法:
  python3 publish.py article.md --title "标题" [--topics URL ...]
                   [--comment-permission all] [--toc] [--creation-statement ai_creation]
                   [--dry-run] [--confirm]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = os.environ.get("ZHIHU_PUBLISH_BASE_URL", "https://openapi.zhihu.com").rstrip("/")
API_PATH = "/openapi/publish"
# 产物落 var/artifacts/zhihu/publish-output/（投递中转；不再写 cwd 下的隐藏目录）
WS = Path(os.environ.get("PAPERCAST_WS") or Path(__file__).resolve().parents[3])
OUT = Path(os.environ.get("ZHIHU_PUBLISH_OUT") or WS / "var" / "artifacts" / "zhihu" / "publish-output")
CRED_FILE = Path.home() / ".zhihu" / "openapi-credentials.json"
COMMENT_PERMISSIONS = {"all", "nobody", "followee", "censor", "follower"}
CREATION_STATEMENTS = {
    "spoiler",
    "medical_advice",
    "fictional_creation",
    "contain_finance",
    "ai_creation",
}


def load_credentials() -> tuple[str, str]:
    key = os.environ.get("ZHIHU_OPENAPI_APP_KEY", "")
    secret = os.environ.get("ZHIHU_OPENAPI_APP_SECRET", "")
    if (not key or not secret) and CRED_FILE.is_file():
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        key = key or data.get("ZHIHU_OPENAPI_APP_KEY", "")
        secret = secret or data.get("ZHIHU_OPENAPI_APP_SECRET", "")
    return key, secret


def markdown_to_html(md_text: str) -> str:
    try:
        import markdown  # type: ignore

        return markdown.markdown(
            md_text, extensions=["extra", "tables", "fenced_code", "sane_lists", "toc"]
        )
    except ImportError:
        proc = subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html", "--no-highlight"],
            input=md_text,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout


def strip_h1(md_text: str) -> str:
    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[:i] + lines[i + 1 :]).lstrip("\n")
    return md_text


def topic_token(url: str) -> str:
    for part in url.rstrip("/").split("/"):
        if part.isdigit():
            return part
    raise SystemExit(f"无法从链接提取 topic_token: {url}")


def derive_title(md_text: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def stage_payloads(args) -> tuple[dict, dict]:
    md_path = Path(args.markdown)
    raw = md_path.read_text(encoding="utf-8")
    title = args.title or derive_title(raw)
    if not title:
        raise SystemExit("缺少标题：--title 或 Markdown 一级标题")
    body_md = strip_h1(raw) if args.title or derive_title(raw) else raw
    html = markdown_to_html(body_md)
    if not html.strip():
        raise SystemExit("正文为空")

    validate = {
        "type": "article",
        "title": title,
        "body": html,
        "config": {
            "source_markdown": str(md_path),
            "comment_permission": args.comment_permission,
            "table_of_contents_enabled": bool(args.toc),
            "creation_statement": args.creation_statement or "",
            "topics": [topic_token(u) for u in (args.topics or [])][:3],
        },
    }
    content: dict = {
        "title": title,
        "html": html,
        "comment_permission": args.comment_permission,
        "table_of_contents_enabled": bool(args.toc),
    }
    if args.creation_statement:
        content["creation_statement"] = args.creation_statement
    if args.topics:
        content["topics"] = [
            {"topic_id": "", "topic_token": topic_token(u), "topic_name": ""}
            for u in args.topics[:3]
        ]
    request = {
        "type": "article",
        "confirmed": True,
        "confirm_note": "confirmed by user after local preview",
        "content": content,
    }
    return validate, request


def write_stage(stage: str, name: str, payload) -> Path:
    stage_dir = OUT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    latest = stage_dir / f"latest{name}"
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    latest.write_text(text, encoding="utf-8")
    (stage_dir / f"{stamp}{name}").write_text(text, encoding="utf-8")
    return latest


def sign(key: str, secret: str) -> tuple[dict, str]:
    ts = str(int(time.time()))
    log_id = "zhihu-publisher-" + datetime.now().strftime("%Y%m%d%H%M%S")
    extra_info = os.environ.get("ZHIHU_PUBLISH_EXTRA_INFO", "")
    sign_string = f"app_key:{key}|ts:{ts}|logid:{log_id}|extra_info:{extra_info}"
    digest = hmac.new(secret.encode(), sign_string.encode(), hashlib.sha256).digest()
    headers = {
        "Content-Type": "application/json",
        "X-App-Key": key,
        "X-Timestamp": ts,
        "X-Log-Id": log_id,
        "X-Extra-Info": extra_info,
        "X-Sign": base64.b64encode(digest).decode(),
    }
    return headers, ts


def post(request_file: Path, response_file: Path, headers: dict) -> int:
    cmd = ["curl", "-sS", "-o", str(response_file), "-w", "%{http_code}", "-m", "30",
           "-X", "POST", BASE_URL + API_PATH]
    for name, value in headers.items():
        cmd += ["-H", f"{name};" if value == "" else f"{name}: {value}"]
    cmd += ["--data-binary", "@" + str(request_file)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"curl 失败: {proc.stderr.strip()}", file=sys.stderr)
        return -1
    return int(proc.stdout.strip() or -1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("markdown")
    ap.add_argument("--title", default="")
    ap.add_argument("--topics", nargs="*", default=[])
    ap.add_argument("--comment-permission", default="all", choices=sorted(COMMENT_PERMISSIONS))
    ap.add_argument("--toc", action="store_true", help="创建文章目录")
    ap.add_argument("--creation-statement", default="", choices=[""] + sorted(CREATION_STATEMENTS))
    ap.add_argument("--dry-run", action="store_true", help="只生成 request，不发送")
    ap.add_argument(
        "--check-creds",
        action="store_true",
        help="只用故意非法的 type 做凭证探测：401 = 凭证无效；非 401 = 凭证有效（不会发布任何内容）",
    )
    args = ap.parse_args()

    if args.check_creds:
        key, secret = load_credentials()
        if not key or not secret:
            print("缺少凭证 ZHIHU_OPENAPI_APP_KEY / ZHIHU_OPENAPI_APP_SECRET", file=sys.stderr)
            return 2
        probe = OUT / "publish"
        probe.mkdir(parents=True, exist_ok=True)
        probe_file = probe / "cred-probe-request.json"
        probe_file.write_text(
            json.dumps({"type": "__cred_probe__", "confirmed": False, "content": {}}),
            encoding="utf-8",
        )
        headers, _ = sign(key, secret)
        resp = probe / "cred-probe-response.json"
        status = post(probe_file, resp, headers)
        body = resp.read_text(encoding="utf-8") if resp.is_file() else ""
        print(f"HTTP {status} {body[:300]}")
        if status == 401:
            print("凭证无效（AuthenticationError）")
            return 1
        print("凭证有效：鉴权已通过（该探测请求不会创建任何内容）")
        return 0

    validate, request = stage_payloads(args)
    write_stage("validate", ".json", validate)
    write_stage("preview", ".html", (
        "<!doctype html><meta charset='utf-8'><title>" + validate["title"] + "</title>"
        "<article><h1>" + validate["title"] + "</h1>" + validate["body"] + "</article>"
    ))
    request_file = write_stage("publish", "-request.json", request)
    print(f"validate: {OUT/'validate'/'latest.json'}")
    print(f"preview : {OUT/'preview'/'latest.html'}")
    print(f"request : {request_file}")

    if args.dry_run:
        print("dry-run: 未发送请求")
        return 0

    key, secret = load_credentials()
    if not key or not secret:
        print(
            "缺少凭证 ZHIHU_OPENAPI_APP_KEY / ZHIHU_OPENAPI_APP_SECRET\n"
            f"可写入 {CRED_FILE} 或作为环境变量传入；APP_KEY = 知乎主页 URL 用户名，"
            "APP_SECRET 需在 https://www.zhihu.com/playground/zhihu-publisher 申请",
            file=sys.stderr,
        )
        return 2

    headers, _ = sign(key, secret)
    response_file = OUT / "publish" / "latest-response.json"
    status = post(request_file, response_file, headers)
    body = response_file.read_text(encoding="utf-8") if response_file.is_file() else ""
    print(f"HTTP {status}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print(f"响应非 JSON（发布结果未知）: {body[:500]}")
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if isinstance(data.get("status"), int) and data["status"] == 0:
        print(f"发布成功: {data['data'].get('url')}")
        return 0
    print(f"发布失败: status={data.get('status')} msg={data.get('msg')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
