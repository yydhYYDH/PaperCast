# M2 · 内容生成（generate）

**目标**：把 M1 的 `content.md` + `images/` 变成两样东西 —— 一份**唯一事实源** `digest.json`，
和一组**可直接发布**的平台文案（小红书图文 + 卡片 / 知乎长文 / B 站脚本 / 公众号长文）。

平台与语气由 `app/styles.py` 的「**平台体裁 × 讲述者人格**」两层决定，见第 8 节与 `docs/09-voice-styles.md`。

前端 `understand` 与 `article` 两个阶段都由本模块承担：先理解（digest），再生成（文案 + 卡片）。

## 1. 唯一事实源 `digest.json`

形状 1:1 对齐前端 `PaperDigest`（`papercast/src/types.ts`）：

```jsonc
{
  "arxivId": "2510.05096",
  "title": "Paper2Video: ...",
  "authors": ["..."],
  "venue": "arXiv preprint",
  "year": 2025,
  "abstractCn": "中文摘要（翻译，不是改写）",
  "keywords": ["论文视频化", "多智能体", "..."],
  "contributions": ["贡献点，逐条来自原文，不做推测"],
  "method": "方法主线的中文说明",
  "results": [{ "label": "指标名", "value": "数值", "note": "证据出处（表/图/节）" }],
  "figures": [{ "id": "fig-1", "caption": "原图注", "source": "images/fig-1.png" }],
  "limitations": ["作者承认的局限 + 可核验的客观限制"],
  "stagesNote": "本次生成的来源与取舍说明"
}
```

**反幻觉约束**（写在 prompt 里，并在生成后做机器校验）：

1. `results[].value` 必须逐字出现在论文正文/表格中，否则该条目被丢弃并记 `warn`；
2. 论文没给数值的结论，`value` 写「未给出具体数值」而不是编一个；
3. `figures[].source` 必须是 M1 实际产出的文件，不存在则丢弃；
4. 生成后跑 `verify_digest()`：数字回溯检查（`digest.results[].value` 的每个数字串在 `content.md` 中可检索），
   结果写进 `stage.checks`，前端能直接看到「证据链」是否闭合。

## 2. 中文精读笔记 `reading_note.md`

参考 `repos/paper2x/paper2note` 的结构，按论文叙事顺序：摘要翻译 → Introduction 翻译 →
方法详解（顺读为主）→ 数据与训练 → 实验设计与主结果 → 消融 → 附录要点 → 可信度/局限 → 复现清单。
公式用 `$...$` KaTeX 格式，图片嵌入对应小节。长文，供人精读/复习，不作为发布物。

## 3. 小红书图文 `xhs.md`（platform = xhs）

严格按 `repos/paper2x/paper2xhs/SKILL.md` 的规范产出（人格 voice 只改语气，不改下面的硬规则）：

```markdown
# 小红书图文帖：{推荐标题}

## 候选标题
1. ... （5-8 个，20 字以内为主）
推荐标题：...

## TL;DR
...

## 正文
（3 段，最多 4 段，1000 字以内）

## 标签
#标签1 #标签2 ...（8-12 个）

## 配图顺序
1. `cards/p1.png`：用途说明
...
```

硬性规则（生成后逐条机器校验）：

| 规则 | 校验方式 | 不通过时 |
| --- | --- | --- |
| 正文**不出现公式** | 正则扫 `$...$`、`\\frac`、`\\begin{` | 重试一次，仍违规则删除该句并记 `warn` |
| 标题 ≤ 38（中文算 2，ASCII 算 1） | 前端同款计重规则 | 用候选标题里最短的替换 |
| 正文 1000 字以内 | 去空白字符计数 | 截断到最后一个完整段落 |
| 标签 8-12 个 | 计数 | 从 digest 的 keywords 补齐 |
| 数字可追溯 | 正文里的每个数字都能在 digest 找到 | 该句改写为定性表述 |

**不写**：标题党、无出处的数字、论文没说的「行业影响」。

## 4. 卡片图 `cards/`

默认从 M1 抽出的 Figure 里挑 3-6 张组成图集（第一张优先 Figure 1 / teaser / overview），
遵循 paper2xhs 的图集顺序：总览 → 方法 → 数据/训练流程 → 主结果 → 消融 → 定性示例。
**不生成额外封面图**，不裁剪拼接（与 skill 规范一致）。

每张卡片 = 论文原图 + 该图的**中文一句话解读**，渲染成 3:4（1080×1440）PNG：

```text
cards/p1.png  = render_card(paper_image, caption_cn, "1/6 · 问题")
```

渲染实现：**PIL 直绘**（`app/cards/render.py`），不依赖浏览器 —— 版式是固定的（顶栏强调条 + 主标题 +
白色图框 + 中文图注 + 页脚来源），PIL 画出来更快、更可复现，也省掉一个浏览器进程。
字体检测是这里唯一的坑：**不能用裸子串匹配文件名**（`DejaVuSansCondensed` 里就含 `sC`，
会把无中文的字体当成 CJK 字体，中文全变方块）。现在按白名单 + `fc-list :lang=zh` + fontTools cmap
三重校验，只认真的含中文字形的字体；本机命中 `~/.local/share/fonts/waic/msyh.ttc`（微软雅黑）。
渲染失败或字体不含中文字形时不阻塞：`cards/` 留空、`checks` 里如实标 `fail` 并说明原因。

## 5. 变体循环：一份事实源 → 多个平台变体

`config.article.variants` 里的每个 `{platform}-{voice}` 都会独立调用一次 LLM，产物写入
`article/<platform>[-<voice>].md`：

| 变体 id 示例 | 输出 | 校验（由 `styles.validate_markdown` / 内联校验执行） |
| --- | --- | --- |
| `xhs-author` | `xhs.md`（JSON 结构 + 卡片） | 计重 ≤38、无公式、≤1000 字、标签 8-12、数字可回溯 |
| `xhs-newsflash` | `xhs-newsflash.md` | 同上（卡片复用主变体那批图） |
| `zhihu-analyst` | `zhihu.md` | 标题 ≤40 字、2000-4000 字、允许公式、标签 3-6、数字可回溯 |
| `bilibili-peer` | `bilibili-peer.md` | 无公式、口播稿 1200-2500 字、标签 3-8 |
| `wechat-author` | `wechat.md` | 1500-2500 字、允许公式 |

规则：

- **单次上限 `styles.MAX_VARIANTS`（4 个）**，超出部分只记 `warn`（每个变体一次 LLM 调用，成本线性增长）；
- 人格为 `author`（默认）时沿用旧文件名（`xhs.md` / `wechat.md`），其余人格加后缀，**不覆盖旧产物**；
- `export/title.txt`、`export/content.txt` **只写主变体**（列表里的第一个），避免多平台互相覆盖；
- 单个变体失败不拖垮其它变体：记 `err` + `check=fail` 继续跑，全部失败才让阶段 `failed`；
- 卡片与人格无关（同一批图），只在第一个 xhs 变体渲染，其余复用。

## 6. LLM 调用

- 统一走 `app/llm.py` 的 OpenAI 兼容客户端：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。
- 默认兜底：从 `~/.dsh/.credentials.yaml` 读 `GO_API_KEY`，base 用 `https://opencode.ai/zen/go/v1`，
  模型 `deepseek-v4.1-flash`（本机实测可用，注意该模型是 reasoning 模型，
  必须给足 `max_tokens`，且要带 `x-opencode-session` 头，客户端已处理）。
- 调用是流式的但按段落聚合：长文生成分 3 次请求（digest / 笔记 / 文案），
  每次失败重试 2 次（指数退避），全部失败则阶段 `failed`，已产出的部分保留。
- 超长论文按章节切块送入（每块 ≤ 60k 字符），最后做一次「合并 + 去重」请求。

## 7. 闸门

`understand` 阶段结束后挂一个闸门（与前端 mock 一致）：

```jsonc
{ "id": "digest", "label": "确认论文理解层",
  "options": [{ "id": "continue", "label": "确认并继续" },
              { "id": "revise", "label": "补充要点后重跑", "hint": "..." }] }
```

- `continue` → 放行到 `article`；
- `revise` → 把手填的批注（`POST .../gate` 的 `note` 字段）追加进 digest prompt 重跑本阶段。

**下游产物在闸门放行前不会生成**：这是「单一理解层」原则的执行点，保证文案与笔记永远基于同一版理解。

## 8. 平台体裁 × 讲述者人格（`app/styles.py`）

风格层是**两条正交轴**，不是一张风格清单：

```
variant_id = "{platform}-{voice}"      例如 zhihu-analyst
platform → 体裁与硬约束（长度 / 公式 / 标题计重 / 标签数 / 输出格式 / 是否出卡片）
voice    → 语气、人称、句长节奏、归属强度、证据呈现方式
```

| 轴 | 取值 | 位置 |
| --- | --- | --- |
| platform | `xhs` 小红书 · `zhihu` 知乎 · `bilibili` B 站 · `en` 英文传播（X / LinkedIn）。公众号已于 2026-09-19 下线 | `styles.PLATFORMS` |
| voice | `independent` 第三方独立视角（**默认**，取代已退役的 `author`） · `peer` 同行拆解 · `newsflash` 科技快讯（新智元式） · `analyst` 技术解读（机器之心式） · `reviewer` 审稿人视角 | `styles.VOICES` |

约定：

1. **约束优先级：事实源 > 平台硬约束 > 人格语气**。人格不得放宽平台规则，也不参与校验。
2. 提示词由 `prompts.article_system(platform, voice)` 拼装：人格片段 + 平台规则 + 输出模板 + `FACT_RULES`。
3. 旧 id（`xhs`、`xhs-academic`、`xhs-media`、`zhihu-academic`、`bilibili-academic` …）在 `styles.parse_variant()` 里做兼容映射，
   历史配置不会失效（`academic` → `independent`，`media` → `newsflash`）；`author` 经 `RETIRED_VOICES` 落到 `independent`，
   公众号相关 id 解析不出平台，会被如实报成「无法识别的变体」。
4. 新增人格的取样与归纳流程见 skill `paper-voice-styles`；`newsflash` / `analyst` 有 8 篇真实语料支撑，
   `independent` / `peer` / `reviewer` 目前是设计稿。
5. 每个 voice 还要给两行面向用户的字：`short`（口语名，如「震惊流」「专业科普」）与 `hint`（一句话手感），
   经 `GET /api/styles` 进前端风格页。

**用户从哪里改风格**：前端「风格」页把 4 平台 × 5 人格 = 20 条组合列全（选项、口语名、硬约束都来自
`GET /api/styles`），勾中的 id 就是这次运行的 `config.article.variants`；不勾则用工作台默认。
在工作台输入框里说的（「做成小红书+知乎，用机器之心的口吻」）由前端 `data/stylePick.ts` 解析成同样的 id ——
**说出口的要真的生效**，不能只当一句 brief 文字飘过去。


调试用脚本（只跑 article 阶段，复用已有 run 的事实源，不碰原 run 目录）：

```bash
cd apps/papercast-server
.venv/bin/python scripts/test_article_variants.py --list
.venv/bin/python scripts/test_article_variants.py run_a7b9460d3953 xhs-analyst,zhihu-newsflash
```
