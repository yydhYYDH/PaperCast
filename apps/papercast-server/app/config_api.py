"""配置中心 HTTP 视图：GET / PATCH `/api/config` + POST `/api/config/test`。

为什么单独一个模块：`app/config.py` 负责**读**配置，这里负责**改**配置，职责分开；
挂载方式与 `app/channels/routes.py` 一致（APIRouter + 统一错误形状）。

安全约定（改这里前先读）：
1. 密钥**永不回明文**：GET 只回打码值（前 3 + **** + 后 4）与 configured 标记；
2. PATCH 里的密钥字段**留空或省略 = 不修改**（防止把打码值写回去覆盖真值）；
3. `.env` 落盘时 chmod 600，且只写本文件 SPEC 里白名单的键；
4. 改完**热生效**（重新 `Settings.load()` 后就地刷新单例），不需要重启后端；
   标记 `restart=True` 的项（监听地址等）除外。
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from .config import ROOT, Settings, _dsh_credential, _parse_env_file, settings
from .llm import LLMClient, LLMError
# 与 channels/routes.py 共用同一套错误形状 {error:{code,message}}
from .platforms import PlatformError

router = APIRouter(prefix="/api/config", tags=["config"])

ENV_PATH: Path = ROOT / ".env"

# 白名单。key=环境变量名；attr=Settings 字段名；kind 决定 UI 控件与校验。
# restart=True 的项改了要重启后端才生效，UI 会显式提示。
SPEC: list[dict[str, Any]] = [
    # ── 模型与 API ──
    {"key": "LLM_BASE_URL", "attr": "llm_base_url", "group": "模型与 API", "label": "API 地址",
     "kind": "str", "desc": "OpenAI 兼容的 base_url，**不含** /chat/completions"},
    {"key": "LLM_MODEL", "attr": "llm_model", "group": "模型与 API", "label": "模型名",
     "kind": "str", "desc": "请求体里的 model 字段"},
    {"key": "LLM_API_KEY", "attr": "llm_api_key", "group": "模型与 API", "label": "API 密钥",
     "kind": "secret", "desc": "留空 = 不修改。未配置时回落 ~/.dsh/.credentials.yaml 的 GO_API_KEY"},
    {"key": "LLM_TIMEOUT_SEC", "attr": "llm_timeout_sec", "group": "模型与 API", "label": "单次调用超时（秒）",
     "kind": "int", "desc": "**这是治卡死的关键旋钮**：默认 600 秒太长，配合重试可让一个阶段合法地耗掉一小时"},
    {"key": "LLM_MAX_TOKENS", "attr": "llm_max_tokens", "group": "模型与 API", "label": "默认输出上限（token）",
     "kind": "int", "desc": "调用方未显式指定 max_tokens 时生效"},
    {"key": "LLM_MAX_TOKENS_CAP", "attr": "llm_max_tokens_cap", "group": "模型与 API", "label": "硬上限（token，0 = 不限）",
     "kind": "int", "desc": "对所有调用生效：长文变体写死 24000，填 16000 即可全局压下来"},
    # ── 投递渠道 ──
    {"key": "PAPERCAST_CHANNELS", "attr": "channels", "group": "投递渠道", "label": "启用的渠道",
     "kind": "list", "desc": "逗号分隔，如 xiaohongshu,zhihu,bilibili"},
    {"key": "XHS_MCP_BASE", "attr": "xhs_mcp_base", "group": "投递渠道", "label": "小红书 MCP 地址",
     "kind": "str", "desc": "默认 http://127.0.0.1:18060"},
    {"key": "ZHIHU_PUBLISHER_BASE", "attr": "zhihu_publisher_base", "group": "投递渠道", "label": "知乎发布服务地址",
     "kind": "str", "desc": "默认 http://127.0.0.1:18070"},
    {"key": "BILIBILI_PUBLISHER_BASE", "attr": "bilibili_publisher_base", "group": "投递渠道", "label": "B 站发布服务地址",
     "kind": "str", "desc": "默认 http://127.0.0.1:18080"},
    {"key": "PUBLISH_CONFIRM_ACCOUNT", "attr": "publish_confirm_account", "group": "投递渠道", "label": "投递前二次校验账号",
     "kind": "str", "desc": "填了的话，真实投递前会比对账号名，防串号；留空 = 不校验"},
    # ── 解析与渲染 ──
    {"key": "PAPERCAST_INTAKE_ENGINE", "attr": "intake_engine", "group": "解析与渲染", "label": "PDF 解析引擎",
     "kind": "str", "desc": "pymupdf（本机无 GPU 时的正确选择）| mineru"},
    {"key": "PAPERCAST_CARDS", "attr": "cards_enabled", "group": "解析与渲染", "label": "卡片图渲染",
     "kind": "bool", "desc": "on = 生成 1080×1440 卡片；off = 跳过"},
    {"key": "PAPERCAST_POSTER_DECK", "attr": "poster_deck", "group": "解析与渲染", "label": "小红书组图（guizang 技能）",
     "kind": "str", "desc": "auto（默认）= 装了技能才跑 | on = 强制跑（技能没装则阶段里记 run 跳过）| off = 不跑"},
    {"key": "MAX_UPLOAD_MB", "attr": "max_upload_mb", "group": "解析与渲染", "label": "上传大小上限（MB）",
     "kind": "int", "desc": "PDF / LaTeX 源码包"},
    # ── 只读（由运行环境决定，改了也没用）──
    {"key": "PAPERCAST_HOST", "attr": "host", "group": "运行环境（只读）", "label": "监听地址",
     "kind": "str", "desc": "由 ops/start_all.sh 注入", "editable": False, "restart": True},
    {"key": "PAPERCAST_PORT", "attr": "port", "group": "运行环境（只读）", "label": "监听端口",
     "kind": "int", "desc": "由 ops/start_all.sh 注入", "editable": False, "restart": True},
    {"key": "PAPERCAST_DATA_DIR", "attr": "data_dir", "group": "运行环境（只读）", "label": "运行数据目录",
     "kind": "str", "desc": "var/runs，跑起来的 run 都在这里", "editable": False},
    {"key": "PAPERCAST_UPLOAD_DIR", "attr": "upload_dir", "group": "运行环境（只读）", "label": "上传目录",
     "kind": "str", "desc": "var/uploads", "editable": False},
    {"key": "PAPERCAST_CHROME", "attr": "chrome", "group": "运行环境（只读）", "label": "无头浏览器",
     "kind": "str", "desc": "卡片图与登录二维码渲染用，自动探测", "editable": False},
    {"key": "PAPERCAST_CJK_FONT", "attr": "cjk_font", "group": "运行环境（只读）", "label": "中文字体",
     "kind": "str", "desc": "自动探测；缺失会导致卡片图中文变方块", "editable": False},
    {"key": "PAPERCAST_ALLOW_ORIGINS", "attr": "allow_origins", "group": "运行环境（只读）", "label": "允许的前端来源",
     "kind": "list", "desc": "CORS 白名单", "editable": False, "restart": True},
]

SPEC_BY_KEY = {s["key"]: s for s in SPEC}
SECRET_MASK = "****"


def _mask(secret: str) -> str:
    """只暴露前 3 + 后 4，剩下的打码。短于 12 位就整体打码。"""
    if not secret:
        return ""
    if len(secret) < 12:
        return SECRET_MASK
    return f"{secret[:3]}{SECRET_MASK}{secret[-4:]}"


def _raw_value(s: dict[str, Any], env_file: dict[str, str]) -> tuple[str, str]:
    """返回 (展示用字符串, 来源)。来源：environment > .env > dsh-credential > default。"""
    key, attr = s["key"], s["attr"]
    val = getattr(settings, attr, None)
    plain = ""

    if isinstance(val, bool):
        plain = "on" if val else "off"
    elif isinstance(val, list):
        plain = ",".join(str(v) for v in val)
    else:
        plain = "" if val is None else str(val)

    if key in os.environ:
        source = "environment"
    elif key in env_file:
        source = ".env"
    elif key == "LLM_API_KEY":
        source = "dsh-credential" if _dsh_credential("GO_API_KEY") else "unset"
    else:
        source = "default"

    shown = _mask(plain) if s["kind"] == "secret" else plain
    return shown, source


def _public(s: dict[str, Any], env_file: dict[str, str]) -> dict[str, Any]:
    shown, source = _raw_value(s, env_file)
    item = {
        "key": s["key"],
        "group": s["group"],
        "label": s["label"],
        "kind": s["kind"],
        "desc": s["desc"],
        "editable": bool(s.get("editable", True)),
        "restart": bool(s.get("restart", False)),
        "value": shown,
        "source": source,
    }
    if s["kind"] == "secret":
        item["configured"] = bool(getattr(settings, s["attr"], ""))
    return item


class PatchBody(BaseModel):
    values: dict[str, Any] = {}


def _coerce(s: dict[str, Any], raw: Any) -> Optional[str]:
    """把前端来的值转成写进 .env 的字符串；None = 删除该键（回落默认值）。"""
    kind = s["kind"]
    if isinstance(raw, bool) and kind != "bool":
        raise ValueError("布尔值只能给 bool 类型的项")
    text = "" if raw is None else str(raw).strip()
    if kind == "secret":
        # 空 = 不修改（由调用方过滤，这里兜底）
        return text or None
    if text == "":
        return None  # 非密钥项留空 = 恢复默认
    if kind == "int":
        try:
            int(text)
        except ValueError:
            raise ValueError(f"{s['label']} 需要是整数") from None
    if kind == "bool" and text.lower() not in ("on", "off", "1", "0", "true", "false", "yes", "no"):
        raise ValueError(f"{s['label']} 只接受 on/off")
    if kind == "list":
        text = ",".join(p.strip() for p in text.split(",") if p.strip())
    if "\n" in text:
        raise ValueError("值里不能有换行")
    return text


def _write_env(updates: dict[str, Optional[str]]) -> Path:
    """原子改写 .env：保留注释与顺序，只动白名单键。"""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = line.strip().startswith("#") or not line.strip()
        if m or "=" not in line:
            out.append(line)
            continue
        k = line.split("=", 1)[0].strip()
        if k in updates:
            seen.add(k)
            v = updates[k]
            if v is not None:
                out.append(f"{k}={v}")
        else:
            out.append(line)

    added = [k for k in updates if k not in seen and updates[k] is not None]
    if added:
        if out and out[-1].strip():
            out.append("")
        out.append("# 由「设置 → 模型与 API」写入")
        out.extend(f"{k}={updates[k]}" for k in added)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), prefix=".env.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o600)   # 里面有密钥，别让同机其他用户读到
        os.replace(tmp, ENV_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return ENV_PATH


def _hot_swap() -> None:
    """重新读 .env + 环境变量，就地把单例刷新；已构造的 LLMClient 持有同一对象，故立即生效。"""
    fresh = Settings.load()
    for k, v in vars(fresh).items():
        setattr(settings, k, v)


@router.get("")
async def get_config() -> dict[str, Any]:
    """全部可配项 + 当前值 + 值来自哪里。密钥只回打码值。"""
    return {
        "envFile": str(ENV_PATH),
        "envFileExists": ENV_PATH.exists(),
        "items": [_public(s, _parse_env_file(ENV_PATH)) for s in SPEC],
    }


@router.patch("")
async def patch_config(body: PatchBody) -> dict[str, Any]:
    """按白名单写入 .env 并热生效。密钥留空 = 不修改。"""
    updates: dict[str, Optional[str]] = {}
    for key, raw in (body.values or {}).items():
        s = SPEC_BY_KEY.get(key)
        if s is None or not s.get("editable", True):
            raise PlatformError(400, "CONFIG_READONLY", f"不可配置的键：{key}")
        if s["kind"] == "secret" and (raw is None or str(raw).strip() == ""):
            continue  # 留空 = 不动
        try:
            updates[key] = _coerce(s, raw)
        except ValueError as e:
            raise PlatformError(400, "CONFIG_INVALID", f"{key}：{e}") from None

    if not updates:
        return {"changed": [], "envFile": str(ENV_PATH), "applied": False}

    _write_env(updates)
    _hot_swap()
    return {
        "changed": sorted(updates),
        "envFile": str(ENV_PATH),
        "applied": True,
        "restartNeeded": [k for k in updates if SPEC_BY_KEY[k].get("restart")],
    }


@router.post("/reload")
async def reload_config() -> dict[str, Any]:
    """手工改过 .env 后，不重启后端也能让配置生效。"""
    _hot_swap()
    return {"reloaded": True, "envFile": str(ENV_PATH)}


@router.post("/test")
async def test_llm() -> dict[str, Any]:
    """连通性探针：用当前配置发一个最小请求，回显延迟与模型回话。不含任何密钥。"""
    client = LLMClient(settings)
    if not client.available:
        raise PlatformError(400, "LLM_NOT_CONFIGURED", "没有可用的密钥（LLM_API_KEY / GO_API_KEY）")

    started = time.perf_counter()
    try:
        # 预算必须给足：这个模型是 reasoning 模型，会先把 token 花在思维链上，
        # 给 16 会被 finish_reason=length 判成空内容（实测踩过）。1024 + 允许一次加倍重试。
        reply = await client.chat(
            "你是连通性探针。只回复 OK 两个字符，不要解释。",
            "OK?",
            max_tokens=1024,
            retries=1,
        )
    except LLMError as e:
        return {
            "ok": False,
            "ms": round((time.perf_counter() - started) * 1000),
            "code": e.code,
            "message": str(e),
            "model": settings.llm_model,
            "baseUrl": settings.llm_base_url,
        }
    return {
        "ok": True,
        "ms": round((time.perf_counter() - started) * 1000),
        "reply": (reply or "").strip()[:40],
        "model": settings.llm_model,
        "baseUrl": settings.llm_base_url,
    }

