"""配置：env + .env 文件 + DSH 凭据兜底。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 工作区分层约定（见 docs/conventions.md）：运行期数据统一放 <workspace>/var/。
# 本后端按 apps/papercast-server/ 布局时，运行期数据落在工作区 var/；
# 若被单独拷出去跑（没有 apps/ 那一层），退回本组件内的 data/。
_WORKSPACE = ROOT.parent.parent
VAR_DIR = _WORKSPACE / "var" if (_WORKSPACE / "apps").is_dir() else ROOT / "data"


def _parse_env_file(path: Path) -> dict[str, str]:
    """.env 解析：够用即可（KEY=VALUE，支持 # 注释与首尾引号）。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def _dsh_credential(name: str) -> str:
    """从 ~/.dsh/.credentials.yaml 里取一个 key（DSH 已配置好的 LLM 通道）。

    只读不写；文件不存在或没这个 key 就返回空串，让调用方自己报错。
    """
    p = Path.home() / ".dsh" / ".credentials.yaml"
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(rf"^{re.escape(name)}\s*:\s*(\S+)\s*$", text, re.M)
    return m.group(1) if m else ""


def _detect_chrome() -> str:
    """探测 chrome-headless-shell（Playwright 缓存优先）。"""
    cache = Path.home() / ".cache" / "ms-playwright"
    if cache.is_dir():
        for pat in ("**/chrome-headless-shell-linux64/chrome-headless-shell", "**/chrome-headless-shell"):
            for hit in sorted(cache.glob(pat)):
                if os.access(hit, os.X_OK):
                    return str(hit)
    for name in ("chrome-headless-shell", "chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    return ""


CJK_STRICT = re.compile(
    r"(CJK|Noto\s*Sans\s*SC|NotoSansSC|Source\s*Han|SourceHan|HanSans|HanSerif|"
    r"msyh|YaHei|SimHei|SimSun|songti|hei|wqy|uming|ukai|DroidSansFallback|"
    r"\.ttc$)",
    re.I,
)


def find_cjk_font(explicit: str = "") -> str:
    """找一个**真的**含中日韩字形的字体。

    教训：不要用裸的 "SC" 之类的子串去匹配文件名 —— "DejaVuSansCondensed" 里就有 "sC"，
    会把无中文的字体当成 CJK 字体，卡片上的中文全变方块。所以这里只认白名单，
    并优先问 fontconfig（fc-list :lang=zh，它是权威答案）。
    """
    if explicit and Path(explicit).is_file():
        return explicit

    # 1. 明确路径（含用户目录下的 waic/msyh 这类常见投放点）
    home = Path.home()
    for c in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        home / ".local/share/fonts/waic/msyh.ttc",
        home / ".fonts/waic/msyh.ttc",
        "/usr/share/fonts/truetype/msttcorefonts/msyh.ttc",
    ]:
        if str(c) and Path(c).is_file():
            return str(c)

    # 2. fontconfig（权威）：问系统「哪些字体支持中文」
    if shutil.which("fc-list"):
        try:
            out = subprocess.run(
                ["fc-list", ":lang=zh", "-f", "%{file}\n"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            for line in out.splitlines():
                p = line.strip()
                if p and Path(p).is_file():
                    return p
        except Exception:
            pass

    # 3. 扫字体目录（严格白名单）
    for root in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".local/share/fonts"):
        if not root.is_dir():
            continue
        try:
            for f in sorted(root.rglob("*")):
                if f.suffix.lower() in (".ttc", ".otf", ".ttf") and CJK_STRICT.search(f.name):
                    return str(f)
        except OSError:
            continue
    return ""


def has_cjk_glyphs(font_path: str, sample: str = "论文速读") -> bool:
    """真刀真枪验证字体有没有中文字形（用 fontTools 查 cmap；没有就退回 PIL 探测）。"""
    if not font_path or not Path(font_path).is_file():
        return False
    try:
        from fontTools.ttLib import TTFont, TTCollection

        with open(font_path, "rb") as fh:
            head = fh.read(4)
        if head == b"ttcf":
            fonts = TTCollection(font_path, lazy=True).fonts
        else:
            fonts = [TTFont(font_path, lazy=True)]
        for font in fonts:
            cmap = font.getBestCmap() or {}
            if all(ord(ch) in cmap for ch in sample):
                return True
    except Exception:
        pass
    try:
        from PIL import ImageFont

        f = ImageFont.truetype(font_path, 40)
        return bool(f.getmask(sample).getbbox())
    except Exception:
        return False


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = field(default_factory=lambda: VAR_DIR / "runs")
    upload_dir: Path = field(default_factory=lambda: VAR_DIR / "uploads")
    allow_origins: list[str] = field(default_factory=lambda: [
        "http://127.0.0.1:5178",
        "http://localhost:5178",
    ])
    intake_engine: str = "pymupdf"
    cards_enabled: bool = True
    # 小红书组图（guizang 技能链路）：on | off | auto（auto = 装了技能才跑，见 app/modules/cards_deck.py）
    poster_deck: str = "auto"
    chrome: str = ""
    cjk_font: str = ""
    max_upload_mb: int = 200
    llm_base_url: str = "https://opencode.ai/zen/go/v1"
    llm_model: str = "deepseek-v4.1-flash"
    llm_api_key: str = ""
    llm_timeout_sec: int = 600
    llm_max_tokens: int = 16000
    # 对所有 LLM 调用生效的硬上限；0 = 不限制（默认，等于保持既有行为）
    llm_max_tokens_cap: int = 0
    xhs_mcp_base: str = "http://127.0.0.1:18060"
    zhihu_publisher_base: str = "http://127.0.0.1:18070"
    bilibili_publisher_base: str = "http://127.0.0.1:18080"
    # 素材路径映射（可选）：「本机前缀=通道服务那侧的前缀」，逗号分隔多条，长的优先。
    # **跨机器时必须配**：后端在 WSL 里、小红书 MCP 跑在 Windows 上时，我们递过去的
    # `/home/yydh/hack/...` 在对面根本不存在，MCP 只会回一句
    # 「视频文件不存在或不可访问: CreateFile …: The system cannot find the path specified.」
    # （2026-09-19 实测，1.8ms 就失败，浏览器都没起）。配好后递的是对端读得到的写法。
    # 例：CHANNEL_PATH_MAP=/home/yydh/hack=//wsl.localhost/Ubuntu/home/yydh/hack
    # 同机部署（Linux 服务器上通道服务与后端同机）留空即可 —— 路径原样传递，零影响。
    channel_path_map: str = ""
    # 启用的渠道（规范 id，逗号分隔）；渠道实现见 app/channels/
    # x = X（推特）：material-only 渠道 —— 只把英文 thread 落成素材包，不接投递、不会真发
    channels: list[str] = field(default_factory=lambda: ["xiaohongshu", "zhihu", "bilibili", "x"])
    # 真实投递前的二次校验账号（可选）：填了的话渠道服务会比对该账号，防串号
    publish_confirm_account: str = ""

    @classmethod
    def load(cls) -> "Settings":
        env = {**_parse_env_file(ROOT / ".env"), **os.environ}
        s = cls()

        def pick(key: str, default: str) -> str:
            return (env.get(key) or default).strip()

        s.host = pick("PAPERCAST_HOST", s.host)
        s.port = int(pick("PAPERCAST_PORT", str(s.port)))
        s.data_dir = Path(pick("PAPERCAST_DATA_DIR", str(s.data_dir))).expanduser()
        s.upload_dir = Path(pick("PAPERCAST_UPLOAD_DIR", str(s.upload_dir))).expanduser()
        origins = pick("PAPERCAST_ALLOW_ORIGINS", ",".join(s.allow_origins))
        s.allow_origins = [o.strip() for o in origins.split(",") if o.strip()]
        s.intake_engine = pick("PAPERCAST_INTAKE_ENGINE", s.intake_engine)
        s.cards_enabled = pick("PAPERCAST_CARDS", "on").lower() in ("1", "on", "true", "yes")
        deck_mode = pick("PAPERCAST_POSTER_DECK", "auto").lower()
        s.poster_deck = deck_mode if deck_mode in ("on", "off", "auto") else "auto"
        s.chrome = pick("PAPERCAST_CHROME", "") or _detect_chrome()
        s.cjk_font = pick("PAPERCAST_CJK_FONT", "") or find_cjk_font()
        s.max_upload_mb = int(pick("MAX_UPLOAD_MB", str(s.max_upload_mb)))
        s.llm_base_url = pick("LLM_BASE_URL", s.llm_base_url).rstrip("/")
        s.llm_model = pick("LLM_MODEL", s.llm_model)
        s.llm_api_key = pick("LLM_API_KEY", "") or _dsh_credential("GO_API_KEY")
        s.llm_timeout_sec = int(pick("LLM_TIMEOUT_SEC", str(s.llm_timeout_sec)))
        s.llm_max_tokens = int(pick("LLM_MAX_TOKENS", str(s.llm_max_tokens)))
        s.llm_max_tokens_cap = int(pick("LLM_MAX_TOKENS_CAP", str(s.llm_max_tokens_cap)))
        s.xhs_mcp_base = pick("XHS_MCP_BASE", s.xhs_mcp_base).rstrip("/")
        s.zhihu_publisher_base = pick("ZHIHU_PUBLISHER_BASE", s.zhihu_publisher_base).rstrip("/")
        s.bilibili_publisher_base = pick("BILIBILI_PUBLISHER_BASE", s.bilibili_publisher_base).rstrip("/")
        s.channel_path_map = pick("CHANNEL_PATH_MAP", s.channel_path_map)
        s.channels = [c.strip() for c in pick("PAPERCAST_CHANNELS", ",".join(s.channels)).split(",") if c.strip()]
        s.publish_confirm_account = pick("PUBLISH_CONFIRM_ACCOUNT", s.publish_confirm_account)

        s.data_dir.mkdir(parents=True, exist_ok=True)
        s.upload_dir.mkdir(parents=True, exist_ok=True)
        return s


settings = Settings.load()
