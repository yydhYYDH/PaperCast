"""pytest 共享配置与替身对象。

原则（见任务边界）：
- **不连真实服务**：这里没有任何 HTTP/LLM/浏览器的真实调用，LLM 一律 AsyncMock；
- FakeCtx 是最小的 StageContext 替身，只对齐被测代码用到的那几个方法/属性；
- 不往仓库里写数据：所有落盘都用 pytest 的 tmp_path。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

# 让测试在被拷出去 / 在仓库根跑（pytest apps/papercast-server/tests）时都能 import app.*
SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.models import RunConfig, SourceInput, new_run  # noqa: E402


class FakeStore:
    """只实现 community/poster 用到的 dir()；不落盘、不做恢复。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def dir(self, run_id: str) -> Path:
        d = self.root / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def stage_dir(self, run_id: str, stage_id: str) -> Path:
        d = self.dir(run_id) / stage_id
        d.mkdir(parents=True, exist_ok=True)
        return d


class FakeCtx:
    """最小 StageContext 替身：log / progress / check / artifact + work / shared / llm / run / store。

    行为对齐 app/pipeline.py 的 StageContext：
    - check() 同 label 覆盖（真实实现是去重后再 append）；
    - artifact() 只在文件真实存在时登记，否则只记一条 warn 日志；
    - progress() 夹到 0..1。
    """

    def __init__(
        self,
        work: Path,
        *,
        run: Any = None,
        llm: Any = None,
        store: Any = None,
    ) -> None:
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.run = run if run is not None else new_run(
            SourceInput(kind="pdf", value="paper.pdf"), RunConfig(), "测试论文"
        )
        self.stage = next((s for s in self.run.stages if s.id == "publish"), self.run.stages[-1])
        self.shared: dict[str, Any] = {}
        self.llm = llm if llm is not None else AsyncMock()
        self.store = store
        # 断言辅助（不参与业务逻辑）
        self.logs: list[tuple[str, str]] = []
        self.checks: list[tuple[str, str, str]] = []
        self.progress_values: list[float] = []
        self.artifacts: list[dict[str, Any]] = []

    # ---- 与真 StageContext 同名同签名 ----

    def log(self, level: str, text: str) -> None:
        self.logs.append((level, text))

    def progress(self, value: float) -> None:
        self.progress_values.append(max(0.0, min(1.0, float(value))))

    def check(self, label: str, state: str, detail: str) -> None:
        self.checks = [c for c in self.checks if c[0] != label]
        self.checks.append((label, state, detail))

    def artifact(
        self,
        kind: str,
        label: str,
        rel: str,
        *,
        preview: bool = True,
        meta: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        f = self.work / rel
        if not f.is_file():
            self.log("warn", f"产物缺失，未登记：{rel}")
            return None
        art = {"kind": kind, "label": label, "rel": rel, "preview": preview, "meta": meta}
        self.artifacts.append(art)
        return art

    # ---- 断言辅助 ----

    @property
    def labels(self) -> list[str]:
        return [c[0] for c in self.checks]

    def state_of(self, label: str) -> Optional[str]:
        for lbl, state, _ in self.checks:
            if lbl == label:
                return state
        return None

    def detail_of(self, label: str) -> str:
        for lbl, _, detail in self.checks:
            if lbl == label:
                return detail
        return ""

    def find(self, needle: str) -> list[tuple[str, str, str]]:
        return [c for c in self.checks if needle in c[0]]


@pytest.fixture
def make_run():
    """造一个真实的 PaperRun（走 models.new_run，不落盘）。"""

    def _make(**config: Any):
        return new_run(
            SourceInput(kind="pdf", value="paper.pdf"),
            RunConfig(**config),
            "测试论文：一个用于单测的标题",
        )

    return _make


@pytest.fixture
def fake_ctx(tmp_path, make_run):
    """FakeCtx 工厂：fake_ctx(work=..., run=..., llm=...)"""

    def _make(*, work: Optional[Path] = None, run: Any = None, llm: Any = None, store: Any = None) -> FakeCtx:
        return FakeCtx(work or (tmp_path / "work"), run=run or make_run(), llm=llm, store=store)

    return _make

@pytest.fixture
def park_at_gate():
    """把 run 摆成「停在人工闸门上」的样子（等价于 StageContext.gate() 落盘的那几行）。

    B1 的复现起点：run.status == "waiting" 且某阶段 status == "waiting" 且 gate 未放行。
    """

    def _park(run, stage_id: str = "understand", options=("continue", "revise")):
        from app.models import GateOption, StageGate, now_ts

        stage = next(s for s in run.stages if s.id == stage_id)
        stage.status = "waiting"
        stage.progress = 1.0
        stage.gate = StageGate(
            id="digest",
            label="确认论文理解层",
            detail="测试用闸门：下游数字全部由这份事实源派生。",
            options=[GateOption(id=o, label=o) for o in options],
            askedAt=now_ts(),
        )
        run.status = "waiting"
        return stage

    return _park


@pytest.fixture
def run_tree(tmp_path, make_run):
    """造一个 tmp 运行目录树，供 poster/community 这类「从磁盘读产物」的模块用：

        <tmp>/runs/<runId>/understand/digest.json
        <tmp>/runs/<runId>/intake/content.md
        ctx.work = <tmp>/runs/<runId>/<stage>

    返回 (ctx, run_dir)；不碰真实 var/runs，也不连任何服务。
    """

    def _make(
        *,
        digest: Optional[dict[str, Any]] = None,
        content: Optional[str] = None,
        run: Any = None,
        llm: Any = None,
        stage: str = "publish",
    ):
        import json as _json

        run = run or make_run()
        root = tmp_path / "runs"
        run_dir = root / run.id
        (run_dir / "understand").mkdir(parents=True)
        if digest is not None:
            (run_dir / "understand" / "digest.json").write_text(
                _json.dumps(digest, ensure_ascii=False), encoding="utf-8"
            )
        (run_dir / "intake").mkdir()
        if content is not None:
            (run_dir / "intake" / "content.md").write_text(content, encoding="utf-8")
        ctx = FakeCtx(run_dir / stage, run=run, llm=llm, store=FakeStore(root))
        return ctx, run_dir

    return _make
