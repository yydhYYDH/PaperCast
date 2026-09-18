# 渠道层（L3 发布）：一份物料 → 三个平台

> 面向三个平台：**小红书 / 知乎 / B 站**。代码在 `app/channels/`，M3 编排在 `app/modules/publish.py`。
> 本文是渠道层的唯一规格：新增平台、改渠道行为、判断「为什么没发出去」都看这里。

## 0. 一句话

一份物料只收集一次（`Materials`），三个渠道各自决定「能不能投、怎么投、投不了怎么兜底」，
投递互相隔离，每个渠道都留下可人工复核的素材包与回执。

## 1. 两层分工（别混）

| 层 | 文件 | 回答的问题 | HTTP 出口 | 谁在用 |
| --- | --- | --- | --- | --- |
| **身份层** | `app/platforms.py` | 这个平台的**账号**是谁、登没登录、怎么扫码 | `GET/POST /api/platforms...` | 前端「平台账号」页、发布页扫码按钮 |
| **投递层** | `app/channels/` | 这份**物料**能不能投、怎么投、回执、兜底 | `GET /api/channels` | M3 发布阶段、设置页 |

- 身份层回答「能不能登录」，投递层回答「能不能发」。两层共用同一套渠道 id 与别名：
  `xiaohongshu`（别名 `xhs`）/ `zhihu` / `bilibili`，见 `channels/registry.py` 的 `ALIASES`。
- 前端手动发一条（`POST /api/platforms/{id}/publish`，目前仅知乎）走身份层；
  **流水线里发**走投递层（M3 扇出 + 人工闸门）。两条路都不绕过「不可逆动作要人确认」。
- 待收敛：`platforms.py` 里 `publish()/export_draft()` 的 `if channel_id == ...` 分支，
  最终应改为调用 `app.channels`（该文件当前由知乎轨道在改，未动）。

## 2. 渠道契约（`channels/base.py`）

```python
class Channel:
    id, name, aliases, capabilities, login_kind, transport, why, restart_hint
    def supports(m: Materials) -> (bool, str)        # 平台规则留在自己家里：缺什么、超没超限
    async def preflight() -> Preflight               # 服务在不在、登录有没有、账号是谁、下一步干什么
    async def export(m, out: Path) -> dict           # 兜底素材包（无副作用、不触网）
    async def publish(m, *, confirmed: bool) -> Delivery   # confirmed=False 必须直接拒绝，不发请求
```

- `Materials`：与平台无关的物料（title / body / tags / images / video / cover / source / run_id）。
- `Preflight.state`：`ready` / `login_required` / `offline` / `unconfigured` / `blocked`，
  非 ready 时 **必须** 给出 `hint`（人能照着做的下一步）。
- `Delivery.status`：`published` / `failed` / `blocked` / `skipped` / `draft`，
  失败要带 `error: {code, message}`，`raw` 里保留渠道原始返回片段。

### 三条硬约束（改代码前先读）

1. **不可逆动作要人确认**：`confirmed=False` 时禁止任何网络投递（`check_channels.py` 会断言这一点）。
2. **失败隔离 + 不丢素材**：单渠道挂掉不阻塞其它渠道；每个渠道的素材包在闸门**之前**就落盘。
3. **如实上报**：没装依赖、没登录就报 `unconfigured` / `login_required`，绝不假装可用、不静默重试。

## 3. 三个渠道一览（2026-09-19 实测）

| 渠道 | id / 别名 | 能力 | 登录 | 传输 | 端口 | 启动 | 实测状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 小红书 | `xiaohongshu` / `xhs` | text, images, video | 扫码 | MCP HTTP（Go/rod） | 18060 | `./ops/start_all.sh mcp` | `login_required`（MCP 在线，cookie 失效需重扫） |
| 知乎 | `zhihu` | text, images | 桌面窗口人工 | playwright HTTP | 18070 | `./ops/start_all.sh zhihu` | `ready`（已登录 YYDH） |
| B站 | `bilibili` | text, video, images(封面) | cookies | biliup CLI 子进程 HTTP | 18080 | `./ops/start_all.sh bilibili` | `ready`（biliup 在 `var/toolchains/bili-venv`，凭证 `var/home/.bilibili/`，账号 YYDH54）。**本通道尚未投过**；项目里已有一次 B站 真实投稿成功，但走的是上游脚本直投（BV1DveU6GEPR），见 §9 |

平台特有的规则都写在 adapter 里，例如：小红书标题计重 ≤ 38、图文 1~18 张图、有视频走 `publish_video`；
知乎正文不堆 `#` 标签（改成「本文标签」一行）；B 站必须有成片、标题 ≤ 80 字。

## 4. B 站通道（`apps/bilibili-publisher`）

选型结论（2026-09 核实，来源见本节末）：

| 方案 | 结论 |
| --- | --- |
| **biliup CLI 子进程** | ✅ 采用。PyPI `biliup==1.2.4` 有 manylinux wheel（免编译）；cookies 有效期 1~3 个月，`biliup renew` 续期 |
| biliup-rs | ❌ 仓库已归档，与 biliup 同一内核 |
| B 站开放平台（`arcopen /video/add`） | ❌ 需资质 + 权限审核，本期不可行 |
| 浏览器自动化复刻创作中心上传 | ❌ 风控风险高，仅作最后兜底 |
| 只出 export 素材包 | ✅ 始终保底（任何情况下都产出） |

- cookies 是凭证 → 默认 `var/secrets/bilibili/cookies.json`（`chmod 600`），兼容读旧的 `var/artifacts/bilibili/cookies.json`。
- 登录：`biliup login` 是交互式菜单，二维码画在终端 → 通道服务的 `POST /api/v1/login/start`
  用 pty 跑它并把输出写进 `var/logs/bilibili-login.log`；也可以 `POST /api/v1/login/cookies` 导入现成 cookies。
- 投稿命令（argv 组装，不走 shell 拼接）：
  ```
  biliup -u <cookies> upload <video> --title T --tag "a,b" --desc D --copyright 1 --tid 231 [--cover C]
  ```
  `-u` 是全局选项必须在子命令前；分区默认 `BILIBILI_TID=231`（以投稿页当前口径为准）；
  追加参数用 `BILIBILI_UPLOAD_EXTRA`。**不要**用 `--no-reprint`（biliup 1.x 没这个参数，上游脚本会因此失败）。
- 被 413 拒绝（文件过大）时，加 `--line cnbd --limit 1` 重试**一次**（`BILIBILI_RETRY_ARGS` 可覆盖），
  退出码非 0 时把 biliup 的 stderr 尾部回传；命中鉴权关键词则报 `NOT_LOGGED_IN` 并提示 `renew`。

来源：`reference/upstream/paper-share-skills/paper-bilibili-uploader/`（上游用的是 biliup）、
[PyPI biliup](https://pypi.org/project/biliup/)、[biliup 文档](https://doc.biliup.rs/)、
[biliup-rs（已归档）](https://github.com/biliup/biliup-rs)、[B 站开放平台](https://open.bilibili.com/doc)。

## 5. M3 的执行顺序（`app/modules/publish.py`）

```
1. 收物料          从 article/export + article/cards（缺图回退 intake/images）+ video/*.mp4 + poster 封面
2. 解析目标渠道    run.config.publish.targets（默认三个）→ registry.resolve_targets
                   未知/停用的渠道不静默丢弃，写成 stage.check=fail
3. 落素材包        每个渠道 publish/<渠道>/export/（title/content/tags/图片/视频/封面/指引/publish_request.json）
4. 探测状态        并发 preflight；每渠道写「渠道状态：X」check；非 ready 带 hint
5. 人工闸门        一个闸门，detail 列出「谁将投递 / 谁投不了 / 为什么」+ 兜底说明
                   **防重复投递**：若 `video/upload_result.json`（上游套件投完写的回执）等证据存在，
                   `previous_delivery()` 会把它顶到闸门 detail 与 `历史投递` check 上 —— 重复投稿不可逆，必须先看见
                   continue=只向就绪渠道投递 / draft=只准备 / skip=本轮不发
6. 并发投递        失败隔离；回执写入 publish/<渠道>/receipt.json
7. 汇总            publish/receipts.json（含 published/failed/blocked）；小红书另写兼容别名 xhs_receipt.json
```

回执总表 `status` 的取值：`published`（≥1 个渠道成功，部分失败在 `failed` 里单列）/
`failed` / `blocked`（闸门放行了但没有任何渠道可投）/ `draft` / `skipped`。

**阶段不会被投递失败判死**：素材包一定在，人可以从 dashboard 下载后手动发。

## 6. 新增第四个平台（四步）

1. 给平台一个本机端口（写进 `docs/conventions.md` §3.3），做一个「独立进程 + HTTP」的通道服务
   （形状照抄 `apps/zhihu-publisher` 或 `apps/bilibili-publisher`：`/health`、`/api/v1/login/status`、`/api/v1/export`、`/api/v1/publish`（要 `confirmed=true`））；
2. 在 `app/channels/` 写一个 `Channel` 子类（照抄 `bilibili.py`：`supports` / `preflight` / `publish` / `manual_steps`）；
3. 在 `channels/registry.py` 的 `BUILTIN` 里登记（有别名就写 `aliases`）；
4. 在 `ops/start_all.sh` 加一个 `start_<name>` 分支，并跑 `scripts/check_channels.py`。

前端不需要为每个渠道写一套 UI：读 `GET /api/channels` 的 `capabilities` / `state` / `hint` 即可。

## 7. 自检与验证

```bash
cd apps/papercast-server
.venv/bin/python scripts/check_channels.py                    # 离线：契约/适配规则/素材包/未确认必须拒绝
.venv/bin/python scripts/check_channels.py --live             # 额外真实探测三个通道服务
.venv/bin/python scripts/check_channels.py --run --option draft   # 合成 run 真跑一遍 M3（不依赖 LLM）
curl -s http://127.0.0.1:8000/api/channels                    # 投递视角的渠道状态
```

实测证据（2026-09-19，`./ops/start_all.sh` 起服务后）：

- 离线自检 25 项、`--live --run --option draft` 43 项、故障演练 37 项、重复投递防护 40 项全过；
- 重复投递防护用的是**真数据**：`var/runs/run_a7b9460d3953/video/upload_result.json` 被正确解析为 BV1DveU6GEPR；
- 故障演练：把三个通道指向死端口 + 闸门选 `continue` → 总表 `status=blocked`、`published=[]`、
  每个渠道仍有独立回执与素材包，阶段不判死（这就是「失败隔离 + 不丢素材」的验收方式）。

## 8. 前端接入清单（给前端轨道，接口已就绪）

| 要展示的 | 用哪个接口 | 字段 |
| --- | --- | --- |
| 三个平台「能不能发」 | `GET /api/channels` | `state` / `detail` / `hint`（非 ready 必有 hint，直接当行动指引展示） |
| 单个平台详情 | `GET /api/channels/{id}` | 同上；`id` 支持别名 `xhs` |
| 平台支持什么形态 | 同上 | `capabilities`（`text`/`images`/`video`）—— **按能力渲染表单**，不要按平台名写死分支 |
| 本轮投哪些平台 | `RunConfig.publish.targets`（建 run 时就带上） | 默认三个；别名 `xhs` 也认；未知值会在 `stage.checks` 里报 fail |
| 每个平台的投递进展 | `GET /api/runs/:id` 的 `stage.checks` / `artifacts` | `素材适配：<渠道>`、`渠道状态：<渠道>`、`可投递渠道`、`发布结果`；产物 `publish/<渠道>/receipt.json`、`publish/receipts.json` |
| 闸门怎么展示 | `stage.gate.detail` 是**多行**计划文本 | 用 `white-space: pre-line` 渲染，别当成一句话截断 |

注意：`/api/platforms`（账号页）与 `/api/channels`（投递视角）**不是重复接口**，
前者回答「登录了吗」，后者回答「这份物料能不能投」。两者的 id/别名一致，可以合并展示。

## 9. 还没做（诚实清单）

- **本通道（`apps/bilibili-publisher`）还没投过稿**：它已 `ready`（biliup 在 `var/toolchains/bili-venv`，
  凭证 `var/home/.bilibili/cookies.json`，账号 YYDH54）。项目里 B站 已有一条真实投稿成功
  （[BV1DveU6GEPR](https://www.bilibili.com/video/BV1DveU6GEPR)），但那是**上游 `paper-share-skills` 直接投的**，
  没经过渠道层、也没有 M3 回执 —— 所以「通道投递」这条路径第一次跑仍要人工盯。
  验收方式：`--run --with-video --option continue`（注意那条 run 已有回执，会被防重复逻辑警告）。
- **视频阶段没实现**（`video` 仍 `skipped`），B 站渠道因此常处于「素材不适用 → 只出素材包」。
- 知乎视频通道未接（`capabilities` 里如实不含 video）。
- 微信公众号在 `platforms.py` 里声明为 `unconfigured`，投递层暂未收录（`targets` 写 wechat 会报 unknown）。
- 没有做「发布后回访」：发出去之后的数据（阅读/点赞）不回采，B1 的运营闭环还没闭。
