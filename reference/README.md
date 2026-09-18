# reference · 参考区（别人的代码，只读）

| 子目录 | 内容 |
| --- | --- |
| `upstream/` | 23 个上游参考实现。来源、HEAD、借用点见 [`../docs/research/upstream-repos.md`](../docs/research/upstream-repos.md) |
| `baoyu-research/` | 出图后端调研（21 个 `baoyu-*` 技能 + codex-imagegen 方案），R2 素材增强用 |

## 规矩

1. **只读**。不要在这里改代码、加脚本、跑构建；
2. 每个仓库都带自己的 `.git`，根仓库已忽略整个 `upstream/`（不用 submodule）；
3. 需要借用某个实现时：结论写进 `docs/research/`，代码复制成 `apps/` 下的组件；
4. 整个目录可删可重克隆，所以**不要把它当长期资料库**。

体积提醒：`upstream/` 约 2.5G（`Paper2Poster` 单仓 1.2G，`Paper2Any` 345M，`zhihu-mcp` 258M）。`du -sh */ | sort -h` 可查。
