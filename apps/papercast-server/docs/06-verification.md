# 验证记录

本文只写**真实跑过的东西**，命令与输出都可复现。验证环境 = 当前服务器
（20 核 / 1TB 盘 / **GPU 被系统禁用**），验证时间 2026-09-18。

## 0. 样本

用一篇真实的 19 页 CVPR 风格论文，**不是**手写的小 PDF：

```bash
curl -sL -o samples/paper2video.pdf https://arxiv.org/pdf/2510.05096
# -> PDF document, version 1.7, 19 pages / 5,251,910 bytes
```

论文：*Paper2Video: Automatic Video Generation from Scientific Papers*（Show Lab, NUS）。
选它的原因：双栏排版、大量矢量图、附录里有长 prompt 文本，正好压 M1 解析器的边界。

## 1. 端到端结果（最终代码，安全默认）

```bash
./scripts/run_dev.sh                                   # http://127.0.0.1:8000
./scripts/smoke_test.sh samples/paper2video.pdf        # 发布闸门默认 draft，不真发帖
```

run `run_224e72b5a672`，`status = done`，四段阶段全部 `done`，**所有 checks 通过**：

| 阶段 | 结果 | 耗时/规模 |
| --- | --- | --- |
| `intake` | done | 68k 字符 / **12 张图（fig 8 + table 4）** / 23 个章节 / **11.4s** |
| `understand` | done | digest：4 条贡献、11 条证据（全部可回溯）、6 张选定图表；精读笔记 8,770 字 |
| `article` | done | 小红书正文 773 字、12 个标签、标题计重 35（上限 38）、**6 张 1080×1440 卡片** |
| `poster` / `video` | skipped | 契约占位，本后端未实现 |
| `publish` | done（draft） | 素材就绪：6 张图 + title.txt + content.txt；未投递 |

`checks` 明细（前端「引擎与环境」/阶段卡片会原样显示）：

```text
intake      正文抽取   pass  68k 字符 / 23 个标题
intake      图片抽取   pass  12 张（fig 8 / table 4 / 未匹配 0）
intake      元数据     pass  Paper2Video: Automatic Video Generation from Scientific Papers
intake      图片引用   pass  全部图片文件存在
understand  事实源结构 pass  4 条贡献 / 788 字方法说明
understand  数值可回溯 pass  11 条结果全部能在原文中检索到
understand  图表选择   pass  选定 6 张：fig-1, fig-4, fig-5, fig-3, fig-7, fig-2
understand  精读笔记   pass  8770 字
article     标题计重   pass  「Paper2Video：从论文自动生成演示视频」= 35（上限 38）
article     无公式     pass  正文不含 LaTeX/公式表达
article     正文长度   pass  773 字（上限 1000）
article     标签数量   pass  12 个（8-12）
article     卡片渲染   pass  6 张 3:4 卡片
publish     MCP 可用性 pass  http://127.0.0.1:18060 健康
publish     登录态     pass  账号 momo
publish     发布素材   pass  6 张图 / 773 字 / 标题计重 35
publish     发布结果   run   draft（素材在 export/）
```

产出的目录（`<工作区>/var/runs/run_224e72b5a672/`）与 `docs/00-overview.md` 约定完全一致：
`intake/content.md` + `intake/images/{fig-1..8,table-1,2,4,5}.png`、`understand/digest.json` +
`reading_note.md`、`article/xhs.md` + `article/cards/p1..6.png`、`publish/xhs_receipt.json`。

## 2. M1 抽图质量：为什么不用 pymupdf4llm 自带的图

同一篇论文，两种抽图方式的实测对比：

| 方式 | 结果 |
| --- | --- |
| `pymupdf4llm(write_images=True)` | **8 张**，全是内嵌位图；Figure 1/2/3/7 这类**矢量图整张丢失** |
| 本项目的「图注驱动 + 连续内容带」 | **12 张**：fig-1..8 + table-1/2/4/5，覆盖正文所有主图 |

同一批裁图的墨迹覆盖率 0.05–0.23（空白区域为 0.00），确认是真实图形内容而非空白块。
唯一未定位到的是 p8 的 `Table 3`，已按设计记 `warn` 并保留图注文字，不静默丢。

## 3. 前端契约一致性

后端的 `PaperRun` JSON 逐字段对齐 `papercast/src/types.ts`：

```bash
curl -s http://127.0.0.1:8000/api/runs/<id> | python -c "
import json,sys; d=json.load(sys.stdin)
print(sorted(d.keys()))
print(sorted(d['stages'][0].keys()))
print(sorted(d['config'].keys()), sorted(d['config']['publish'].keys()))
print(sorted(d['articles'][0].keys()))
print(sorted(d['digest'].keys()))"
```

对比结果：

| 类型 | 结果 |
| --- | --- |
| `PaperRun` | `id, createdAt, title, source, status, stages, config`（+ 可选 `digest, articles, error`）✅ |
| `Stage` | `id, label, engine, status, progress, logs, artifacts, checks`（+ 可选 `gate, startedAt, endedAt`）✅ |
| `RunConfig` | `article, poster, video, publish` 四段全在，字段名一致 ✅ |
| `Artifact` | `id, stageId, kind, label, path, url, bytes` ✅ |
| `StageGate` | `id, label, detail, options[{id,label,hint}], resolved` ✅ |

前端切到真实后端只需 `VITE_API_BASE=http://127.0.0.1:8000`，组件与 store 不改。

## 4. 闸门与取消

- **闸门确实会停住**：`understand` 与 `publish` 两处都观测到 `run.status=waiting` / `stage.status=waiting`，
  放行前下游产物不存在（符合「理解层确认后才生成文案」的设计）。
- **放行后状态回正**：`POST /stages/:sid/gate {optionId}` 返回 204，run 回到 `running` 并继续。
- **重复放行被拒**：对已放行的闸门再次放行返回 409 `GATE_REJECTED`。
- **取消**：`POST /cancel` 返回 204，run 置 `failed` 且 `error.code=CANCELLED`（见 `docs/04-api-contract.md` 状态机）。

## 5. 踩到并修掉的坑（都有代码注释留痕）

1. **静默死在 `queued`**：`_execute` 里的延迟导入写错了名字（`run_intake` vs `run`），
   asyncio 任务抛异常后没人取，run 永远停在 `queued`、阶段永远 `pending`。
   现在 `_execute` 外层兜底 + 导入失败显式置 `failed`，任何编排异常都会变成可见状态。
2. **假 CJK 字体**：字体探测用裸子串 `"SC"` 匹配，`DejaVuSansCondensed` 里的 `sC` 命中，
   卡片上的中文会全变方块（探测结果 `cjkFontUsable:false` 才暴露）。
   现在按白名单 + `fc-list :lang=zh` + fontTools cmap 三重校验，本机命中 `waic/msyh.ttc`。
3. **卡片写错目录**：`render_cards` 只收一个 `work_dir` 去推图片目录和输出目录，结果卡片落进
   `intake/cards/`，而产物按 `article/` 相对路径登记 → 6 张卡全部「产物缺失」。
   现在 `figures_dir` 与 `out_dir` 显式分开传。
4. **冒烟脚本把帖子真发出去了**：第一版对所有闸门一律回 `continue`，验证运行把测试帖发到了账号
   （回执 `status: published`，账号 momo）。现在发布闸门默认 `draft`，只有 `PUBLISH=1` 才会真投递。
5. **本机服务被代理吃掉**：`http_proxy` 指向 127.0.0.1:7890，直连 MCP 的请求会走代理并返回空。
   后端调 MCP 一律 `httpx.AsyncClient(trust_env=False)`。
6. **uv 缓存只读**：沙箱下 `~/.cache/uv` 不可写，需 `UV_CACHE_DIR=/home/yydh/hack/var/cache/uv`。
7. **长请求被上游断开**：精读笔记一次要 32k tokens，上游 `RemoteProtocolError` 断连。
   现在分两档（12000 → 6000 精简版）重试，并落一条 `check=run` 如实记录；小红书链路只依赖 digest，不受影响。

## 6. 未验证 / 未实现（别当成能用）

- `poster` / `video` 两个阶段只返回 `skipped`，没有任何实现。
- **LaTeX 通道没有用真实论文验证过**：本机无 TeX 引擎，LaTeX 输入只能走源码解析，
  只在合成的小样本上跑过语法级检查。等有真实 LaTeX 论文（或装了 TeX Live）再补验证。
- **扫描件 PDF**：本机无 tesseract，纯扫描件会明确报 `CONTENT_TOO_SHORT` 并提示需要 OCR，未做 OCR。
- 公众号 / B 站通道未实现（M3 只做小红书）。
- 前端 `5178` 仍是 mock 数据；真机联调需要按 `docs/05-deployment.md` 起 `VITE_API_BASE` 后再刷新页面。
