# 渠道层（L3 发布）：一份物料 → 三个真渠道 + X

> 面向**小红书 / 知乎 / B 站**三个真渠道，外加 **X（推特）**这个 material-only 渠道（只出素材包，不投递）。
> 代码在 `app/channels/`，M3 编排在 `app/modules/publish.py`。
> 本文是渠道层的唯一规格：新增平台、改渠道行为、判断「为什么没发出去」都看这里。

## 0. 一句话

一份物料只收集一次（`Materials`），各渠道各自决定「能不能投、怎么投、投不了怎么兜底」，
投递互相隔离，每个渠道都留下可人工复核的素材包与回执。

X 是不同的那一类：它**没有投递通道**（`material_only=True`，2026-09-19 加，见 §3.1），
一样按渠道取自己那份文案（`en` 变体的英文 thread）、一样落素材包与回执，但回执恒为 `draft`，
闸门放行也不会发出任何请求。

## 1. 两层分工（别混）

| 层 | 文件 | 回答的问题 | HTTP 出口 | 谁在用 |
| --- | --- | --- | --- | --- |
| **身份层** | `app/platforms.py` | 这个平台的**账号**是谁、登没登录、怎么扫码 | `GET/POST /api/platforms...` | 前端「平台账号」页、发布页扫码按钮 |
| **投递层** | `app/channels/` | 这份**物料**能不能投、怎么投、回执、兜底 | `GET /api/channels` | M3 发布阶段、设置页 |

- 身份层回答「能不能登录」，投递层回答「能不能发」。两层共用同一套渠道 id 与别名：
  `xiaohongshu`（别名 `xhs`）/ `zhihu` / `bilibili` / `x`（别名 `twitter`、`x-com`、`en`），
  见 `channels/registry.py` 的 `ALIASES`。
- 前端手动发一条（`POST /api/platforms/{id}/publish`，目前仅知乎）走身份层；
  **流水线里发**走投递层（M3 扇出 + 人工闸门）。两条路都不绕过「不可逆动作要人确认」。
- 待收敛：`platforms.py` 里 `publish()/export_draft()` 的 `if channel_id == ...` 分支，
  最终应改为调用 `app.channels`（该文件当前由知乎轨道在改，未动）。

## 2. 渠道契约（`channels/base.py`）

```python
class Channel:
    id, name, aliases, capabilities, login_kind, transport, why, restart_hint
    material_only = False                            # True = 只出素材包，不接投递（X）
    def supports(m: Materials) -> (bool, str)        # 平台规则留在自己家里：缺什么、超没超限
    async def preflight() -> Preflight               # 服务在不在、登录有没有、账号是谁、下一步干什么
    async def export(m, out: Path) -> dict           # 兜底素材包（无副作用、不触网）
    async def publish(m, *, confirmed: bool) -> Delivery   # confirmed=False 必须直接拒绝，不发请求
```

- `Materials`：与平台无关的物料（title / body / tags / images / video / cover / source / run_id）。
- `Preflight.state`：`ready` / `login_required` / `offline` / `unconfigured` / `blocked` / `material_only`，
  非 ready 时 **必须** 给出 `hint`（人能照着做的下一步）。`material_only` 不是「环境不对」，
  而是「设计上就不投」——它不该显示成故障，也不该被期待有登录态。
- `Delivery.status`：`published` / `failed` / `blocked` / `skipped` / `draft`，
  失败要带 `error: {code, message}`，`raw` 里保留渠道原始返回片段。

### 三条硬约束（改代码前先读）

1. **不可逆动作要人确认**：`confirmed=False` 时禁止任何网络投递（`check_channels.py` 会断言这一点）。
2. **失败隔离 + 不丢素材**：单渠道挂掉不阻塞其它渠道；每个渠道的素材包在闸门**之前**就落盘。
3. **如实上报**：没装依赖、没登录就报 `unconfigured` / `login_required`，绝不假装可用、不静默重试。
4. **material-only 不许混进「可投递渠道」**：M3 里凡判定「能不能投」的地方（闸门文案、`可投递渠道`
   检查项、投递列表）都用 `is_material_only(channel)` 把它摘出来单独处理（2026-09-19）。

## 3. 渠道一览（2026-09-19 实测）

| 渠道 | id / 别名 | 能力 | 登录 | 传输 | 端口 | 启动 | 实测状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 小红书 | `xiaohongshu` / `xhs` | text, images, video | 扫码 | MCP HTTP（Go/rod） | 18060 | `./ops/start_all.sh mcp` | `login_required`（MCP 在线，cookie 失效需重扫） |
| 知乎 | `zhihu` | text, images | 桌面窗口人工 | playwright HTTP | 18070 | `./ops/start_all.sh zhihu` | `ready`（已登录 YYDH） |
| B站 | `bilibili` | text, video, images(封面) | cookies | biliup CLI 子进程 HTTP | 18080 | `./ops/start_all.sh bilibili` | `ready`（biliup 在 `var/toolchains/bili-venv`，凭证 `var/home/.bilibili/`，账号 YYDH54）。**本通道尚未投过**；项目里已有一次 B站 真实投稿成功，但走的是上游脚本直投（BV1DveU6GEPR），见 §9 |
| X（推特） | `x` / `twitter`, `x-com`, `en` | text | 不需要 | 本地素材包（无服务） | — | — | `material_only`（设计上就不投，见 §3.1） |

### 3.1 X（推特）：material-only 渠道

**为什么有它**：英文传播（`app/styles.py` 的 `PLATFORMS["en"]`）产出的是 6-10 条英文 thread，
产品上它的落点是 X。但 2026-09-19 的决策是「英文不发」——不接投递 API、不碰账号、不存凭证。
于是它跟三个真渠道**形状相同、语义不同**：

- 一样按渠道取自己那份文案（`CHANNEL_PLATFORMS["x"] = ("en",)`，绝不让它退到中文稿上）；
- 一样在闸门**之前**落 `publish/x/export/`（`README.txt` 里是手动发的三步）；
- 一样写 `publish/x/receipt.json`，但 `status` **恒为 `draft`**；
- `preflight()` 直接返回 `material_only`，**不触网**；`publish()` 无条件返回 `draft`（fail-closed：
  就算被别的路径调到，也一个字节都不会发出去）。

**什么时候会进这一轮目标**：

1. 用户显式勾了 `x`；或
2. 这一轮的 `article/` 里**真有** `en*.md` 变体 —— M3 会自动把 X 加进本轮目标并记一条日志
   （`_with_auto_x`，`app/modules/publish.py`）。刻意**不写回** `run.config.publish.targets`：
   那是用户的勾选，替用户改配置是另一回事。

**界面怎么呈现**（2026-09-19）：

- 作品库：X **自成一块**（`data/library.ts` 的 `PLATFORM_META.x`，稿子记号是 `en`，平台归到 `x`），
  量词是「条 thread」，状态一般停在「存了草稿」；
- 「平台账号」页：状态 chip 是「只出素材包」，没有登录按钮（`login="none"`、`kind="export"`）；
- 发布页：X 不参与「未就绪」判定，单独一句「只出素材包，不真发」；
- 新建运行 / 作品库直投：勾 X 只会落素材包 + draft 回执（`direct_publish.publish_work` 里的
  `is_material_only(channel)` 分支）。

**怎么验**：`scripts/check_channels.py --run`（第 4、8 节断言「放行也只回 draft」「不进可投递渠道」），
以及 `ops/shot/x_platform_check.mjs`（作品库里 X 是独立一块、详情说清不会真发）。

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

### 5.1 作品库直投（`app/direct_publish.py`）—— 与 M3 共用渠道层，但不是同一条路

`POST /api/runs/{id}/publish` 是**作品库里那一件作品**的直投口（前端「发布这一件」走它），与 M3 的闸门是两套：一条运行一次确认、一个渠道一次投递。两者共用 `channels/` 与 `collect_materials_for`，平台规则只有一份。

**2026-09-19 改：没有 `article/` 的运行不再一律 409。** 以前 `_load()` 硬要求 run 目录下有 `article/`，而独立脚本产出的成片（`ops/make_short_video.py` / `make_portrait_video.py` 那套）落在的 run 里不会有 `article/` —— `run.json` 的 video 阶段一直是 `skipped`，成片是上游套件自己写进 `video/` 的。结果这种「只出成片」的运行连界面都打不开（草稿列表直接 409 `ARTICLE_MISSING`）。现在：

- `list_drafts`：草稿照出，只是文案为空、`variant=overrides`，`supports()` 如实报「缺标题、正文」——界面要先能看见这条运行有什么可投的，再由人把文案填上；
- `publish_work`：调用方给了标题**和**正文（`overrides`）就用它们组物料，不再看 `article/`；一个都没给、或只给了一半，仍然 409 `ARTICLE_MISSING`（老保证不松：没文案不发）；
- 闸门不变：`confirmed=false` 只落 `publish/direct/<渠道>/export/`，一个发布接口都不调。

验收：`pytest -q` 298 passed（新增 `test_drafts_without_article_still_preview`、`test_publish_work_without_article_{needs_text,partial_text_is_409,uses_overrides,still_gates_on_confirmed}`）。真 run 实测 `run_a7b9460d3953`（没有 `article/`）：drafts 由 409 变 200，草稿带 `video/PAPER2VIDEO_narrated.mp4` 与 `variant=overrides`；`confirmed=false` 的发布请求返回 `status=draft`，回执里是 overrides 的标题 + 7 个标签 + 244 字正文。

**2026-09-19 改（二）：形态默认值写在渠道层，视频另有单独入口。**

同一条 run 往往**两个产物都有**（卡片组图 + 竖版成片），而小红书里图文笔记和视频笔记是**两种不同的笔记** —— 以前渠道只要看到 `materials.video` 非空就走视频分支，于是「这次想发图文」时那 6 张卡片一张都用不上。现在：

- 形态是**平台口径**，声明在渠道类上：`Channel.default_media`（`xiaohongshu = "images"`、`bilibili = "video"`，未知按 `images` 保守兜底），取值口径与 `video_orientation` 一致：由 `channels/` 层决定，不让调用方猜；
- `publish_work(..., media="")` 留空即用渠道默认；`media="video"` 才发成片。**要发视频但 run 里没有成片**不是 4xx，返回 `blocked` + `MEDIA_UNAVAILABLE`「缺成片」—— 不能在 `_apply_media()` 里只把 `video` 摘成 `None`，那样 `supports()` 会退回图文分支、把卡片当图文笔记发出去还报成功（形态悄悄变了才是最坏的结果）；
- `POST /api/runs/{id}/publish` 因此**默认发图文**（小红书）；发成片走 `POST /api/runs/{id}/publish/video`（同请求体，只是形态 = 视频，B 站投稿也走它）；
- `GET /api/runs/{id}/drafts` 的每渠道草稿加两个字段：`defaultMedia`（主按钮发什么）与 `video`（这个渠道**可用**的成片，**不一定被这次默认形态用到**）—— 界面靠它们决定要不要给「发布视频」这个动作，别从 `images`/`video` 的位置反推。草稿里的 `reason`/`images` 已按默认形态整理过，跟主按钮真会发出去的那一版一致。

验收：`pytest -q` 325 passed（新增 `test_default_media_is_image_note_so_cards_are_used`、`test_explicit_video_media_keeps_the_film`、`test_video_media_without_film_is_blocked_not_silently_image`、`test_unknown_media_value_is_400`、`test_channel_default_media_is_declared_per_channel`、`test_drafts_preview_matches_the_main_action_but_still_shows_the_film`；`/publish` 的 `video` 空串覆盖已由 `media` 取代）。真 run 实测 `run_ec0f0e056f47`：drafts 里小红书 `defaultMedia=images`、`reason=图文笔记（6 张图 / 标题计重 33）`、`video=video-vertical.mp4`，B 站 `defaultMedia=video`、拿到横版 `video.mp4`；`confirmed=false` 打两个端点分别回 `media=images` 与 `media=video`。前端实测（Playwright）：同样这条 run 的面板上出现「发布视频」、闸门那句写「这次发的是图文」；没有成片的 run 不出现该按钮。

**顺带记下还没做的**：`_pick_media()` 的「顶层 `video/*.mp4` 优先、嵌套目录不抓」口径没变；**按渠道选成片已经做了**（`Channel.video_orientation`：小红书取竖版 `video-vertical.mp4`、B 站取横版 `video.mp4`，即上面实测那次）。

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
| 这个平台默认发哪种形态 | 同上 | `defaultMedia`（`images`/`video`）—— 主按钮发的就是它，别在前端猜（小红书图文、B 站成片） |
| 想发另一个形态（成片） | `POST /api/runs/:id/publish/video` | 与 `/publish` 同请求体；形态 = 视频笔记 / B 站投稿。run 里没成片回 `blocked` + `MEDIA_UNAVAILABLE`，不是 4xx |
| 这条 run 有没有成片可发 | `GET /api/runs/:id/drafts` | `video`（该渠道可用的成片，**不一定被默认形态用到**）—— 有它才给「发布视频」 |
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
