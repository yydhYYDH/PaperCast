"""对话式发布任务：一句话 → 动作提案（app/chat_api.py 的「意图 → 动作提案」一节）。

背景（用户 2026-09-19 要求）：工作台的主 agent 原先只能问答，不能发任务。现在它多了一个能力：
认出意图就给一张**动作卡**（返回体里的 `action`），前端渲染成「一句话 + 一个动词按钮」，点了才执行。

这里锁住三条不能被改坏的性质：
1. **服务端零副作用**：_propose 只产出「做什么 + 参数」，不投递、不起停进程、不写任何文件；
2. **闸门只认内存里的真状态**：没有等待放行的阶段时，「放行」这类话**不许**递出动作卡（否则前端会
   拿一个早已不成立的 stageId/optionId 去打闸门接口）；
3. **默认动作是推荐项**：说「放行」要落到 continue，说「草稿」落到 draft，说「跳过」落到 skip。

不联网、不起服务、不改真实 var/runs。
"""

from __future__ import annotations

from app.chat_api import _choose_option, _pending_gate, _propose
from app.models import GateOption, PaperRun, SourceInput, Stage, StageGate

PUBLISH_GATE = StageGate(
    id="publish-gate",
    label="发布前人工闸门",
    detail="即将投递到小红书与知乎：6 张图，正文 773 字。",
    options=[
        GateOption(id="continue", label="确认发布"),
        GateOption(id="draft", label="仅存草稿"),
        GateOption(id="skip", label="本轮不发布"),
    ],
)


def make_run(status: str = "waiting") -> PaperRun:
    """一条停在发布闸门上的运行。"""
    return PaperRun(
        id="run_test",
        createdAt=1,
        title="DeepRare",
        source=SourceInput(kind="arxiv", value="2502.12345"),
        status="waiting",  # type: ignore[arg-type]
        stages=[
            Stage(id="understand", label="论文理解层", engine="e", status="done"),
            Stage(id="publish", label="发布与运营", engine="e", status="waiting", gate=PUBLISH_GATE),  # type: ignore[arg-type]
        ],
    )


def kind_of(text: str, run: PaperRun | None) -> str | None:
    proposed = _propose(text, "run_test", run)
    if proposed is None:
        return None  # 认不出来 → 交给模型 / 或只回话
    _reply, action = proposed
    return None if action is None else str(action["kind"])


# ---------- 闸门 ----------


def test_gate_default_action_is_the_recommended_one() -> None:
    """「放行」= 第一个选项（推荐项 = 确认发布），且标成 public（真发到平台上）。"""
    proposed = _propose("放行", "run_test", make_run())
    assert proposed is not None
    _reply, action = proposed
    assert action is not None
    assert action["kind"] == "gate"
    assert action["risk"] == "public"
    assert action["needsConfirm"] is True
    assert action["params"]["stageId"] == "publish"
    assert action["params"]["optionId"] == "continue"
    assert action["confirmLabel"] == "确认发布"


def test_gate_words_map_to_their_options() -> None:
    for text, option in [("只存草稿", "draft"), ("跳过这一轮", "skip"), ("确认发布", "continue")]:
        proposed = _propose(text, "run_test", make_run())
        assert proposed is not None, text
        _reply, action = proposed
        assert action is not None and action["params"]["optionId"] == option, text


def test_no_pending_gate_means_no_gate_action() -> None:
    """没有等待放行的阶段时，「放行」不许递出动作卡 —— 这是防「对空气放行」的那条。"""
    done = make_run()
    done.stages[1].status = "done"  # type: ignore[union-attr]
    done.stages[1].gate.resolved = "continue"  # type: ignore[union-attr]
    assert _pending_gate(done) is None
    assert kind_of("放行", done) != "gate"
    assert kind_of("放行", None) is None


def test_choose_option_falls_back_to_first() -> None:
    assert _choose_option(PUBLISH_GATE, "你看着办").id == "continue"  # type: ignore[union-attr]
    assert _choose_option(PUBLISH_GATE, "先存草稿").id == "draft"  # type: ignore[union-attr]
    assert _choose_option(PUBLISH_GATE, "算了不发了").id == "skip"  # type: ignore[union-attr]


# ---------- 其它动作 ----------


def test_metrics_action_is_readonly_and_needs_no_confirm() -> None:
    """只读动作不需要人工闸门，前端可以直接执行（少一次点击）。"""
    proposed = _propose("看下现在的播放和点赞", "run_test", make_run())
    assert proposed is not None
    _reply, action = proposed
    assert action is not None
    assert action["kind"] == "metrics"
    assert action["risk"] == "readonly"
    assert action["needsConfirm"] is False


def test_rerun_action_carries_the_source() -> None:
    proposed = _propose("重新跑一遍", "run_test", make_run())
    assert proposed is not None
    _reply, action = proposed
    assert action is not None
    assert action["kind"] == "run"
    assert action["params"] == {"kind": "arxiv", "value": "2502.12345", "title": "DeepRare"}
    assert action["needsConfirm"] is True


def test_service_action_is_whitelisted_and_confirmed() -> None:
    proposed = _propose("重启后端", "run_test", make_run())
    assert proposed is not None
    _reply, action = proposed
    assert action is not None
    assert action["kind"] == "service"
    assert action["params"] == {"name": "backend", "action": "restart"}
    assert action["risk"] == "local"
    assert action["needsConfirm"] is True
    # 服务白名单只有 5 个：随便点一个名字不许变成「任意命令执行入口」
    assert kind_of("重启一下那个不知道叫啥的东西", make_run()) != "service"


def test_interaction_intent_replies_honestly_without_action() -> None:
    """互动（读评论/起草回复）还没做：如实说没接上，但**不许**编一个不存在的动作出来。"""
    proposed = _propose("帮我回一下评论", "run_test", make_run())
    assert proposed is not None
    reply, action = proposed
    assert action is None
    assert "还没接上" in reply


def test_unrecognized_goes_to_the_model() -> None:
    """认不出来就该落到模型自由问答那条路（返回 None），而不是硬塞一张卡片。"""
    assert _propose("这篇论文的创新点跟别人的区别在哪", "run_test", make_run()) is None
    assert _propose("你好", "run_test", make_run()) is None
