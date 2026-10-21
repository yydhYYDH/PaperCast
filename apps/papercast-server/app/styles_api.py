"""文章风格清单 + 用户自定义人格（`/api/styles`）。

- `GET /api/styles`：平台 × 讲述者人格的清单（风格页展示），选项/口语名/硬约束都来自
  `app/styles.py` 这一份真源 —— 界面不自己拼 id、不自己起名字。
- `GET/POST/PATCH/DELETE /api/styles/voices[/{id}]`：**用户自定义人格的增删改查**（2026-09-23）。
  内置人格（VOICES）是只读真源，用户改动落 `var/styles/voices.json`（不进 git）；读取时与内置
  合并：同 id 覆盖内置、新 id 是自定义。删除内置的「覆盖」= 恢复默认。
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import styles

router = APIRouter(prefix="/api/styles", tags=["styles"])


class VoiceCreate(BaseModel):
    # 留空则从名称生成（中文名生成不出来时回落 voice-xxxx）
    id: str = ""
    label: str = Field(min_length=1, max_length=styles.MAX_LABEL)
    short: str = Field(default="", max_length=styles.MAX_SHORT)
    hint: str = Field(default="", max_length=styles.MAX_HINT)
    persona: str = Field(min_length=1, max_length=styles.MAX_PERSONA)


class VoiceUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=styles.MAX_LABEL)
    short: Optional[str] = Field(default=None, max_length=styles.MAX_SHORT)
    hint: Optional[str] = Field(default=None, max_length=styles.MAX_HINT)
    persona: Optional[str] = Field(default=None, max_length=styles.MAX_PERSONA)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:32]


def _flags(vid: str) -> dict[str, object]:
    return styles._voice_flags(vid)


def _public(v: styles.VoiceSpec) -> dict[str, Any]:
    return {
        "id": v.id,
        "label": v.label,
        "short": v.short or v.label,
        "hint": v.hint,
        "anchor": v.anchor,
        "sampled": "1" if v.sampled else "0",
        "persona": v.persona,
        **_flags(v.id),
    }


@router.get("")
def list_styles() -> dict[str, Any]:
    return {
        "default": {
            "platform": styles.DEFAULT_PLATFORM,
            "voice": styles.DEFAULT_VOICE,
            "variant": styles.variant_id(styles.DEFAULT_PLATFORM, styles.DEFAULT_VOICE),
        },
        "maxVariants": styles.MAX_VARIANTS,
        "platforms": styles.platform_menu(),
        "voices": styles.voice_menu(),
        # 组合清单（前端按平台分组渲染），含每条风格的口语名与一句话手感
        "styles": styles.style_menu(),
    }


@router.get("/voices/{voice_id}")
def get_voice(voice_id: str) -> dict[str, Any]:
    vid = (voice_id or "").strip().lower()
    if vid not in styles.all_voices():
        raise HTTPException(status_code=404, detail=f"没有这条风格：{voice_id}")
    return _public(styles.voice_spec(vid))


@router.post("/voices", status_code=201)
def create_voice(body: VoiceCreate) -> dict[str, Any]:
    vid = _slug(body.id or body.label)
    if not vid:
        vid = "voice-" + uuid.uuid4().hex[:6]
    try:
        spec = styles.upsert_user_voice(vid=vid, label=body.label, short=body.short,
                                        hint=body.hint, persona=body.persona)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"风格「{spec.short or spec.label}」已保存", "voice": _public(spec)}


@router.patch("/voices/{voice_id}")
def update_voice(voice_id: str, body: VoiceUpdate) -> dict[str, Any]:
    vid = (voice_id or "").strip().lower()
    if vid not in styles.all_voices():
        raise HTTPException(status_code=404, detail=f"没有这条风格：{voice_id}")
    cur = styles.voice_spec(vid)  # 内置或已存在的自定义，作为未提供字段的底
    try:
        spec = styles.upsert_user_voice(
            vid=vid,
            label=body.label if body.label is not None else cur.label,
            short=body.short if body.short is not None else cur.short,
            hint=body.hint if body.hint is not None else cur.hint,
            persona=body.persona if body.persona is not None else cur.persona,
            anchor=cur.anchor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"风格「{spec.short or spec.label}」已更新", "voice": _public(spec)}


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str) -> dict[str, Any]:
    vid = (voice_id or "").strip().lower()
    if vid not in styles.all_voices():
        raise HTTPException(status_code=404, detail=f"没有这条风格：{voice_id}")
    if styles.is_builtin_voice(vid):
        # 内置人格：删掉「覆盖」= 恢复默认；没被改过就没什么可恢复的
        if not styles.delete_user_voice(vid):
            raise HTTPException(status_code=400, detail="这条内置风格没有被改过，不用恢复")
        v = styles.VOICES[vid]
        return {"message": f"「{v.short or v.label}」已恢复默认"}
    styles.delete_user_voice(vid)
    return {"message": f"自定义风格「{voice_id}」已删除"}
