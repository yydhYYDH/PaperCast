import type { PipelineApi, CreateRunRequest } from './types'
import type {
  Artifact,
  ArtifactKind,
  LogLine,
  PaperRun,
  RunConfig,
  Stage,
  StageId,
  StageStatus,
} from '../types'
import { STAGE_META, STAGE_ORDER } from '../types'

/** 模拟器节拍与演示速度（真实流水线是分钟级，这里压缩成秒级） */
const TICK_MS = 420
const SPEED = 0.45

const DURATION: Record<StageId, number> = {
  intake: 5,
  understand: 12,
  article: 17,
  poster: 15,
  video: 21,
  publish: 8,
}

type Script = { text: string; level?: LogLine['level'] }[]

const LOGS: Record<StageId, Script> = {
  intake: [
    { text: '检测输入类型：arxiv:2510.05096' },
    { text: '下载 arXiv 源码包 arXiv-2510.05096.tar.gz（1.4 MB）' },
    { text: '解包 paper_src/：main.tex + 6 个 .tex + 23 张图' },
    { text: 'MinerU 解析 PDF → content.md（保留公式 / 表格 / 图注）', level: 'ok' },
    { text: '归一化完成：paper 模型 42 节，38 张图注' , level: 'ok' },
  ],
  understand: [
    { text: '构建图表素材池 scripts/paper2note_prepare.py' },
    { text: '精读 abstract / introduction / method / experiments / appendix' },
    { text: '抽取贡献点、方法主线、实验证据链' },
    { text: '对齐图表与正文引用（fig ↔ caption ↔ section）' },
    { text: '生成 digest.json + 中文阅读笔记', level: 'ok' },
    { text: '理解层落盘：下游 4 个产物共用这一份事实源', level: 'ok' },
  ],
  article: [
    { text: '载入风格操作系统：微信×学术 / 微信×媒体 / 小红书×学术 / 小红书×媒体' },
    { text: '微信×学术：贡献-证据链结构，保留公式与数字' },
    { text: '微信×媒体：钩子前置，术语降维，类比引导' },
    { text: '小红书×学术：6 张卡片，每张一个知识点' },
    { text: '小红书×媒体：第二人称叙述，制造代入感' },
    { text: '生成封面图 wechat-cover.svg / xhs-cover.svg', level: 'ok' },
    { text: '4 篇文字稿完成，最长 1.6k 字', level: 'ok' },
  ],
  poster: [
    { text: 'intake QA：会场 NeurIPS · 尺寸 36×48 in · 语言 en' },
    { text: 'auto_outline.py → digest.json + assets[]' },
    { text: '选择视觉素材：3 个原始figure + 2 处文字承载' },
    { text: 'Planner：文图对齐为二叉树布局，保持阅读顺序' },
    { text: 'Painter-Commentor：渲染 poster.html 并回读截图' },
    { text: '几何检查：无溢出 / 无重叠 / 边距达标', level: 'ok' },
    { text: '盲读者内容测验：8/10 题命中核心结论', level: 'ok' },
  ],
  video: [
    { text: 'paper-to-beamer：生成 16:10 SUSTech Beamer 幻灯片（7 页）' },
    { text: 'LaTeX 编译 → slides.pdf → 逐页渲染 PNG（300 dpi）' },
    { text: 'narration.json：7 段中文旁白，共 4 分 12 秒' },
    { text: 'TTS 合成（voice: zh-CN-XiaoxiaoNeural, 1.0x）' },
    { text: '物理页拼接 + 转场 + 光标定位' },
    { text: '封面合成 + 横竖双版本导出', level: 'ok' },
    { text: 'paper2video.mp4 输出：1920×1080 / 4:12', level: 'ok' },
  ],
  publish: [
    { text: '小红书：xiaohongshu-mcp 健康检查 http://localhost:18060 ✓' },
    { text: '小红书：上传 6 张卡片 + 正文，等待人工确认' },
    { text: '公众号：Markdown → 微信 HTML 排版（主题 default）' },
    { text: '公众号：封面图上传 + 草稿箱接口调用' },
    { text: 'B 站：biliup 元数据校验（标题/分区/封面/简介）', level: 'warn' },
    { text: '等待发布闸门放行', level: 'warn' },
  ],
}

const GATES: Partial<Record<StageId, Stage['gate']>> = {
  understand: {
    id: 'digest',
    label: '确认论文理解层',
    detail: '下游文章 / Poster / 视频都基于这份事实源，请确认贡献点与关键数据无误。',
    options: [
      { id: 'continue', label: '确认并继续' },
      { id: 'revise', label: '补充要点后重跑', hint: '回到理解层，追加人工批注再生成' },
    ],
  },
  poster: {
    id: 'poster-spec',
    label: '海报规格确认',
    detail: '会场与尺寸会改变 Planner 的分栏策略与字号阶梯。',
    options: [
      { id: 'continue', label: '36×48 in 竖向（默认）' },
      { id: 'landscape', label: '48×36 in 横向' },
      { id: 'a0', label: 'A0 竖版' },
    ],
  },
  publish: {
    id: 'publish-gate',
    label: '发布前人工闸门',
    detail: '选中的渠道将真实投递：小红书走 xiaohongshu-mcp，公众号进草稿箱，B 站走 biliup。',
    options: [
      { id: 'continue', label: '确认发布' },
      { id: 'draft', label: '仅存草稿' },
      { id: 'skip', label: '本轮不发布' },
    ],
  },
}

const art = (
  stageId: StageId,
  id: string,
  kind: ArtifactKind,
  label: string,
  file: string,
  url?: string,
  meta?: Artifact['meta'],
): Artifact => ({
  id: `${stageId}-${id}`,
  stageId,
  kind,
  label,
  path: `.papercast/runs/<run>/${stageId}/${file}`,
  url,
  meta,
})

const ARTIFACTS: Record<StageId, Artifact[]> = {
  intake: [
    art('intake', 'tex', 'text', 'arXiv 源码包', 'arXiv-2510.05096.tar.gz', undefined, { bytes: 1468006 }),
    art('intake', 'md', 'markdown', '解析正文 content.md', 'parsed/content.md', undefined, { bytes: 128400 }),
    art('intake', 'pdf', 'text', '论文 PDF', 'paper.pdf', undefined, { pages: 17 }),
  ],
  understand: [
    art('understand', 'digest', 'json', 'digest.json（事实源）', 'digest.json', '/samples/digest.json'),
    art('understand', 'note', 'markdown', '中文阅读笔记', 'paper2note_reading_note.md', undefined, { words: 6200 }),
  ],
  article: [
    art('article', 'wechat-academic', 'markdown', '微信 × 学术', 'wechat-academic.md', '/samples/article/wechat-academic.md'),
    art('article', 'wechat-media', 'markdown', '微信 × 媒体', 'wechat-media.md', '/samples/article/wechat-media.md'),
    art('article', 'xhs-academic', 'markdown', '小红书 × 学术', 'xhs-academic.md', '/samples/article/xhs-academic.md'),
    art('article', 'xhs-media', 'markdown', '小红书 × 媒体', 'xhs-media.md', '/samples/article/xhs-media.md'),
    art('article', 'cover', 'image', '公众号封面', 'wechat-cover.svg', '/samples/covers/wechat-cover.svg'),
  ],
  poster: [
    art('poster', 'html', 'html', 'poster.html', 'poster.html', '/samples/poster/poster.html'),
    art('poster', 'outline', 'json', 'outline.json', 'outline.json', undefined),
    art('poster', 'png', 'image', 'poster.png（1080×1440 渲染）', 'poster.png', '/samples/poster/poster.png', { w: 1080, h: 1440 }),
  ],
  video: [
    art('video', 'mp4', 'video', 'paper2video.mp4', 'video/paper2video.mp4', '/samples/video/paper2video.mp4', { durationSec: 350, w: 1920, h: 1080 }),
    art('video', 'narration', 'json', 'narration.json', 'narration.json', '/samples/video/narration.json'),
    art('video', 'pptx', 'pptx', 'slides.pptx（7 页）', 'slides.pptx', undefined, { slides: 7 }),
  ],
  publish: [
    art('publish', 'xhs', 'text', '小红书发布回执', 'xhs_receipt.json', undefined, { status: '待确认' }),
    art('publish', 'wechat', 'html', '公众号草稿 HTML', 'wechat_draft.html', undefined, { target: '草稿箱' }),
  ],
}

const CHECKS: Partial<Record<StageId, Stage['checks']>> = {
  poster: [
    { label: '几何检查', state: 'pass', detail: '无溢出 / 无重叠 / 边距 ≥ 2.5 cm' },
    { label: '盲读者测验', state: 'pass', detail: '8 / 10 归纳出核心贡献' },
    { label: '视觉回读', state: 'run', detail: '对比度与字号阶梯复核中' },
  ],
  video: [
    { label: '时长', state: 'pass', detail: '4:12（目标 ≤ 5:00）' },
    { label: '旁白对齐', state: 'pass', detail: '7/7 页旁白与画面同步' },
  ],
}

function makeStage(id: StageId, status: StageStatus = 'pending'): Stage {
  return {
    id,
    label: STAGE_META[id].label,
    engine: STAGE_META[id].engine,
    status,
    progress: 0,
    logs: [],
    artifacts: [],
    gate: GATES[id] ? { ...GATES[id]!, options: GATES[id]!.options.map((o) => ({ ...o })) } : undefined,
    checks: CHECKS[id] ? CHECKS[id]!.map((c) => ({ ...c })) : undefined,
  }
}

const DEFAULT_CONFIG: RunConfig = {
  article: { variants: ['wechat-academic', 'wechat-media', 'xhs-academic', 'xhs-media'] },
  poster: { size: '36×48 in', venue: 'NeurIPS 2025', theme: 'default', lang: 'en' },
  video: { durationSec: 300, voice: 'zh-CN-XiaoxiaoNeural', aspect: '16:9', narration: '中文' },
  publish: { targets: ['xhs', 'wechat'], autoPublish: false },
}

let seq = 0
const nextId = () => `run-${Date.now().toString(36)}-${(++seq).toString(36)}`

export class MockPipelineApi implements PipelineApi {
  readonly label = '内置模拟器 · mock adapter（未连接后端）'

  private runs: PaperRun[] = []
  private timer: number | undefined

  constructor() {
    this.runs = [this.seedDone(), this.seedOlder()]
  }

  /** 一条完整跑完的示例运行，让面板一打开就有内容 */
  private seedDone(): PaperRun {
    const run: PaperRun = {
      id: nextId(),
      createdAt: Date.now() - 1000 * 60 * 26,
      title: 'Paper2Video: Automatic Video Generation from Scientific Papers',
      source: {
        kind: 'arxiv',
        value: '2510.05096',
        title: 'Paper2Video: Automatic Video Generation from Scientific Papers',
        authors: ['Zeyu Zhu', 'Kevin Qinghong Lin', 'Mike Zheng Shou'],
        venue: 'NeurIPS 2025 · SEA Workshop',
        pages: 17,
      },
      status: 'done',
      config: DEFAULT_CONFIG,
      stages: STAGE_ORDER.map((id) => {
        const s = makeStage(id, 'done')
        s.progress = 100
        s.artifacts = ARTIFACTS[id].map((a) => ({ ...a }))
        s.logs = LOGS[id].map((l, i) => ({ ts: Date.now() - 1800000 + i * 900, level: l.level ?? 'info', text: l.text }))
        if (s.gate) s.gate.resolved = s.gate.options[0]!.id
        if (s.checks) s.checks = s.checks.map((c) => ({ ...c, state: 'pass' as const }))
        return s
      }),
    }
    return run
  }

  /** 早前的一条运行，用于运行历史 */
  private seedOlder(): PaperRun {
    const run: PaperRun = {
      id: nextId(),
      createdAt: Date.now() - 1000 * 60 * 60 * 3,
      title: 'Paper2Poster: Multimodal Poster Automation from Scientific Papers',
      source: { kind: 'pdf', value: 'paper2poster.pdf', pages: 12 },
      status: 'failed',
      config: { ...DEFAULT_CONFIG, publish: { targets: ['wechat'], autoPublish: false } },
      stages: STAGE_ORDER.map((id, i) => {
        if (i > 3) return makeStage(id, 'skipped')
        const s = makeStage(id, 'done')
        s.progress = 100
        s.artifacts = ARTIFACTS[id].slice(0, 2).map((a) => ({ ...a }))
        s.logs = [{ ts: Date.now() - 1000 * 60 * 180, level: 'info', text: '阶段完成' }]
        return s
      }),
    }
    const poster = run.stages.find((s) => s.id === 'poster')!
    poster.status = 'failed'
    poster.progress = 71
    poster.logs = [
      ...poster.logs,
      { ts: Date.now() - 1000 * 60 * 172, level: 'err', text: 'MinerU 解析失败：PDF 第 3 页公式区域乱码' },
    ]
    poster.artifacts = []
    poster.gate = undefined
    return run
  }

  async listRuns() {
    return this.runs.map((r) => structuredClone(r))
  }

  async createRun(req: CreateRunRequest): Promise<PaperRun> {
    const run: PaperRun = {
      id: nextId(),
      createdAt: Date.now(),
      title: req.source.title ?? req.source.value,
      source: req.source,
      status: 'queued',
      config: req.config,
      stages: STAGE_ORDER.map((id) => makeStage(id)),
    }
    this.runs.unshift(run)
    this.runs = this.runs.slice(0, 12)
    this.start()
    return structuredClone(run)
  }

  async getRun(id: string) {
    const r = this.runs.find((x) => x.id === id)
    return r ? structuredClone(r) : undefined
  }

  async cancelRun(id: string) {
    const r = this.runs.find((x) => x.id === id)
    if (!r) return
    r.status = 'failed'
    for (const s of r.stages) {
      if (s.status === 'running') {
        s.status = 'failed'
        s.logs.push({ ts: Date.now(), level: 'err', text: '用户取消' })
      }
    }
  }

  async resolveGate(runId: string, stageId: StageId, optionId: string) {
    const r = this.runs.find((x) => x.id === runId)
    const s = r?.stages.find((x) => x.id === stageId)
    if (!r || !s || !s.gate) return
    s.gate.resolved = optionId
    s.logs.push({ ts: Date.now(), level: 'ok', text: `人工闸门：${s.gate.options.find((o) => o.id === optionId)?.label ?? optionId}` })
    if (optionId === 'revise') {
      s.status = 'running'
      s.progress = 62
      s.endedAt = undefined
    } else {
      this.finish(s)
    }
  }

  dispose() {
    if (this.timer !== undefined) window.clearInterval(this.timer)
    this.timer = undefined
  }

  // ---------- 节拍引擎 ----------
  private start() {
    if (this.timer !== undefined) return
    this.timer = window.setInterval(() => this.tick(), TICK_MS)
  }

  private hasWork() {
    return this.runs.some((r) => r.stages.some((s) => s.status === 'running' || s.status === 'pending'))
  }

  private tick() {
    for (const run of this.runs) {
      if (run.status === 'done' || run.status === 'failed') continue
      const active = run.stages.find((s) => s.status === 'running') ?? this.promote(run)
      if (!active) continue
      if (active.status === 'waiting') {
        run.status = 'waiting'
        continue
      }
      run.status = 'running'
      const perTick = (100 / ((DURATION[active.id] * 1000 * SPEED) / TICK_MS))
      active.progress = Math.min(100, active.progress + perTick)
      const script = LOGS[active.id]
      const wantLogs = Math.floor((active.progress / 100) * script.length)
      while (active.logs.length < wantLogs) {
        const line = script[active.logs.length]
        if (!line) break
        active.logs.push({ ts: Date.now(), level: line.level ?? 'info', text: line.text })
      }
      if (active.progress >= 100) {
        if (active.gate && !active.gate.resolved) {
          active.status = 'waiting'
          active.logs.push({ ts: Date.now(), level: 'warn', text: `等待人工确认：${active.gate.label}` })
          run.status = 'waiting'
        } else {
          this.finish(active)
        }
      }
      if (run.stages.every((s) => s.status === 'done' || s.status === 'skipped')) run.status = 'done'
    }
    if (!this.hasWork()) this.dispose()
  }

  private promote(run: PaperRun): Stage | undefined {
    const next = run.stages.find((s) => s.status === 'pending')
    if (!next) return undefined
    next.status = 'running'
    next.progress = 1
    next.startedAt = Date.now()
    run.status = 'running'
    next.logs.push({ ts: Date.now(), level: 'info', text: `▶ ${next.label} · ${next.engine}` })
    return next
  }

  private finish(s: Stage) {
    s.status = 'done'
    s.progress = 100
    s.endedAt = Date.now()
    s.artifacts = ARTIFACTS[s.id].map((a) => ({ ...a }))
    s.checks = s.checks?.map((c) => ({ ...c, state: 'pass' as const }))
    s.logs.push({ ts: Date.now(), level: 'ok', text: `✓ ${s.label} 完成，产出 ${s.artifacts.length} 个产物` })
    if (s.gate && !s.gate.resolved) s.gate.resolved = s.gate.options[0]!.id
  }
}
