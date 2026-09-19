"""渠道层：统一「一份物料 → 一个平台」的投递契约（L3 发布层的核心抽象）。

与 app/platforms.py 的分工（务必分清，两者共用同一套渠道 id）：

| 层 | 文件 | 回答的问题 | 谁在用 |
| --- | --- | --- | --- |
| 身份层 | app/platforms.py | 这个平台的**账号**是谁、登没登录、怎么扫码 | 前端「平台账号」页 |
| 投递层 | app/channels/（本包） | 这份**物料**能不能投、怎么投、回执是什么、投不出去怎么兜底 | M3 发布阶段、/api/channels |

渠道 id 与别名见 registry 的 ALIASES：xiaohongshu（别名 xhs）/ zhihu / bilibili，
以及**只出素材包的 x**（别名 twitter，2026-09-19 加，见 x.py）。

三个真渠道都以「本机独立进程 + HTTP」接入（小红书 :18060、知乎 :18070、B 站 :18080）：
backend venv 不背浏览器与上传依赖，渠道可单独重启、单独诊断、单独挂掉。
x 不走 HTTP：它没有通道服务，只把英文 thread 落成素材包。

三条硬约束（源自 docs/00-goal-and-architecture.md 的 ADR，任何改动都不得违反）：
1. **真实投递不可逆**：只有人工闸门放行（confirmed=True）才允许调 publish()；
2. **单渠道故障不阻塞其它渠道，更不丢素材**：export/ 兜底在闸门之前先落盘；
3. **状态如实上报**：没接通就报 unconfigured / offline / login_required，不假装可用。
"""

from __future__ import annotations

import json
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import httpx

# material_only（2026-09-19 加）：这个渠道**没有投递通道**，只把物料落成素材包。
# 与 blocked / unconfigured 的区别是语义：那两者是「本来该能投，但环境不对」，
# 这个是「设计上就不投」——不该显示成故障，也不该被期待有登录态。
ChannelState = Literal["ready", "login_required", "offline", "unconfigured", "blocked", "material_only"]
DeliveryStatus = Literal["published", "failed", "draft", "skipped", "blocked"]

MEDIA_SUFFIX = {"image": ".png", "video": ".mp4", "cover": ".png"}


@dataclass
class Materials:
    """平台无关的投递物料：M3 从 M2/M4 的产物收集一次，三个渠道共用。

    字段刻意只保留「所有平台都认」的部分；平台特有的东西由各 adapter 自己拼。
    """

    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    video: Optional[Path] = None
    cover: Optional[Path] = None
    run_id: str = ""
    source: str = ""          # 论文来源（arXiv 链接 / 文件名），写进长文与视频简介
    duration_sec: int = 0     # 视频时长（B 站投稿需要）
    extra: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        bits = [f"标题「{self.title}」", f"正文 {len(self.body)} 字"]
        if self.images:
            bits.append(f"{len(self.images)} 张图")
        if self.video is not None:
            bits.append(f"视频 {self.video.name}")
        if self.tags:
            bits.append(f"{len(self.tags)} 个标签")
        return " / ".join(bits)


@dataclass
class Preflight:
    """投递前探测：渠道服务在不在、登录有没有、账号是谁。"""

    state: ChannelState
    account: str = ""
    detail: str = ""
    transport: str = ""
    reachable: bool = False
    hint: str = ""            # 不可用时「下一步该干什么」，要能直接照着做
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def dump(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "account": self.account,
            "detail": self.detail,
            "transport": self.transport,
            "reachable": self.reachable,
            "hint": self.hint,
        }


@dataclass
class Delivery:
    """一次投递的结果。status=published 才算真的发出去了。"""

    channel: str
    status: DeliveryStatus
    url: str = ""
    remote_id: str = ""
    account: str = ""
    export_dir: str = ""
    error: Optional[dict[str, str]] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "published"

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {"channel": self.channel, "status": self.status}
        for key in ("url", "remote_id", "account", "export_dir"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.error:
            out["error"] = self.error
        return out


def is_material_only(channel: "Channel") -> bool:
    """这个渠道是不是 material-only（只出素材包、不接投递）。

    用 getattr 兜底：测试里的替身渠道未必带这个标志，少一个属性不该让整条发布编排 500。
    """
    return bool(getattr(channel, "material_only", False))


class Channel(ABC):
    """一个平台的投递适配器。新增平台 = 新增一个子类 + 在 registry 注册。"""

    id: str = ""
    name: str = ""
    aliases: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()   # text / images / video
    login_kind: str = "none"                     # qrcode / browser / cookies / env
    transport: str = ""
    why: str = ""
    restart_hint: str = ""
    # 只出素材包的渠道（X）：不接投递通道，preflight 报 material_only，publish 永远不真发。
    # M3 见到它就跳过「能不能投」的判定，只落 publish/<id>/export/ 并写一份 draft 回执。
    material_only: bool = False
    # 这个平台要横版(16:9)还是竖版(9:16)成片。run 目录里两种都可能有
    # （video/video.mp4 1920×1080 是母版，video-vertical.mp4 1080×1920 是竖切），
    # 选哪个是**平台口径**，所以声明在这里由 channels 层决定，别让素材收集去猜。
    # 默认横版：B 站等 16:9 平台的题材以横版为母版；竖版平台（小红书）自己覆盖。
    video_orientation: str = "landscape"
    # 没特别指定时这个渠道发什么形态：`images`（图文/卡片）还是 `video`（成片）。
    # 同一条 run 常常两个产物都有（卡片组图 + 竖版成片），而平台只认一种笔记形态，
    # 所以"默认发哪个"是**平台口径**，和 video_orientation 一样声明在渠道层。
    # 默认图文：卡片是流水线的常规产物，成片是加项，想发成片就走 /publish/video。
    default_media: str = "images"

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ #
    # 元信息
    # ------------------------------------------------------------------ #

    @property
    def base_url(self) -> str:
        return ""

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": list(self.aliases),
            "capabilities": sorted(self.capabilities),
            # 不特别指定时发什么形态：界面拿它给按钮定性（主按钮发默认形态、次按钮发成片）
            "defaultMedia": self.default_media,
            "login": self.login_kind,
            "transport": self.transport,
            "endpoint": self.base_url,
            "why": self.why,
            "restart": self.restart_hint,
        }

    # ------------------------------------------------------------------ #
    # 物料适配性：由各 adapter 覆盖，规则留在平台自己家里
    # ------------------------------------------------------------------ #

    @abstractmethod
    def supports(self, m: Materials) -> tuple[bool, str]:
        """(能不能投, 一句人话的理由)。不能投时要说清缺什么。"""

    def missing(self, m: Materials, *, image: bool = False, video: bool = False) -> str:
        miss: list[str] = []
        if not m.title.strip():
            miss.append("标题")
        if not m.body.strip():
            miss.append("正文")
        if image and not m.images:
            miss.append("图片")
        if video and m.video is None:
            miss.append("视频")
        return "、".join(miss)

    # ------------------------------------------------------------------ #
    # 兜底：导出可手动发布的素材包（任何渠道都必须能做出这一步）
    # ------------------------------------------------------------------ #

    async def export(self, m: Materials, out: Path) -> dict[str, Any]:
        """把物料落成「服务全挂也能手动发」的素材包。无副作用、不触网。"""
        out.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        (out / "title.txt").write_text(m.title + "\n", encoding="utf-8")
        files.append("title.txt")
        (out / "content.txt").write_text(self.compose_body(m), encoding="utf-8")
        files.append("content.txt")
        (out / "tags.txt").write_text(" ".join(m.tags) + "\n", encoding="utf-8")
        files.append("tags.txt")

        for i, img in enumerate(m.images, 1):
            name = f"p{i}{img.suffix or MEDIA_SUFFIX['image']}"
            shutil.copyfile(img, out / name)
            files.append(name)
        if m.video is not None:
            name = f"video{m.video.suffix or MEDIA_SUFFIX['video']}"
            shutil.copyfile(m.video, out / name)
            files.append(name)
        if m.cover is not None:
            name = f"cover{m.cover.suffix or MEDIA_SUFFIX['cover']}"
            shutil.copyfile(m.cover, out / name)
            files.append(name)

        (out / "publish_request.json").write_text(
            json.dumps(
                {
                    "channel": self.id,
                    "transport": self.transport,
                    "title": m.title,
                    "content": m.body,
                    "tags": m.tags,
                    "images": [f"p{i}{p.suffix or '.png'}" for i, p in enumerate(m.images, 1)],
                    "video": (f"video{m.video.suffix}" if m.video is not None else ""),
                    "runId": m.run_id,
                    "source": m.source,
                    "preparedAt": int(time.time() * 1000),
                    "note": "本文件是待发布内容；真实投递需闸门放行后由 M3 调用渠道 publish()",
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        files.append("publish_request.json")
        (out / "README.txt").write_text(self.manual_steps(m, out), encoding="utf-8")
        files.append("README.txt")

        remote: Optional[dict[str, Any]] = None
        try:
            remote = await self.remote_export(m, out)
        except Exception as exc:  # 远程 export 失败不影响本地兜底
            remote = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

        return {"dir": str(out), "files": sorted(files), "remote": remote}

    async def remote_export(self, m: Materials, out: Path) -> Optional[dict[str, Any]]:
        """渠道服务自带 export 时再调一次（默认没有）。"""
        return None

    def compose_body(self, m: Materials) -> str:
        """导出与投递共用的正文拼装。默认在末尾附话题标签。"""
        body = m.body.strip()
        if m.source:
            body = f"{body}\n\n—— 论文：{m.source}"
        if m.tags:
            body = f"{body}\n\n" + " ".join(f"#{t}" for t in m.tags)
        return body + "\n"

    @abstractmethod
    def manual_steps(self, m: Materials, out: Path) -> str:
        """服务不可用时，人照着这几步就能把这包素材发出去。"""

    # ------------------------------------------------------------------ #
    # 探测 / 投递
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def preflight(self) -> Preflight:
        """探测本渠道当前能不能投。必须给出可执行的 hint。"""

    @abstractmethod
    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        """真实投递。confirmed=False 时必须直接返回 status=blocked，不发任何请求。"""


def parse_path_map(text: str) -> list[tuple[str, str]]:
    """解析 `本机前缀=对端前缀` 列表（逗号分隔）。

    按前缀**长的优先**排序：短前缀在前会把长前缀吃掉（`/a=/x` 会先命中 `/a/b/...`）。
    不符合形状的条目直接跳过 —— 配置写错不该让发布挂掉。
    """
    pairs: list[tuple[str, str]] = []
    for item in (text or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        src, dst = (part.strip() for part in item.split("=", 1))
        if src and dst:
            pairs.append((src.rstrip("/") or "/", dst.rstrip("/")))
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def map_remote_path(path: Path | str, mapping: str) -> str:
    """把素材路径换成**通道服务所在机器**读得到的写法（见 `Settings.channel_path_map`）。

    只在同前缀时替换；没配、或路径不在任何映射里，就原样返回。前缀按目录边界匹配
    （`/a/b` 不会命中 `/a/bc`）。同机部署（Linux 服务器上通道服务与后端同机）不需要配，
    这里就是恒等函数。
    """
    text = str(path)
    for src, dst in parse_path_map(mapping):
        if text == src:
            return dst
        if text.startswith(src + "/"):
            return dst + text[len(src):]
    return text


class HttpChannel(Channel):
    """走本机 HTTP 通道服务的渠道基类（小红书 / 知乎 / B 站都是这一形状）。"""

    health_timeout: float = 8.0
    probe_timeout: float = 45.0
    publish_timeout: float = 300.0

    def remote_path(self, path: Path | str) -> str:
        """递给通道服务前，把**本机素材路径**换成对端读得到的写法。

        只有跨机器才需要。本仓默认就是跨机器：后端在 WSL 里，小红书 MCP 特意跑在 Windows
        上（要的是原生 Windows 指纹，别拿 Linux 无头 + Windows 指纹这种组合去撞风控）——
        所以 `/home/yydh/hack/...` 对面根本不认，MCP 只会回「视频文件不存在或不可访问:
        CreateFile …」。配 `CHANNEL_PATH_MAP` 即可（见 .env.example）。
        """
        return map_remote_path(path, getattr(self.settings, "channel_path_map", "") or "")

    @property
    def base_url(self) -> str:
        raise NotImplementedError

    def _client(self, timeout: float) -> httpx.AsyncClient:
        # 本机服务必须绕开 http_proxy，否则请求会被代理吃掉（本机实测过）
        return httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def _request(self, method: str, path: str, *, timeout: float, **kw: Any) -> tuple[int, dict[str, Any]]:
        async with self._client(timeout) as cx:
            resp = await cx.request(method, f"{self.base_url}{path}", **kw)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text[:400]}
        return resp.status_code, data if isinstance(data, dict) else {"data": data}

    @staticmethod
    def error_of(status: int, body: dict[str, Any]) -> dict[str, str]:
        """把各渠道的错误统一成 {code, message}。

        各通道的 `error` 形状并不一致：知乎/B站 是 `{code, message}`，**小红书 MCP 是字符串**
        （`{"error":"视频发布失败","code":"PUBLISH_VIDEO_FAILED","details":"CreateFile …"}`）。
        原来一律当 dict 用，于是真原因（视频路径在 MCP 那侧不存在）被一句
        `AttributeError: 'str' object has no attribute 'get'` 盖掉，排查绕了一大圈
        （2026-09-19 实测）。所以这里两种形状都认，并把 `details` 拼进 message ——
        那句才是能定位问题的。
        """
        raw = body.get("error")
        if isinstance(raw, dict):
            err: dict[str, Any] = raw
        elif isinstance(raw, str):
            err = {"message": raw}
        else:
            err = {}
        code = err.get("code") or body.get("code") or f"HTTP_{status}"
        msg = str(err.get("message") or body.get("message") or "渠道返回失败")
        details = err.get("details") or body.get("details")
        if details and str(details) not in msg:
            msg = f"{msg}：{details}"
        return {"code": str(code)[:64], "message": msg[:400]}

    async def health(self) -> tuple[bool, str, dict[str, Any]]:
        """返回 (可达, 说明, 原始 body)。"""
        try:
            status, body = await self._request("GET", "/health", timeout=self.health_timeout)
        except Exception as exc:
            return False, f"{self.base_url} 不可达：{type(exc).__name__}: {exc}"[:300], {}
        if status != 200:
            return False, f"{self.base_url}/health 返回 HTTP {status}", body
        return True, "在线", body

    def offline(self, detail: str) -> Preflight:
        return Preflight(state="offline", reachable=False, transport=self.transport,
                         detail=detail, hint=self.restart_hint)

    def login_required(self, detail: str, hint: str = "") -> Preflight:
        return Preflight(state="login_required", reachable=True, transport=self.transport,
                         detail=detail, hint=hint or "先在「平台账号」页完成登录，再回发布阶段")

    def blocked_delivery(self, code: str, message: str) -> Delivery:
        return Delivery(channel=self.id, status="blocked", error={"code": code, "message": message})
