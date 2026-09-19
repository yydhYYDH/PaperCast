"""文章风格清单（GET /api/styles）—— 把「平台 × 讲述者人格」如实端给前端。

为什么单独一个只读端点：风格页要展示的是**内容风格**（小红书 · 专业科普、小红书 · 震惊流、
知乎 · 专业解读…），选项、口语名、硬约束都来自 `app/styles.py` 这一份真源；
界面不自己拼 id、不自己起名字，也就不会出现「界面上写着作者自述、后端早把 author 退役了」这种漂移。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from . import styles

router = APIRouter(prefix="/api/styles", tags=["styles"])


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
