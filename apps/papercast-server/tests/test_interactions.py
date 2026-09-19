"""互动 P1：只读评论/通知 + 起草回复（app/interactions.py）。

用户 2026-09-19 拍板：互动合并进主 agent，按风险分三步走 —— P1 只读+起草（这里）、
P2 逐条确认后才发送、全自动不做。这份用例锁住 P1 的四条性质：

1. **只读**：模块里出现的 MCP 调用路径**只能**是只读路由（写类路由一个都不许有）——
   这条是防「以后顺手把自动回复接上」的；
2. **读不到就说读不到**：MCP 不可达/报错时 gap 里要有原因，items 为空、canSend=False，
   **绝不返回「0 条评论」冒充读到过**；
3. **起草 ≠ 发送**：草稿落 var/interactions/drafts.jsonl（sent=False），返回值里 canSend 恒为 False；
4. 通知条目的字段映射（有 comment_id 才算「评论」，才谈得上回复）。

全部离线：MCP 用替身、LLM 用替身、落盘用 tmp_path，不联网、不碰真实 var/。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app import interactions as I
from app.platforms import PlatformError


# ---------- 替身 ----------


class FakeLLM:
    available = True

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def chat_json(self, system: str, user: str, **kw: Any) -> Any:
        self.calls.append((system, user))
        return self.payload


def mcp_stub(payloads: dict[str, Any], errors: dict[str, Exception] | None = None):
    """按路径返回固定 payload 的 _mcp_get 替身；errors 里的路径直接抛。

    注意形状：真实 MCP 的 HTTP 层返回 {success, data: {data: <真结果>}}，而 _mcp_get 已经剥掉
    最外面那层，所以替身要返回 {"data": <真结果>} —— 少包一层就等于把线上的形状测错了。
    """
    seen: list[str] = []

    async def _get(path: str) -> Any:
        seen.append(path)
        err = (errors or {}).get(path.split("?")[0])
        if err:
            raise err
        for key, val in payloads.items():
            if path.startswith(key):
                return {"data": val}
        raise AssertionError(f"没准备这条路径的替身：{path}")

    return _get, seen


#: 「评论和@」一页通知（MCP 侧的 NotificationList：tab / filtered / items）
NOTIF = {
    "tab": "mentions",
    "filtered": 2,
    "items": [
        {
            "id": "n1",
            "type": "comment",
            "time": 1789783000000,
            "from": {"user_id": "u1", "nickname": "张三"},
            "comment_id": "c1",
            "comment_text": "这个方法能用在临床上吗？",
            "feed_id": "f1",
            "feed_xsec_token": "TKN-1",
            "feed_title": "DeepRare",
        },
        {"id": "n2", "type": "follow", "title": "李四 关注了你", "time": 1789783100000, "from": {"nickname": "李四"}},
    ],
}
UNREAD = {"mentions": 2, "likes": 5, "connections": 1, "unread": 8}


# ---------- 1) 只读红线 ----------


def test_only_read_only_routes_are_called() -> None:
    """模块里对 MCP 的调用路径必须全是只读路由 —— 写类路由一律不许出现。"""
    src = Path(I.__file__).read_text(encoding="utf-8")
    called = [ln.strip() for ln in src.splitlines() if "_mcp_get(" in ln and "def _mcp_get" not in ln]
    assert called, "没找到任何 MCP 调用？读法要跟着改"
    for line in called:
        assert "/api/v1/notifications/" in line, f"这个调用不在只读白名单里：{line}"
    write_routes = I.write_routes_are_disallowed()
    for dead in write_routes:
        assert f'_mcp_get("{dead}' not in src and f"_mcp_get(f\"{dead}" not in src, f"写类路由不许被调用：{dead}"


# ---------- 2) 正常读一页 ----------


def test_list_interactions_maps_items(monkeypatch: pytest.MonkeyPatch) -> None:
    get, seen = mcp_stub({"/api/v1/notifications/list": NOTIF, "/api/v1/notifications/unread": UNREAD})
    monkeypatch.setattr(I, "_mcp_get", get)
    out = asyncio.run(I.list_interactions(10))

    assert out["canSend"] is False and out["stage"] == "P1"          # 契约里写死「不发送」
    assert out["unread"] is None                                      # 默认不多开一次浏览器去读未读数
    assert out["filtered"] == 2                                       # 过滤数如实带出来
    assert out["gap"] == "" and out["errors"] == []

    first = out["items"][0]
    assert first["author"] == "张三" and first["commentId"] == "c1" and first["canReply"] is True
    assert first["workTitle"] == "DeepRare" and first["xsecToken"] == "TKN-1"
    second = out["items"][1]
    assert second["kind"] == "follow" and second["canReply"] is False  # 关注通知没有可回的评论
    assert len(seen) == 1                                              # 默认一次动作只花一次浏览器预算


# ---------- 3) 读不到就说读不到 ----------


def test_unread_is_opt_in_and_costs_one_more_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式要未读数才多打一次；不显式要就一次都不多打（浏览器预算是最贵的资源）。"""
    get, seen = mcp_stub({"/api/v1/notifications/list": NOTIF, "/api/v1/notifications/unread": UNREAD})
    monkeypatch.setattr(I, "_mcp_get", get)
    out = asyncio.run(I.list_interactions(10, with_unread=True))
    assert out["unread"] == {"mentions": 2, "likes": 5, "connections": 1, "unread": 8}
    assert len(seen) == 2


def test_unreachable_mcp_reports_gap_and_does_not_retry_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    get, seen = mcp_stub({}, {"/api/v1/notifications/list": PlatformError(502, "MCP_UNREACHABLE", "小红书通道不可达（ConnectError）")})
    monkeypatch.setattr(I, "_mcp_get", get)
    out = asyncio.run(I.list_interactions(10, with_unread=True))

    assert out["items"] == []
    assert "小红书通道不可达" in out["gap"] and out["errors"]
    assert out["unread"] is None
    assert len(seen) == 1, "列表已经失败时不该再为未读数多开一次浏览器"


def test_empty_but_readable_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """真读到空列表（确实没人评论）→ gap 说清「可能真的还没有人评论」，但不算错误。"""
    empty = {"tab": "mentions", "filtered": 0, "items": []}
    get, _ = mcp_stub({"/api/v1/notifications/list": empty})
    monkeypatch.setattr(I, "_mcp_get", get)
    out = asyncio.run(I.list_interactions(10))
    assert out["items"] == [] and out["errors"] == []
    assert "可能真的还没有人评论" in out["gap"]


def test_mcp_error_code_is_surfaced(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 自己报错（例如未登录）→ 把它的原话与建议带上，不吞成空列表。"""

    async def _boom(path: str) -> Any:
        raise PlatformError(502, "MCP_ERROR", "小红书通道拒绝了这次读取：登录已失效—— 先去「平台账号」扫码登录")

    monkeypatch.setattr(I, "_mcp_get", _boom)
    out = asyncio.run(I.list_interactions(10))
    assert "登录已失效" in out["gap"] and "扫码" in out["gap"]
    assert out["canSend"] is False


# ---------- 4) 起草：只落盘，不发送 ----------


def test_draft_reply_persists_and_never_claims_to_send(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeLLM({"reply": "临床验证还没做，我在做的事是让人更快读懂它。", "why": "对方问的是能不能落地，先给边界再给出路"})
    monkeypatch.setattr(I, "LLMClient", lambda _settings: fake)
    dst = tmp_path / "interactions" / "drafts.jsonl"
    monkeypatch.setattr(I, "_drafts_path", lambda: dst)

    out = asyncio.run(
        I.draft_reply(I.DraftRequest(commentText="这个方法能用在临床上吗？", author="张三", workTitle="DeepRare"))
    )

    assert out["canSend"] is False and out["stage"] == "P1"
    assert out["savedTo"] == I.DRAFTS_REL
    draft = out["draft"]
    assert draft["reply"].startswith("临床验证") and draft["sent"] is False
    assert draft["commentText"] == "这个方法能用在临床上吗？"

    written = [json.loads(ln) for ln in dst.read_text(encoding="utf-8").splitlines()]
    assert len(written) == 1 and written[0]["reply"] == draft["reply"] and written[0]["sent"] is False

    # 提示词里必须带上评论原文，且明确「不许编数字/不许承诺时间」
    system, user = fake.calls[0]
    assert "评论原文" in user and "张三" in user
    assert "不许编" in system and "时间承诺" in system


def test_draft_reply_rejects_blank_comment() -> None:
    with pytest.raises(ValidationError):
        I.DraftRequest(commentText="   ")


def test_draft_reply_reports_model_garbage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """模型没写出可用草稿 → 明确报错，不许返回一条空草稿假装成功。"""
    monkeypatch.setattr(I, "LLMClient", lambda _settings: FakeLLM({"why": "只有理由没有回复"}))
    monkeypatch.setattr(I, "_drafts_path", lambda: tmp_path / "drafts.jsonl")
    with pytest.raises(PlatformError) as e:
        asyncio.run(I.draft_reply(I.DraftRequest(commentText="你好", author="x")))
    assert e.value.code == "DRAFT_EMPTY"


def test_drafts_path_lives_in_var_interactions() -> None:
    assert I._drafts_path().as_posix().endswith("/var/interactions/drafts.jsonl")
    assert I._sent_path().as_posix().endswith("/var/interactions/sent.jsonl")


# ---------- 5) P2：真发（默认关，且只走两条写路由） ----------


def test_send_is_off_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """开关默认关：即使前端点了确认，也只得到 SEND_DISABLED —— 代码可以先上，手不能先动。"""
    monkeypatch.delenv(I.SEND_ENV, raising=False)
    monkeypatch.setattr(I, "_sent_path", lambda: tmp_path / "sent.jsonl")
    with pytest.raises(PlatformError) as e:
        asyncio.run(I.reply_to_comment(I.ReplyRequest(content="谢谢", commentId="c1", confirmed=True)))
    assert e.value.code == "SEND_DISABLED"
    assert not (tmp_path / "sent.jsonl").exists()


def test_send_requires_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """少写 confirmed（或写成 false）一律拒 —— 不能靠「默认就是同意」把话说出去。"""
    monkeypatch.setenv(I.SEND_ENV, "1")
    for body in ({"content": "谢谢", "commentId": "c1"}, {"content": "谢谢", "commentId": "c1", "confirmed": False}):
        with pytest.raises(PlatformError) as e:
            asyncio.run(I.reply_to_comment(I.ReplyRequest(**body)))
        assert e.value.code == "CONFIRM_REQUIRED"


def test_send_needs_a_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(I.SEND_ENV, "1")
    with pytest.raises(PlatformError) as e:
        asyncio.run(I.reply_to_comment(I.ReplyRequest(content="谢谢", confirmed=True)))
    assert e.value.code == "NO_TARGET"


def test_send_picks_the_right_write_route_and_records_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """两种回法各走各的路由；真发一条要在 sent.jsonl 留一行（sent 恒为 true）。"""
    monkeypatch.setenv(I.SEND_ENV, "1")
    monkeypatch.setattr(I, "_sent_path", lambda: tmp_path / "sent.jsonl")
    I._SENT_AT.clear()

    calls: list[tuple[str, dict[str, Any]]] = []

    async def _post(path: str, payload: dict[str, Any]) -> Any:
        calls.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(I, "_mcp_post", _post)

    note = asyncio.run(I.reply_to_comment(I.ReplyRequest(content="好的，我核对后回你", commentId="c1", confirmed=True)))
    assert calls[-1][0] == I.REPLY_VIA_NOTIFICATION
    assert calls[-1][1] == {"comment_id": "c1", "content": "好的，我核对后回你"}
    assert note["sent"] is True and note["stage"] == "P2" and note["savedTo"] == I.SENT_REL

    reply = asyncio.run(
        I.reply_to_comment(
            I.ReplyRequest(content="谢谢", commentId="c2", feedId="f1", xsecToken="TKN", confirmed=True)
        )
    )
    assert calls[-1][0] == I.REPLY_VIA_COMMENT
    assert calls[-1][1]["feed_id"] == "f1" and calls[-1][1]["xsec_token"] == "TKN" and calls[-1][1]["comment_id"] == "c2"
    assert reply["target"] == "comment"

    rows = [json.loads(ln) for ln in (tmp_path / "sent.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and all(r["sent"] is True for r in rows)
    assert rows[0]["content"] == "好的，我核对后回你"
    assert "xsec" not in json.dumps(rows[1]), "令牌不写进落盘记录"


def test_send_is_rate_limited(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """限速是护栏：循环/误触不该变成刷屏（20 条/小时）。"""
    monkeypatch.setenv(I.SEND_ENV, "1")
    monkeypatch.setattr(I, "_sent_path", lambda: tmp_path / "sent.jsonl")
    I._SENT_AT.clear()

    async def _post(path: str, payload: dict[str, Any]) -> Any:
        return {"success": True}

    monkeypatch.setattr(I, "_mcp_post", _post)
    for i in range(I.SEND_CAP_PER_HOUR):
        asyncio.run(I.reply_to_comment(I.ReplyRequest(content=f"第 {i} 条", commentId="c1", confirmed=True)))
    with pytest.raises(PlatformError) as e:
        asyncio.run(I.reply_to_comment(I.ReplyRequest(content="再来一条", commentId="c1", confirmed=True)))
    assert e.value.code == "SEND_RATE_LIMITED"
    I._SENT_AT.clear()


def test_mcp_post_refuses_routes_outside_the_send_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    """兜底：拿 _mcp_post 去调点赞/发帖这类路由，就地拦住。"""
    for bad in I.write_routes_are_disallowed():
        with pytest.raises(PlatformError) as e:
            asyncio.run(I._mcp_post(bad, {}))
        assert e.value.code == "WRITE_ROUTE_NOT_ALLOWED"


def test_module_never_calls_publish_or_like_routes() -> None:
    """读源码拦「以后顺手把点赞/发帖接上」：**写死的** MCP 路径只允许只读路由 + 回复那两条。

    注意只查**字面量**：reply_to_comment 里传给 _mcp_post 的是变量（白名单常量），
    变量那一路由 test_mcp_post_refuses_routes_outside_the_send_whitelist 兜底。
    """
    src = Path(I.__file__).read_text(encoding="utf-8")
    literals = set(re.findall(r'_mcp_(?:get|post)\(\s*f?"([^"]+)"', src))
    assert literals, "没找到任何 MCP 字面量路径？读法要跟着改"
    for path in literals:
        assert path.startswith("/api/v1/notifications/") or path in I.send_routes(), f"这个路由不在白名单里：{path}"
    assert set(I.send_routes()) == {I.REPLY_VIA_COMMENT, I.REPLY_VIA_NOTIFICATION}
    for dead in I.write_routes_are_disallowed():
        assert dead not in I.send_routes(), f"回复白名单里混进了对外动作：{dead}"
