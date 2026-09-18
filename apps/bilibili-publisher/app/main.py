"""B 站发布通道服务（HTTP）—— 对齐 apps/zhihu-publisher、apps/xiaohongshu-mcp 的形状。

定位：B 站投稿要上传视频、要 cookies、底层是 biliup CLI，这些都不该进 backend venv，
所以做成「独立进程 + HTTP」，后端只按 HTTP 调它。

底层选型（2026-09 核实）：**biliup**（PyPI 1.2.4 有 manylinux wheel，不需要编译器）。
- biliup-rs 仓库已归档，与 biliup 同一内核，故不单列；
- B 站开放平台（arcopen /video/add）需要资质 + 权限审核，本期不可行；
- 浏览器自动化（rod/playwright 复刻创作中心上传）风控风险高，只作最后兜底；
- 结论：biliup CLI 子进程 + cookies（有效期 1~3 个月，biliup renew 续期）。

接口契约：
  GET    /health                      -> {"status":"ok","biliup":...,"cookies":...}
  GET    /api/v1/login/status         -> {"success","data":{is_logged_in,username,cookie_count,biliup_available,...}}
  POST   /api/v1/login/start          -> {"success","data":{started,pid,log,hint}}   # biliup login 跑在 pty 里，二维码进日志
  POST   /api/v1/login/renew          -> {"success","data":{pid,log}}                # 续期（cookies 未过期时）
  POST   /api/v1/login/cookies        -> {"success","data":{saved,path,count}}        # 导入现成 cookies
  DELETE /api/v1/login/cookies        -> {"success","data":{deleted}}
  POST   /api/v1/export               -> {"success","data":{dir,files[]}}             # 只落盘，无副作用
  POST   /api/v1/publish              -> {"success","data":{bvid,url,...}}            # 必须 confirmed=true

**诚实原则**：没装 biliup、没有可用 cookies，就如实报 unconfigured / login_required，
绝不假装能投；投递失败一定回传 biliup 的原始输出片段，方便人工定位。
"""
from __future__ import annotations

import base64
import json
import os
import pty
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

WS = Path(os.environ.get("PAPERCAST_WS") or Path(__file__).resolve().parents[3])


def _default_cookies() -> Path:
    """cookies 是凭证 → 写新登录一律落 var/secrets/；读的时候把历史位置也认下来。

    历史位置两个，都是真实存在过的登录产物，不能视而不见：
    - var/artifacts/bilibili/cookies.json（本服务早期路径）；
    - var/home/.bilibili/cookies.json（biliup **自己**的 HOME 落盘位置：人在终端敲
      `biliup login` 时写的就是这里，dashboard 里点「重启通道服务」后不该突然变未登录）。
    """
    secrets = WS / "var" / "secrets" / "bilibili" / "cookies.json"
    legacy = [
        WS / "var" / "artifacts" / "bilibili" / "cookies.json",
        WS / "var" / "home" / ".bilibili" / "cookies.json",
    ]
    if secrets.is_file():
        return secrets
    for cand in legacy:
        if cand.is_file():
            return cand
    return secrets


def _find_biliup() -> str:
    """按 环境变量 → PATH → 工作区自带 venv 的顺序找 biliup。

    本工作区把 biliup 装在 var/toolchains/bili-venv（不在 PATH 里，见 ops/README.md），
    不显式回退就会出现「明明装了却报 BILIUP_MISSING」。
    """
    for cand in (WS / "var" / "toolchains" / "bili-venv" / "bin" / "biliup",):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return ""


COOKIES_PATH = Path(os.environ.get("BILIBILI_COOKIES") or _default_cookies())
EXPORT_ROOT = Path(os.environ.get("BILIBILI_EXPORT_ROOT") or WS / "var" / "artifacts" / "bilibili" / "export")
LOG_ROOT = Path(os.environ.get("BILIBILI_LOG_ROOT") or WS / "var" / "logs")
# biliup login 的 cwd：二维码图 qrcode.png 是**相对 cwd** 写的，固定下来前端才能取到它
LOGIN_DIR = Path(os.environ.get("BILIBILI_LOGIN_DIR") or WS / "var" / "artifacts" / "bilibili" / "login")
# biliup 自己的凭据/配置目录（HOME 换掉，免得写进别人的家目录）
BILIUP_HOME = Path(os.environ.get("BILIBILI_HOME") or WS / "var" / "home")
BILIUP = os.environ.get("BILIBILI_BILIUP") or shutil.which("biliup") or _find_biliup()
DEFAULT_TID = int(os.environ.get("BILIBILI_TID", "231"))   # 学术向分区；以投稿页当前口径为准，可用环境变量改
UPLOAD_TIMEOUT = int(os.environ.get("BILIBILI_UPLOAD_TIMEOUT", "2400"))
EXTRA_ARGS = os.environ.get("BILIBILI_UPLOAD_EXTRA", "")    # 追加参数，例如 "--submit web --line cnbd"
# 413（文件被拒）时的一次补救重试：换固定线路 + 限并发。方向以 biliup 文档为准，可用环境变量覆盖。
RETRY_ARGS = shlex.split(os.environ.get("BILIBILI_RETRY_ARGS", "--line cnbd --limit 1"))
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
AUTH_HINTS = ("未登录", "登录失败", "鉴权", "-101", "cookie", "Cookie", "请先登录")
SIZE_HINTS = ("413", "too large", "文件过大", "Payload Too Large")

app = FastAPI(title="bilibili-publisher", version="0.1.0")


class ChannelError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@app.exception_handler(ChannelError)
async def _channel_error(_request, exc: ChannelError):
    return JSONResponse(status_code=exc.status,
                        content={"success": False, "error": {"code": exc.code, "message": exc.message}})


class ExportBody(BaseModel):
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=list)
    video: str = ""
    cover: str = ""
    run_id: str = ""


class PublishBody(ExportBody):
    tid: int = DEFAULT_TID
    confirmed: bool = False


class CookiesBody(BaseModel):
    cookies: Any = None          # {name: value} 或 [{name,value},...] 或 biliup 的 LoginInfo JSON
    cookies_path: str = ""       # 或者直接给一个现成文件的路径


# --------------------------------------------------------------------------- #
# cookies / 登录态
# --------------------------------------------------------------------------- #

def _extract_cookies(raw: Any) -> dict[str, str]:
    """尽量从各种形状里抠出 name->value：裸字典 / list / biliup LoginInfo。都抠不出就返回空。"""
    if isinstance(raw, dict):
        if isinstance(raw.get("cookie_info"), dict) and isinstance(raw["cookie_info"].get("cookies"), list):
            raw = raw["cookie_info"]["cookies"]
        elif isinstance(raw.get("cookies"), list):
            raw = raw["cookies"]
        elif raw and all(isinstance(v, str) for v in raw.values()):
            return {str(k): str(v) for k, v in raw.items()}
        else:
            return {}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                out[str(item["name"])] = str(item.get("value") or "")
        return out
    return {}


def _read_cookie_file() -> tuple[str, dict[str, str]]:
    """返回 (kind, cookies)。kind ∈ raw / biliup / none。"""
    if not COOKIES_PATH.is_file():
        return "none", {}
    try:
        raw = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "none", {}
    kind = "raw"
    if isinstance(raw, dict) and ("cookie_info" in raw or "token_info" in raw):
        kind = "biliup"
    return kind, _extract_cookies(raw)


async def _nav_check(cookies: dict[str, str]) -> tuple[bool, str, str]:
    """用真实接口校验登录态：返回 (是否登录, 账号名, 说明)。网络不通≠未登录。"""
    if not cookies:
        return False, "", "cookies 里没有可用字段（需要 SESSDATA 等）"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as cx:
            resp = await cx.get(NAV_URL, cookies=cookies, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
    except Exception as exc:
        return bool(cookies.get("SESSDATA")), "", f"无法校验登录态（{type(exc).__name__}: {exc}），按 SESSDATA 是否存在粗判"[:200]
    body = data.get("data") or {}
    if data.get("code") == 0 and body.get("isLogin"):
        return True, str(body.get("uname") or ""), f"cookies 有效，已登录：{body.get('uname') or '未知账号'}"
    return False, "", f"cookies 无效或已过期（code={data.get('code')}，{data.get('message') or ''}）→ 需要重新登录"


async def _account_state() -> dict[str, Any]:
    kind, cookies = _read_cookie_file()
    logged_in, username, detail = await _nav_check(cookies)
    return {
        "cookies_path": str(COOKIES_PATH),
        "cookie_file": kind,               # none / raw / biliup
        "cookie_count": len(cookies),
        "has_sessdata": bool(cookies.get("SESSDATA")),
        "biliup": BILIUP,
        "biliup_available": bool(BILIUP),
        "is_logged_in": logged_in,
        "username": username,
        "tid": DEFAULT_TID,
        "detail": detail,
    }


# --------------------------------------------------------------------------- #
# 接口：健康 / 登录
# --------------------------------------------------------------------------- #

@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "biliup": BILIUP, "cookies": str(COOKIES_PATH), "tid": DEFAULT_TID}


@app.get("/api/v1/login/status")
async def login_status() -> dict[str, Any]:
    return {"success": True, "data": await _account_state()}


# biliup 1.2.4 的 login 是**交互菜单**（账号密码 / 短信登录 / 扫码登录 / 浏览器登录 / 网页Cookie登录），
# 没有「直接扫码」的命令行开关，默认光标停在「短信登录」上。要二维码就得往 pty 里发一次
# 「↓ + 回车」，把光标移到「扫码登录」。（只发一次：多点一次可能落到「浏览器登录」，那会弹窗口。）
QR_MENU_KEYS: tuple[tuple[float, bytes], ...] = ((4.0, b"\x1b[B"), (4.3, b"\r"))


def _spawn_in_pty(argv: list[str], log_name: str, cwd: Optional[Path] = None,
                  keys: tuple[tuple[float, bytes], ...] = ()) -> dict[str, Any]:
    """biliup login 是交互菜单（二维码写在终端）→ 丢进 pty，把输出同时写进日志文件。

    cwd 固定到 LOGIN_DIR：biliup 会在这个目录下写 qrcode.png，前端据此展示可扫的二维码。
    HOME 固定到 var/home：biliup 自己的凭据/配置不落到别人的家目录。
    """
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)
    BILIUP_HOME.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / log_name
    env = {**os.environ, "HOME": str(BILIUP_HOME), "XDG_CONFIG_HOME": str(BILIUP_HOME / ".config")}
    master, slave = pty.openpty()
    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                            close_fds=True, start_new_session=True,
                            cwd=str(cwd) if cwd is not None else None, env=env)
    os.close(slave)

    def pump() -> None:
        with log_path.open("ab") as fh:
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                fh.write(chunk)
                fh.flush()
        os.close(master)

    import threading

    threading.Thread(target=pump, daemon=True).start()

    def feed() -> None:
        for delay, payload in keys:
            time.sleep(delay)
            try:
                os.write(master, payload)
            except OSError:
                return

    if keys:
        threading.Thread(target=feed, daemon=True).start()
    return {"pid": proc.pid, "log": str(log_path), "keys_sent": [p.decode("latin1") for _, p in keys]}


class LoginStartBody(BaseModel):
    """method=qrcode（默认）会自动在 biliup 的交互菜单里选「扫码登录」并出二维码；

    其余取值只用于把菜单原样留给人工（此时请人在终端里操作）。
    """

    method: str = "qrcode"


@app.post("/api/v1/login/start")
async def login_start(body: Optional[LoginStartBody] = None) -> dict[str, Any]:
    if not BILIUP:
        raise ChannelError(501, "BILIUP_MISSING",
                           "本机没有 biliup：用 var/toolchains/bili-venv（见 ops/README.md）或 pip install biliup==1.2.4 后重试")
    if not hasattr(os, "openpty"):
        raise ChannelError(501, "NO_PTY", "本机不支持伪终端，请在终端里手动执行：biliup login")
    method = (body.method if body else "qrcode").strip().lower()
    keys = QR_MENU_KEYS if method == "qrcode" else ()
    info = _spawn_in_pty([BILIUP, "-u", str(COOKIES_PATH), "login"], "bilibili-login.log",
                         cwd=LOGIN_DIR, keys=keys)
    hint = ("已在 biliup 的菜单里自动选「扫码登录」；二维码会写成 "
            f"{LOGIN_DIR / 'qrcode.png'}，用 GET /api/v1/login/qrcode 取图。"
            "扫码成功后本接口不用再调，轮询 /api/v1/login/status 即可") if keys else (
            "biliup 的交互菜单已起：读 " + info["log"] + " 跟着操作，或用手机 App 扫码")
    return {"success": True, "data": {**info, "started": True, "method": method,
                                      "qrcode_dir": str(LOGIN_DIR), "hint": hint}}


@app.get("/api/v1/login/qrcode")
async def login_qrcode(max_age_sec: int = 240) -> dict[str, Any]:
    """取 biliup 刚写下的登录二维码（PNG data URL），供 dashboard 直接扫码。

    biliup login 在 cwd 下写 qrcode.png（终端里那份是同一张码的字符画）；这里读出来转 base64，
    超过 max_age_sec 的旧图视为过期 —— 过期码扫了也没用，宁可让前端重新点一次登录。
    """
    png = LOGIN_DIR / "qrcode.png"
    if not png.is_file():
        return {"success": True, "data": {"available": False, "qrcode_dir": str(LOGIN_DIR),
                                          "hint": "还没有二维码：先 POST /api/v1/login/start"}}
    age = time.time() - png.stat().st_mtime
    if age > max_age_sec:
        return {"success": True, "data": {"available": False, "age_sec": int(age),
                                          "hint": f"二维码已生成 {int(age)} 秒，超过 {max_age_sec} 秒视为过期，请重新登录"}}
    return {"success": True, "data": {
        "available": True,
        "img": "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii"),
        "age_sec": int(age),
        "log": str(LOG_ROOT / "bilibili-login.log"),
    }}


@app.post("/api/v1/login/renew")
async def login_renew() -> dict[str, Any]:
    if not BILIUP:
        raise ChannelError(501, "BILIUP_MISSING", "本机没有 biliup，无法续期")
    if not COOKIES_PATH.is_file():
        raise ChannelError(400, "NO_COOKIES", "还没有 cookies 文件，先完成一次登录")
    info = _spawn_in_pty([BILIUP, "-u", str(COOKIES_PATH), "renew"], "bilibili-renew.log")
    return {"success": True, "data": {**info, "hint": "renew 成功会重写 cookies 文件；失败就直接重新登录"}}


@app.post("/api/v1/login/cookies")
async def import_cookies(body: CookiesBody) -> dict[str, Any]:
    """导入现成 cookies（前端/脚本把 SESSDATA 等喂进来，免去终端交互）。"""
    if body.cookies_path:
        src = Path(body.cookies_path).expanduser()
        if not src.is_file():
            raise ChannelError(400, "FILE_NOT_FOUND", f"找不到文件：{src}")
        payload = src.read_text(encoding="utf-8")
    elif body.cookies is not None:
        payload = json.dumps(body.cookies, ensure_ascii=False)
    else:
        raise ChannelError(400, "EMPTY_BODY", "需要 cookies 或 cookies_path")
    cookies = _extract_cookies(json.loads(payload))
    if not cookies:
        raise ChannelError(400, "NO_COOKIE_FIELDS", "没解析出任何 cookie 字段（需要 name/value 形状）")

    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_text(payload, encoding="utf-8")
    os.chmod(COOKIES_PATH, 0o600)
    state = await _account_state()
    if not state["is_logged_in"]:
        return {"success": True, "data": {"saved": True, "path": str(COOKIES_PATH), "count": len(cookies),
                                          "is_logged_in": False, "detail": state["detail"],
                                          "hint": "文件已写，但校验没通过：多半是 SESSDATA 过期或缺少 bili_jct"}}
    return {"success": True, "data": {"saved": True, "path": str(COOKIES_PATH), "count": len(cookies),
                                      "is_logged_in": True, "username": state["username"]}}


@app.delete("/api/v1/login/cookies")
async def logout() -> dict[str, Any]:
    deleted = False
    if COOKIES_PATH.is_file():
        COOKIES_PATH.unlink()
        deleted = True
    return {"success": True, "data": {"deleted": deleted, "cookies_path": str(COOKIES_PATH)}}


# --------------------------------------------------------------------------- #
# 导出素材包 / 投稿
# --------------------------------------------------------------------------- #

def _link(src: Path, dst: Path) -> None:
    """大视频尽量硬链接/软链接，避免把几百 MB 复制一份。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        try:
            dst.symlink_to(src)
        except OSError:
            shutil.copyfile(src, dst)


def _write_package(body: ExportBody) -> dict[str, Any]:
    out = EXPORT_ROOT / (body.run_id or f"adhoc-{int(time.time())}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "title.txt").write_text(body.title + "\n", encoding="utf-8")
    (out / "desc.txt").write_text(body.desc + "\n", encoding="utf-8")
    (out / "tags.txt").write_text(",".join(body.tags) + "\n", encoding="utf-8")
    files = ["title.txt", "desc.txt", "tags.txt"]
    if body.video and Path(body.video).is_file():
        name = f"video{Path(body.video).suffix or '.mp4'}"
        _link(Path(body.video), out / name)
        files.append(name)
    if body.cover and Path(body.cover).is_file():
        name = f"cover{Path(body.cover).suffix or '.png'}"
        _link(Path(body.cover), out / name)
        files.append(name)
    (out / "README.txt").write_text(
        "B 站投稿指引（服务/凭证不可用时照这个手动投）：\n"
        "1. 打开 https://member.bilibili.com/platform/upload/video/frame；\n"
        "2. 上传 video.mp4（横版 16:9）；\n"
        "3. 标题取 title.txt（≤ 80 字），简介取 desc.txt，标签取 tags.txt；\n"
        f"4. 封面用 cover.png；分区（tid）默认 {DEFAULT_TID}，以投稿页当前口径为准；\n"
        "5. 先存草稿确认无误再投。\n",
        encoding="utf-8")
    files.append("README.txt")
    return {"dir": str(out), "files": files}


@app.post("/api/v1/export")
async def export(body: ExportBody) -> dict[str, Any]:
    return {"success": True, "data": _write_package(body)}


def _upload_argv(body: PublishBody, extra: list[str]) -> list[str]:
    argv = [BILIUP, "-u", str(COOKIES_PATH), "upload", str(Path(body.video).resolve()),
            "--title", body.title, "--tag", ",".join(body.tags), "--desc", body.desc,
            "--copyright", "1", "--tid", str(body.tid)]
    if body.cover and Path(body.cover).is_file():
        argv += ["--cover", str(Path(body.cover).resolve())]
    return argv + extra


def _run_upload(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=UPLOAD_TIMEOUT)


@app.post("/api/v1/publish")
async def publish(body: PublishBody) -> dict[str, Any]:
    if not body.confirmed:
        raise ChannelError(409, "NOT_CONFIRMED", "投稿不可逆：需要人工闸门确认（confirmed=true）后才执行")
    if not body.video or not Path(body.video).is_file():
        raise ChannelError(400, "VIDEO_MISSING", "缺少可上传的视频文件（B 站是视频投稿）")
    if not BILIUP:
        raise ChannelError(501, "BILIUP_MISSING",
                           "本机没有 biliup，无法投稿：pipx install biliup 后执行 biliup login")

    state = await _account_state()
    if not state["is_logged_in"]:
        raise ChannelError(401, "NOT_LOGGED_IN", f"没有可用的 B 站登录态：{state['detail']}")

    package = _write_package(body)          # 投之前先留一份可复核的素材包
    extra = shlex.split(EXTRA_ARGS)
    argv = _upload_argv(body, extra)
    command = " ".join(shlex.quote(a) for a in argv)
    try:
        proc = _run_upload(argv)
    except subprocess.TimeoutExpired:
        raise ChannelError(504, "UPLOAD_TIMEOUT",
                           f"投稿超时（>{UPLOAD_TIMEOUT}s）：biliup 可能仍在后台跑，先查素材包与服务日志，别重复投")

    stderr = (proc.stderr or "")[-2000:]
    stdout = (proc.stdout or "")[-4000:]
    # 大文件被拒（413）：加 `--line/--limit` 重试一次（有界、只一次、回执里保留两次的输出）
    if proc.returncode != 0 and any(h in (stderr + stdout) for h in SIZE_HINTS):
        retry = _upload_argv(body, extra + RETRY_ARGS)
        try:
            proc = _run_upload(retry)
        except subprocess.TimeoutExpired:
            raise ChannelError(504, "UPLOAD_TIMEOUT", "带 --line cnbd --limit 1 的重试也超时了")
        argv, command = retry, " ".join(shlex.quote(a) for a in retry)
        stderr, stdout = (proc.stderr or "")[-2000:], (proc.stdout or "")[-4000:]

    if proc.returncode != 0:
        tail = (stderr or stdout)[-400:]
        if any(h in tail for h in AUTH_HINTS):
            raise ChannelError(401, "NOT_LOGGED_IN",
                               f"biliup 报登录态失效（{tail}）→ 重新扫码登录，或在过期前用 /api/v1/login/renew 续期")
        raise ChannelError(502, "PUBLISH_FAILED", f"biliup 退出码 {proc.returncode}：{tail}")

    bv = BV_RE.search(stdout) or BV_RE.search(stderr)
    data = {
        "bvid": bv.group(0) if bv else "",
        "url": f"https://www.bilibili.com/video/{bv.group(0)}" if bv else "",
        "title": body.title,
        "tid": body.tid,
        "exportDir": package["dir"],
        "command": command,
        "stdoutTail": stdout[-800:],
        "publishedAt": int(time.time() * 1000),
        "note": "biliup 返回 0 即已提交；是否过审以创作中心为准",
    }
    if body.run_id:
        receipt = EXPORT_ROOT / body.run_id / "bilibili_receipt.json"
        receipt.write_text(json.dumps({"channel": "bilibili", "status": "published", **data},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
        data["receipt"] = str(receipt)
    return {"success": True, "data": data}
