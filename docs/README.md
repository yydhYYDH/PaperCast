# 文档索引

本工作区所有文档的入口。**新增文档必须挂到下面某张表里。**

## 全局（`docs/`）

| 文档 | 内容 | 状态 |
| --- | --- | --- |
| [`TODO.md`](TODO.md) | **项目级任务板**：本轮目标、分组任务、谁负责、变更记录 | 活 |
| [`00-goal-and-architecture.md`](00-goal-and-architecture.md) | 跨子项目总纲：意图、R1 目标、五层架构、ADR、验收标准 | 有效 |
| [`01-implementation-plan.md`](01-implementation-plan.md) | **实现方案**：集成契约冻结、模块实现细节、里程碑与验收、开放问题 | 草案 v1 |
| [`INSTALL.md`](INSTALL.md) | **安装与运行**：系统要求、一键脚本、手工步骤、可选依赖、凭证、排查 | 有效 |
| [`conventions.md`](conventions.md) | **目录 / 路径 / 命名 / 密钥规范**（本工作区的法律） | 有效 |
| [`10-ops-and-theme.md`](10-ops-and-theme.md) | **运营维护 + 前端主题**：`/api/ops/*` 四个端点、各平台能拿到的真实互动数据（含实测结论）、明亮 SaaS 卡片风的实现方式 | 有效 |
| [`migration-2026-09-19.md`](migration-2026-09-19.md) | 2026-09-19 目录分层迁移：旧→新对照、影响、回滚 | 记录 |
| [`research/`](research/) | 调研结论与上游清单 | — |
| [`research/paper-dissemination-agents-landscape.md`](research/paper-dissemination-agents-landscape.md) | 论文传播类 Agent 生态调研（各平台工具链盘点） | 有效 |
| [`research/upstream-repos.md`](research/upstream-repos.md) | `reference/upstream/` 上游仓库登记表（来源/HEAD/借用点/许可证），是 `ops/sync_upstream.sh` 的唯一输入 | 有效 |
| [`evidence/`](evidence/) | 验收证据：小红书测试帖截图等 | — |
| [`patches/`](patches/) | 上游/本地改动补丁留档 | — |

## 组件内

| 文档 | 内容 |
| --- | --- |
| [`apps/papercast/README.md`](../apps/papercast/README.md) | 前端：六阶段 dashboard、mock/http 双适配器、上游能力映射、平台登录入口、运营维护页、明亮 SaaS 主题 |
| [`apps/papercast-server/README.md`](../apps/papercast-server/README.md) | 后端：三模块划分与快速开始 |
| `apps/papercast-server/docs/00-overview.md` | 三模块划分、数据流、目录约定、技术选型 |
| `apps/papercast-server/docs/01-module-intake.md` | M1 论文处理 |
| `apps/papercast-server/docs/02-module-generate.md` | M2 内容生成（digest → 文案 → 卡片图） |
| `apps/papercast-server/docs/03-module-publish.md` | M3 发布与闸门 |
| `apps/papercast-server/docs/04-api-contract.md` | HTTP/SSE 契约（前后端共同遵守） |
| `apps/papercast-server/docs/05-deployment.md` | 部署、systemd、nginx、常见故障 |
| `apps/papercast-server/docs/06-verification.md` | 验证与验收记录 |
| [`reference/README.md`](../reference/README.md) | 参考区（别人的代码）使用规则 |
| [`ops/README.md`](../ops/README.md) | 脚本与本地工具说明 |
| [`var/README.md`](../var/README.md) | 运行态目录说明（可删性、清理方式） |

## 写文档的规矩

1. 路径引用按 `docs/conventions.md` 第 3.4 节：跨组件引用写工作区根相对路径；
2. 结论要落在 `docs/`，不要只留在 `reference/upstream/` 的 README 里（参考区随时可删）；
3. 凭据、token、cookie 一律不入文档。
