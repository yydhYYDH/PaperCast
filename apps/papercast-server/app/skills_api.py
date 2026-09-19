"""技能目录（GET /api/skills）—— 把「个性化层」的素材如实端给前端。

前端要能**展示**现有的风格技能（而不是把它们的规矩抄一份到界面里），所以这里只做两件事：
列目录、读原文。规矩只有一条：**只读，且路径写死在一组白名单根里**（不允许任意路径穿越）。

根与优先级与 dsh 的技能发现一致：
  1. <工作区>/.dsh/skills        （本仓库自己的技能）
  2. <工作区>/.agents/skills
  3. ~/.dsh/skills
  4. ~/.agents/skills            （ops/install_skills.sh 装的第三方设计技能）
同名时靠前的优先。技能名取 SKILL.md frontmatter 的 name（缺了就退回目录名）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from .platforms import PlatformError

router = APIRouter(prefix="/api/skills", tags=["skills"])

WS = Path(__file__).resolve().parents[3]  # apps/papercast-server/app/skills_api.py → 工作区根
HOME = Path.home()

# 顺序即优先级：先仓库自己的，再用户目录的
ROOTS: list[tuple[str, Path]] = [
    ("repo", WS / ".dsh" / "skills"),
    ("repo", WS / ".agents" / "skills"),
    ("user", HOME / ".dsh" / "skills"),
    ("user", HOME / ".agents" / "skills"),
]

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BODY_MAX = 60_000
DESC_MAX = 400

#: 风格类技能：前端把它们排在「风格」一组里（其余技能折叠起来，别喧宾夺主）
STYLE_SKILLS = {
    "papercast-frontend",
    "minimalist-ui",
    "frontend-design",
    "impeccable",
    "design-spacing-rhythm",
    "guizang-social-card-skill",
}


def _frontmatter(text: str) -> dict[str, str]:
    """只解析 SKILL.md 头部那几行 YAML（够用即可，不引依赖）。"""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    if end < 0:
        return out
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _read_skill(root_label: str, root: Path, directory: Path) -> dict[str, Any] | None:
    md = directory / "SKILL.md"
    if not md.is_file():
        return None
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm = _frontmatter(text)
    name = fm.get("name") or directory.name
    if not NAME_RE.match(name):
        return None
    refs = directory / "references"
    return {
        "name": name,
        "description": (fm.get("description") or "")[:DESC_MAX],
        "origin": root_label,
        "dir": str(directory),
        "root": str(root),
        # 有分册的技能让前端知道「展开还能看更多」，别把长文塞进列表
        "references": sorted(p.name for p in refs.glob("*") if p.is_file()) if refs.is_dir() else [],
        "style": name in STYLE_SKILLS,
        "_body": text,
    }


def _discover() -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for label, root in ROOTS:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            info = _read_skill(label, root, child)
            if info and info["name"] not in found:  # 靠前的根优先
                found[info["name"]] = info
    # 风格类排前面，其余按名字；同组内仓库自己的优先
    return sorted(found.values(), key=lambda s: (0 if s["style"] else 1, 0 if s["origin"] == "repo" else 1, s["name"]))


def _public(info: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in info.items() if not k.startswith("_")}


@router.get("")
def list_skills() -> list[dict[str, Any]]:
    """列出本机能找到的所有技能（含各自的规矩摘要）。只读目录，不改任何东西。"""
    return [_public(s) for s in _discover()]


@router.get("/{name}")
def get_skill(name: str) -> dict[str, Any]:
    """读一个技能的 SKILL.md 原文（给前端「看它的规矩」用）。"""
    if not NAME_RE.match(name):
        raise PlatformError(400, "BAD_SKILL_NAME", "技能名不合法（只允许小写字母、数字和短横线）")
    for info in _discover():
        if info["name"] == name:
            body = info["_body"]
            data = _public(info)
            data["body"] = body[:BODY_MAX]
            data["truncated"] = len(body) > BODY_MAX
            return data
    raise PlatformError(404, "SKILL_NOT_FOUND", f"没有找到技能「{name}」：看 /api/skills 里有哪些")
