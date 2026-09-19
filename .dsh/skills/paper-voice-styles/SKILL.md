---
name: paper-voice-styles
description: >
  中文科技传播「讲述者人格」风格规范的取样与落地方法。当需要新增/校准一个写作人格
  （新智元式快讯、机器之心式技术解读、第三方独立视角、同行拆解、审稿人视角等），或要把人格
  接到 papercast 的文章生成提示词里时使用。包含可复现的语料取样路径（媒体原站已失效时
  走搜狐号作者接口 + 360 搜索）、量化统计脚本、已验证的两套人格规范与护栏清单。
---

# 论文传播：讲述者人格（voice）风格规范

## 何时用

- 要给 papercast 的文章生成加一个**新人格**（voice）或校准已有的人格；
- 要判断某个媒体/作者「到底是什么风格」，需要证据而不是印象；
- 要把人格接进提示词拼装（`PLATFORMS[platform] + VOICES[voice] + FACT_RULES`）。

## 何时不用

- 平台体裁约束（小红书 1000 字 / 标题计重 38、知乎长文、B站分镜脚本）—— 那是 platform 轴，
  见 `apps/papercast-server/docs/02-module-generate.md`，人格不得覆盖平台硬约束；
- 事实源与反幻觉规则（`app/prompts.py` 的 DIGEST 铁律）—— 优先级最高，人格改动不得触碰。

## 核心原则：风格 = 两条正交轴

```
variant_id = {platform}-{voice}
platform → 体裁与硬约束（长度 / 能否有公式 / 标题计重 / 标签数 / 配图比例 / 校验器）
voice    → 语气、人称、句长节奏、归属强度、证据呈现方式
```

人格**只能**影响语气与结构，不能改校验规则。约束优先级：**事实源 > 平台硬约束 > 人格语气**。

## 工作流（新增一个人格）

1. **取样**：至少 6–8 篇同一人格来源的**论文/技术类**文章正文，落盘本地。
   - 环境事实（2026-09 实测）：`jiqizhixin.com` 已改版为「数据服务」页、不再公开文章；
     微信公众号不可直接抓；百度/必应/DDG 会返回验证页。
   - 可用路径：**搜狐号作者接口**
     `https://v2.sohu.com/author-page-api/author-articles/pc/<userId>?pNo=1&size=20`
     → 拿 id 后抓 `https://www.sohu.com/a/<id>_<userId>`；正文解析用 lxml + gb18030 兜底。
     已知 id：新智元 `473283`、机器之心 `129720`。
   - 备用路径：360 搜索页面里的 `data-mdurl` 属性（含真实 URL，其余搜索引擎多为壳页）。
   - 脚本：`var/tmp/style-research/fetch_sohu.py`、`fetch_corpus.py`（**每次 bash 调用的 /tmp 不共享**，
     中间文件必须写进工作区）。
2. **量化**：跑 `var/tmp/style-research/analyze.py`，得到标题字数/强标点、段落与行长度分布、
   人称与归属词频、数字密度、图表引用、结尾形态、emoji 数的**计数**。
3. **归纳**：每条结论必须带「N 篇里有几篇」的计数，附 ≤25 字短例；只抽象结构特征，
   **不整段引用原文，不抄标志性表达**。
4. **写规则**：产出 10–15 条祈使句（可直接进提示词）+ 3–5 条反面清单。
5. **接进代码**：`app/styles.py` 的 `VOICES[voice]`（人格片段）与 `PLATFORMS[platform]`（硬约束 + 输出模板），
   提示词由 `prompts.article_system(platform, voice)` 自动拼装；新人格记得在 `LEGACY_VARIANTS` 里加旧 id 兼容。
   **必填两个面向用户的两行字**：`short`（口语化风格名，如「震惊流」「专业科普」）与 `hint`（一句话手感），
   它们经 `GET /api/styles` 进前端风格页；缺了风格页上就是一条没名字的条目。
6. **回归**：`cd apps/papercast-server && .venv/bin/python scripts/test_article_variants.py <run_id> <variant,variant>`
   —— 只跑 article 阶段、复用已有事实源、不碰原 run 目录，几十秒出结果；随后再看人工读感。

## 已完成的人格（详见 `apps/papercast-server/docs/09-voice-styles.md`）

| voice | 画像 | 关键量化特征（各 8 篇样本） |
| --- | --- | --- |
| `newsflash` 新智元式快讯 | 标题造势、正文短句推进、结尾行业外推 | 标题均 17.2 字；感叹号 7/8、问号 0/8；「新智元报道」头部 7/8；≤20 字行占 24%，>60 字仅 23%；正文「可能」33 次（标题强、正文留余地） |
| `analyst` 机器之心式解读 | 克制、按论文骨架走、归属明确 | 标题均 20.0 字；会议/机构前缀常见；骨架＝核心结论→问题→现状综述→诊断实验→核心方法→实验结果→结论与展望→作者信息；>60 字行占 43%；「作者」11 次/3 篇；有图表引用与参考链接 |

当前人格全集（`app/styles.py` 的 `VOICES`）：`independent` 第三方独立视角（**默认**，2026-09-19 起取代
已退役的 `author` 作者自述 —— 稿子不该冒充论文作者）、`peer` 同行拆解、`newsflash` 科技快讯、
`analyst` 技术解读、`reviewer` 审稿人视角。

待取样（**不要从上面两套外推**）：`independent`、`peer`、`reviewer`
（外加 `reproducer` 复现者视角、`explainer`/`tutor`/`paperwalk` 讲解型等候选）。

平台轴（`PLATFORMS`）当前为 `xhs` 小红书 / `zhihu` 知乎 / `bilibili` B站 / `en` 英文传播（X、LinkedIn）；
公众号已于 2026-09-19 下线，旧 id 解析不出平台会如实报错，不再静默生成。

## 护栏（写进任何人格都不能省）

1. 事实源里写「未给出具体数值」的，任何人格都不许给数；
2. 图表/表号引用必须来自事实源清单，不得自造编号；
3. 情绪化标题必须配正文的限定语（「可能/仍有待/目前尚不清楚」），不许把作者声称升级为定论；
4. 不写「内部消息/独家」式爆料口吻；
5. UI 上用描述性命名 + 括号锚点（如「科技快讯（新智元式）」），不要拿媒体名当风格标签；
6. 样本镜像会丢失加粗/小标题/配图位置——「没有小标题」这类结论要先在纯文本外核实。

## 产物位置

- 规范文档：`apps/papercast-server/docs/09-voice-styles.md`
- 语料与脚本：`var/tmp/style-research/`（运行态，可删可重建；重跑会重新取样）
