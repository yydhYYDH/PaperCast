"""作品库直投（app/direct_publish.py）的离线单测。

只测纯逻辑与契约，**不连任何真实服务**（preflight / publish 都是替身）：
- 物料真的按渠道分开（小红书拿 xhs 变体、知乎拿 zhihu 变体）—— 这是 2026-09-19 修过的 bug；
- 渠道没就绪 / 素材不适配 / 没有文案 → status=blocked + 人话原因，且**不抛异常**；
- confirmed=False 只落 export/，一个发布接口都不调（不可逆动作的硬约束）；
- confirmed=True 才真调 publish()，且投递前 export/ 已经落盘（服务挂掉也不丢素材）；
- 回执写在 publish/direct/，不覆盖 M3 的 publish/<渠道>/receipt.json。

写法与 tests/test_publish_materials.py 一致：同步用例 + asyncio.run（本仓库没装 pytest-asyncio）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import pytest

from app import direct_publish
from app.channels.base import Channel, Delivery, Materials, Preflight
from app.models import RunConfig, SourceInput, new_run


class FakeChannel(Channel):
    """可编程渠道替身：preflight / publish 的结果都由测试指定，绝不触网。"""

    id = "fake"
    name = "假渠道"
    aliases = ()
    capabilities = frozenset({"text"})
    transport = "none"

    def __init__(self, *, state: str = "ready", account: str = "tester",
                 suitable: bool = True, reason: str = "可以投", publish_status: str = "published",
                 channel_warnings: Optional[list[str]] = None) -> None:
        super().__init__(settings=None)
        self._state = state
        self._account = account
        self._suitable = suitable
        self._reason = reason
        self._publish_status = publish_status
        # 渠道自己报告的降级（配图没上、标签没加……），用来验证它会一路进回执
        self._channel_warnings = list(channel_warnings or [])
        self.published: list[Materials] = []
        self.probed = 0

    def supports(self, m: Materials) -> tuple[bool, str]:
        return self._suitable, self._reason

    def manual_steps(self, m: Materials, out: Path) -> str:
        return "手动发布步骤\n"

    async def preflight(self) -> Preflight:
        self.probed += 1
        return Preflight(state=self._state, account=self._account,  # type: ignore[arg-type]
                         detail=f"替身状态 {self._state}", hint="先登录")

    async def publish(self, m: Materials, *, confirmed: bool = False) -> Delivery:
        if not confirmed:
            return self.blocked_delivery("NOT_CONFIRMED", "没确认不许发")
        self.published.append(m)
        if self._publish_status != "published":
            return Delivery(channel=self.id, status=self._publish_status,  # type: ignore[arg-type]
                            error={"code": "BOOM", "message": "投递失败"})
        return Delivery(channel=self.id, status="published", url="https://example.com/p/1",
                        remote_id="p1", account=self._account,
                        raw={"warnings": list(self._channel_warnings),
                             "upstreamMessage": "文章发布流程完成"} if self._channel_warnings else {})


class FakeStore:
    def __init__(self, run: Any, root: Path) -> None:
        self.run = run
        self.root = root
        self.saves = 0

    def get(self, run_id: str) -> Optional[Any]:
        return self.run if run_id == self.run.id else None

    def dir(self, run_id: str) -> Path:
        return self.root / run_id

    def save(self, run: Any) -> None:
        self.saves += 1


def make_run(tmp_path: Path, *, with_article: bool = True) -> tuple[Any, FakeStore, Path]:
    run = new_run(SourceInput(kind="arxiv", value="2401.00001"), RunConfig(), "测试论文")
    store = FakeStore(run, tmp_path)
    run_dir = store.dir(run.id)
    if with_article:
        article = run_dir / "article"
        article.mkdir(parents=True)
        # 两个渠道各自一份文案：小红书变体是图文帖结构，知乎变体是长文（渠道不能串味）
        (article / "xhs.md").write_text(
            "推荐标题：三分钟读懂这篇论文\n\n## 正文\n这是一段很短的图文笔记正文。\n\n## 标签\n#论文 #科普\n",
            encoding="utf-8",
        )
        (article / "zhihu.md").write_text(
            "# 深度解读这篇论文\n\n" + "这是一段很长的知乎正文。" * 20 + "\n\n## 标签\n#科研 #解读\n",
            encoding="utf-8",
        )
    return run, store, run_dir


def channel_of(payload: dict[str, Any], channel_id: str) -> dict[str, Any]:
    return next(c for c in payload["channels"] if c["channelId"] == channel_id)


# --------------------------------------------------------------------------- #
# list_drafts
# --------------------------------------------------------------------------- #

def test_drafts_carry_real_materials_not_placeholders(tmp_path: Path) -> None:
    """草稿带的是这次运行的**真产物**：标题/正文能填出来，空字段也要是空列表。"""
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel()
    payload = asyncio.run(direct_publish.list_drafts(store, store.run.id, channels=[fake]))

    draft = channel_of(payload, "fake")
    assert draft["hasDraft"] is True
    assert draft["title"].strip() in {"三分钟读懂这篇论文", "深度解读这篇论文"}   # 兜底变体也必须是真文案
    assert draft["body"].strip()
    assert draft["images"] == []          # 没有配图就是空列表，前端 v-for 直接迭代
    assert draft["video"] is None
    assert fake.probed == 1


def test_drafts_report_blocked_reason_without_raising(tmp_path: Path) -> None:
    """渠道没就绪：列表照常返回，把原因写在 reason 里（不 500、不静默）。"""
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel(state="login_required", account="")
    payload = asyncio.run(direct_publish.list_drafts(store, store.run.id, channels=[fake]))

    draft = channel_of(payload, "fake")
    assert draft["ready"] is False
    assert draft["blockedBy"] == "login_required"
    assert "先登录" in draft["reason"]


def test_drafts_without_article_is_409(tmp_path: Path) -> None:
    """没有文章产物：接口层面拦住（409）—— 这时候发什么都没意义。"""
    _, store, _ = make_run(tmp_path, with_article=False)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(direct_publish.list_drafts(store, store.run.id, channels=[FakeChannel()]))
    assert getattr(excinfo.value, "code", "") == "ARTICLE_MISSING"


def test_drafts_unknown_run_is_404(tmp_path: Path) -> None:
    _, store, _ = make_run(tmp_path)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(direct_publish.list_drafts(store, "run_nope", channels=[FakeChannel()]))
    assert getattr(excinfo.value, "status", 0) == 404


# --------------------------------------------------------------------------- #
# publish_work：confirmed 是硬闸门
# --------------------------------------------------------------------------- #

def test_export_only_never_touches_publish(tmp_path: Path) -> None:
    """confirmed=False：只落 export/，一个发布接口都不调。"""
    _, store, run_dir = make_run(tmp_path)
    fake = FakeChannel()
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake", channels=[fake]))

    assert result["status"] == "draft"
    assert fake.published == []
    assert (run_dir / "publish" / "direct" / "fake" / "export" / "title.txt").is_file()


def test_confirmed_publishes_and_writes_receipt(tmp_path: Path) -> None:
    """confirmed=True：先落 export/ 再投递，回执写在自己的目录里。"""
    _, store, run_dir = make_run(tmp_path)
    fake = FakeChannel()
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                                     confirmed=True, channels=[fake]))

    assert result["status"] == "published"
    assert result["url"] == "https://example.com/p/1"
    assert result["receiptUrl"] == f"/artifacts/{store.run.id}/publish/direct/fake/receipt.json"
    # 素材兜底必须已经落盘（服务挂了也能手动发）
    assert (run_dir / "publish" / "direct" / "fake" / "export" / "content.txt").is_file()
    receipt = json.loads((run_dir / "publish" / "direct" / "fake" / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "published"
    assert receipt["via"] == "work-library"
    assert fake.published and fake.published[0].title.strip()


def test_receipt_does_not_clobber_m3_receipt(tmp_path: Path) -> None:
    """作品库直投不许覆盖 M3 写的 publish/<渠道>/receipt.json。"""
    _, store, run_dir = make_run(tmp_path)
    m3 = run_dir / "publish" / "fake"
    m3.mkdir(parents=True)
    (m3 / "receipt.json").write_text('{"via": "m3"}', encoding="utf-8")

    asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                            confirmed=True, channels=[FakeChannel()]))

    assert json.loads((m3 / "receipt.json").read_text(encoding="utf-8"))["via"] == "m3"
    assert (run_dir / "publish" / "direct" / "fake" / "receipt.json").is_file()


def test_unsuitable_material_is_blocked_not_4xx(tmp_path: Path) -> None:
    """素材不适配：返回 blocked + 原因（界面要原样显示），不是一次失败请求。"""
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel(suitable=False, reason="缺视频：B 站是视频投稿")
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                                     confirmed=True, channels=[fake]))

    assert result["status"] == "blocked"
    assert result["error"]["code"] == "MATERIAL_UNSUITABLE"
    assert "缺视频" in result["error"]["message"]
    assert fake.published == []


def test_channel_not_ready_is_blocked(tmp_path: Path) -> None:
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel(state="offline", account="")
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                                     confirmed=True, channels=[fake]))
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "OFFLINE"


def test_confirm_account_mismatch_is_409(tmp_path: Path) -> None:
    """确认的账号与当前登录不一致 → 拒绝（防投错号）。"""
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel(account="real-user")
    with pytest.raises(Exception) as excinfo:
        asyncio.run(direct_publish.publish_work(store, store.run.id, "fake", confirmed=True,
                                                confirm_account="another-user", channels=[fake]))
    assert getattr(excinfo.value, "status", 0) == 409
    assert fake.published == []


def test_unknown_channel_is_404(tmp_path: Path) -> None:
    _, store, _ = make_run(tmp_path)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(direct_publish.publish_work(store, store.run.id, "nope", channels=[FakeChannel()]))
    assert getattr(excinfo.value, "status", 0) == 404


def test_overrides_are_applied(tmp_path: Path) -> None:
    """界面改过的标题/正文/标签要真的生效（改完仍要重新过 supports，见下一个用例）。"""
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel()
    result = asyncio.run(direct_publish.publish_work(
        store, store.run.id, "fake", confirmed=True, channels=[fake],
        overrides={"title": "改过的标题", "content": "改过的正文", "tags": ["#论文", "科普"]},
    ))

    assert result["status"] == "published"
    sent = fake.published[0]
    assert sent.title == "改过的标题"
    assert sent.body == "改过的正文"
    assert sent.tags == ["论文", "科普"]      # 前导 # 要去掉，平台侧只认话题名


def test_overrides_are_rechecked_against_platform_rules(tmp_path: Path) -> None:
    """改过的标题如果不合格，supports 必须重新拦下（不能靠改文案绕过平台规则）。"""
    _, store, _ = make_run(tmp_path)

    class PickyChannel(FakeChannel):
        def supports(self, m: Materials) -> tuple[bool, str]:
            if len(m.title) > 10:
                return False, f"标题 {len(m.title)} 字 > 10 字（替身上限）"
            return True, "可以投"

    fake = PickyChannel()
    result = asyncio.run(direct_publish.publish_work(
        store, store.run.id, "fake", confirmed=True, channels=[fake],
        overrides={"title": "这个标题显然超过十个字了"},
    ))
    assert result["status"] == "blocked"
    assert fake.published == []


def test_failed_delivery_reports_error_not_exception(tmp_path: Path) -> None:
    _, store, _ = make_run(tmp_path)
    fake = FakeChannel(publish_status="failed")
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                                     confirmed=True, channels=[fake]))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "BOOM"
    assert result["receipt"]["status"] == "failed"


# --------------------------------------------------------------------------- #
# 作品库能看见：回执并入发布总表 + 登记成产物
# --------------------------------------------------------------------------- #

def _publish_stage(store: FakeStore, status: str = "done") -> Any:
    stage = next(s for s in store.run.stages if s.id == "publish")
    stage.status = status
    return stage


def test_receipt_is_merged_into_m3_summary(tmp_path: Path) -> None:
    """作品库按 publish/receipts.json 显示「这件发了没有」，直投必须并进去。"""
    _, store, run_dir = make_run(tmp_path)
    publish_dir = run_dir / "publish"
    publish_dir.mkdir(parents=True)
    (publish_dir / "receipts.json").write_text(json.dumps({
        "optionId": "draft", "status": "draft",
        "channels": {"zhihu": {"channel": "zhihu", "status": "draft", "title": "旧的那份"}},
        "published": [], "failed": [], "blocked": [],
    }, ensure_ascii=False), encoding="utf-8")

    asyncio.run(direct_publish.publish_work(store, store.run.id, "fake", confirmed=True, channels=[FakeChannel()]))

    data = json.loads((publish_dir / "receipts.json").read_text(encoding="utf-8"))
    assert data["channels"]["fake"]["status"] == "published"
    assert data["channels"]["zhihu"]["title"] == "旧的那份"     # 别的渠道不许被抹掉
    assert data["published"] == ["fake"]
    assert data["status"] == "published"
    assert data["updatedBy"] == "work-library"


def test_receipt_merge_is_skipped_without_summary(tmp_path: Path) -> None:
    """没跑过发布阶段（没有总表）就不去建一份残缺的：宁可看不见，也不要写错。"""
    _, store, run_dir = make_run(tmp_path)
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                                     confirmed=True, channels=[FakeChannel()]))
    assert result["status"] == "published"
    assert not (run_dir / "publish" / "receipts.json").exists()
    assert not [w for w in result["warnings"] if "总表" in w]


def test_receipt_is_registered_as_artifact(tmp_path: Path) -> None:
    """回执要登记成发布阶段产物，否则作品库货架上还是旧状态。"""
    _, store, run_dir = make_run(tmp_path)
    _publish_stage(store, "done")

    asyncio.run(direct_publish.publish_work(store, store.run.id, "fake", confirmed=True, channels=[FakeChannel()]))

    stage = _publish_stage(store)
    registered = [a for a in stage.artifacts if a.path.endswith("publish/direct/fake/receipt.json")]
    assert len(registered) == 1
    assert registered[0].meta == {"status": "published"}
    assert store.saves == 1


def test_artifact_registration_skipped_while_pipeline_owns_the_stage(tmp_path: Path) -> None:
    """运行正停在闸门上时不许动 run.json —— 会与流水线的保存互相覆盖。"""
    _, store, _ = make_run(tmp_path)
    _publish_stage(store, "waiting")

    asyncio.run(direct_publish.publish_work(store, store.run.id, "fake", confirmed=True, channels=[FakeChannel()]))

    assert _publish_stage(store).artifacts == []
    assert store.saves == 0


def test_channel_degradations_reach_receipt_and_result(tmp_path: Path) -> None:
    """渠道报告的降级（例如「配图没进正文」）必须出现在回执和返回体里。

    2026-09-19 的真实事故：知乎那条 `status=published` 的文章其实无图无标签，
    回执里只有一句 published —— 光看回执的人以为一切正常。降级不许被「成功」吞掉。
    """
    _, store, run_dir = make_run(tmp_path)
    fake = FakeChannel(channel_warnings=["配图没插进正文：p1.png", "标签这一项跳过：没入口"])
    result = asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                                     confirmed=True, channels=[fake]))

    assert result["status"] == "published"
    assert "配图没插进正文：p1.png" in result["warnings"]
    receipt = json.loads(
        (run_dir / "publish" / "direct" / "fake" / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["degradations"] == ["配图没插进正文：p1.png", "标签这一项跳过：没入口"]
    assert receipt["upstreamMessage"] == "文章发布流程完成"


def test_receipt_without_degradations_stays_clean(tmp_path: Path) -> None:
    """没有降级时不许凭空造 `degradations` 字段，否则前端会以为每次都有问题。"""
    _, store, run_dir = make_run(tmp_path)
    asyncio.run(direct_publish.publish_work(store, store.run.id, "fake",
                                            confirmed=True, channels=[FakeChannel()]))
    receipt = json.loads(
        (run_dir / "publish" / "direct" / "fake" / "receipt.json").read_text(encoding="utf-8")
    )
    assert "degradations" not in receipt
    assert "upstreamMessage" not in receipt
