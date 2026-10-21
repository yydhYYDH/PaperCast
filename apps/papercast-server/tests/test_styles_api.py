"""用户自定义人格（风格页 增/删/改）：合并、解析、CRUD、校验。

不触网、不写真 var/：`PAPERCAST_STYLES_FILE` 指到 tmp_path；直接调路由函数（不起服务）。
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app import prompts, styles, styles_api


@pytest.fixture
def store_file(monkeypatch, tmp_path):
    f = tmp_path / "styles" / "voices.json"
    monkeypatch.setenv("PAPERCAST_STYLES_FILE", str(f))
    styles.reload_user_voices()
    yield f
    styles.reload_user_voices()


def _entries(path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["voices"]


def test_create_merges_and_parses(store_file):
    styles_api.create_voice(styles_api.VoiceCreate(
        id="my-voice", label="我的风格", short="我的", hint="一句话", persona="你是……"))
    assert styles.parse_variant("xhs-my-voice") == ("xhs", "my-voice")
    assert styles.voice_spec("my-voice").persona.startswith("你是")
    menu = {s["variant"]: s for s in styles.style_menu()}
    assert menu["xhs-my-voice"]["custom"] is True
    assert menu["xhs-my-voice"]["short"] == "我的"
    assert _entries(store_file)[0]["id"] == "my-voice"


def test_create_without_id_generates_one(store_file):
    r = styles_api.create_voice(styles_api.VoiceCreate(label="火星风格", persona="你是火星来的。"))
    vid = r["voice"]["id"]
    assert vid.startswith("voice-")
    assert styles.parse_variant(f"xhs-{vid}") == ("xhs", vid)


def test_builtin_override_and_restore(store_file):
    styles_api.update_voice("independent", styles_api.VoiceUpdate(short="我改的"))
    assert styles.voice_spec("independent").short == "我改的"
    assert styles.voice_spec("independent").id == "independent"
    m = {s["voice"]: s for s in styles.style_menu() if s["platform"] == "xhs"}
    assert m["independent"]["overridden"] is True and m["independent"]["custom"] is False
    # 删除「覆盖」= 恢复默认，文件里那条也没了
    styles_api.delete_voice("independent")
    assert styles.voice_spec("independent").short == "专业科普"
    assert _entries(store_file) == []
    # 没被改过的内置，再删就没什么可恢复的
    with pytest.raises(HTTPException) as e:
        styles_api.delete_voice("independent")
    assert e.value.status_code == 400


def test_delete_custom(store_file):
    styles_api.create_voice(styles_api.VoiceCreate(id="tmp-one", label="临时", persona="x"))
    styles_api.delete_voice("tmp-one")
    assert styles.parse_variant("xhs-tmp-one") is None
    with pytest.raises(HTTPException) as e:
        styles_api.delete_voice("tmp-one")
    assert e.value.status_code == 404


def test_validation_rejects_bad_id_and_empty_fields():
    assert styles.validate_voice(vid="Bad Id", label="x", persona="y") is not None
    assert styles.validate_voice(vid="xhs", label="x", persona="y") is not None   # 不能和平台同名
    assert styles.validate_voice(vid="ok-id", label="", persona="y") is not None
    assert styles.validate_voice(vid="ok-id", label="x", persona="") is not None
    assert styles.validate_voice(vid="ok-id", label="x", persona="y") is None


def test_platform_name_id_rejected_via_api(store_file):
    with pytest.raises(HTTPException) as e:
        styles_api.create_voice(styles_api.VoiceCreate(id="xhs", label="x", persona="y"))
    assert e.value.status_code == 400


def test_persona_flows_into_prompt(store_file):
    styles_api.create_voice(styles_api.VoiceCreate(
        id="my-voice", label="我的风格", persona="你是火星来的评审。"))
    assert "你是火星来的评审。" in prompts.article_system("xhs", "my-voice")


def test_hook_voice_is_builtin_and_parseable():
    """从小红书爆款帖归纳的 hook 人格：内置、有语料支撑、可被 parse_variant 认出来。"""
    assert styles.parse_variant("xhs-hook") == ("xhs", "hook")
    v = styles.voice_spec("hook")
    assert v.sampled is True and v.short == "爆款拆解"
    assert "标题" in v.persona and "hook" in styles.all_voices()
