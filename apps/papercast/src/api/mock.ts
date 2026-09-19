import type {
  PipelineApi,
  CreateRunRequest,
  AppConfig,
  ConfigItem,
  ConfigPatchResult,
  EnvStatus,
  LlmTestResult,
  PlatformLogoutResult,
  ChatReply,
  ChatRequest,
  DraftBody,
  DraftResult,
  InteractionReplyResult,
  InteractionsResult,
  SkillDetail,
  SkillInfo,
  UploadResult,
} from './types'
import { EXAMPLE_PAPER, exampleSource } from '../data/example'

/** 模拟器里的技能清单（接上真后端时由 GET /api/skills 决定，这里只是让你离线也看得到这一层） */
const MOCK_SKILLS: SkillInfo[] = [
  {
    name: 'papercast-frontend',
    description: '本仓库自己的前端规范：暖调单色编辑风、对话优先入口、只给结论、不许看板化',
    origin: 'repo',
    dir: '（模拟器）.dsh/skills/papercast-frontend',
    root: '（模拟器）.dsh/skills',
    references: ['design-system.md', 'verification.md'],
    style: true,
  },
  {
    name: 'minimalist-ui',
    description: '简洁高级的编辑风格：暖调单色、排版对比、平面网格、柔和粉彩；禁渐变与重阴影',
    origin: 'user',
    dir: '（模拟器）~/.agents/skills/minimalist-ui',
    root: '（模拟器）~/.agents/skills',
    references: [],
    style: true,
  },
  {
    name: 'frontend-design',
    description: '审美方向与反模板纪律：先定调，再排版，不要生成一眼看上去就是默认模板的界面',
    origin: 'user',
    dir: '（模拟器）~/.agents/skills/frontend-design',
    root: '（模拟器）~/.agents/skills',
    references: [],
    style: true,
  },
  {
    name: 'impeccable',
    description: '审计 + 修复分册：布局、排版、降噪、精简，逐条给问题与改法',
    origin: 'user',
    dir: '（模拟器）~/.agents/skills/impeccable',
    root: '（模拟器）~/.agents/skills',
    references: [],
    style: true,
  },
  {
    name: 'design-spacing-rhythm',
    description: '间距刻度与垂直韵律：一套间距、靠距离表达关系，别用线框把每个东西围起来',
    origin: 'user',
    dir: '（模拟器）~/.agents/skills/design-spacing-rhythm',
    root: '（模拟器）~/.agents/skills',
    references: [],
    style: true,
  },
  {
    name: 'guizang-social-card-skill',
    description: '出图技能：文章 → 小红书 3:4 组图 / 公众号封面对（属于"作品长什么样"，不属于界面风格）',
    origin: 'user',
    dir: '（模拟器）~/.agents/skills/guizang-social-card-skill',
    root: '（模拟器）~/.agents/skills',
    references: [],
    style: true,
  },
]
import type {
  Artifact,
  ArtifactKind,
  LogLine,
  OpsLog,
  OpsMetrics,
  OpsService,
  PaperRun,
  PlatformChannel,
  PlatformDraftBody,
  PlatformLoginStart,
  PlatformPublishRequest,
  PlatformPublishResult,
  PlatformQrcode,
  PlatformState,
  DraftMedia,
  RunConfig,
  RunDraft,
  RunDrafts,
  RunPublishRequest,
  RunPublishResult,
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
    { text: 'PyMuPDF 解析 PDF → content.md（保留公式 / 表格 / 图注）', level: 'ok' },
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
    { text: '载入风格层：平台体裁 × 讲述者人格（styles.py）' },
    { text: '小红书 × 作者自述：≤1000 字、无公式、标题计重 ≤38' },
    { text: '知乎 × 技术解读：2000-4000 字、允许公式、结论前置' },
    { text: '小红书：6 张卡片，每张一个知识点' },
    { text: '生成封面图 wechat-cover.svg / xhs-cover.svg', level: 'ok' },
    { text: '2 个变体完成，最长 3.1k 字', level: 'ok' },
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
    { text: '知乎：Markdown → 知乎正文骨架（结论前置）' },
    { text: 'B 站：分镜表 + 口播稿 → 投稿元数据' },
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
    detail: '选中的渠道将真实投递：小红书走 xiaohongshu-mcp、知乎走 zhihu-publisher、B 站走 biliup。',
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
    art('article', 'xhs-author', 'markdown', '小红书 × 作者自述', 'xhs.md', '/samples/article/xhs-academic.md'),
    art('article', 'xhs-newsflash', 'markdown', '小红书 × 科技快讯', 'xhs-newsflash.md', '/samples/article/xhs-media.md'),
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
    engine: '',
    status,
    progress: 0,
    logs: [],
    artifacts: [],
    gate: GATES[id] ? { ...GATES[id]!, options: GATES[id]!.options.map((o) => ({ ...o })) } : undefined,
    checks: CHECKS[id] ? CHECKS[id]!.map((c) => ({ ...c })) : undefined,
  }
}

/** 模拟器里「发出去」的成品地址：只用于演示回执长什么样，不是真实稿件。 */
const DEMO_PUBLISH_URL: Record<string, string> = {
  xhs: 'https://www.xiaohongshu.com/explore/demo-note',
  zhihu: 'https://zhuanlan.zhihu.com/p/2084432742410993947',
  bilibili: 'https://www.bilibili.com/video/BV1demoDemo',
}

/** 演示用二维码：故意画成一眼可辨的占位图，避免被误当成真实登录码。 */
const DEMO_QR = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 240 240">
  <rect width="240" height="240" fill="#f7f7f7"/>
  <g fill="#111">
    <rect x="16" y="16" width="56" height="56"/><rect x="24" y="24" width="40" height="40" fill="#f7f7f7"/>
    <rect x="32" y="32" width="24" height="24"/>
    <rect x="168" y="16" width="56" height="56"/><rect x="176" y="24" width="40" height="40" fill="#f7f7f7"/>
    <rect x="184" y="32" width="24" height="24"/>
    <rect x="16" y="168" width="56" height="56"/><rect x="24" y="176" width="40" height="40" fill="#f7f7f7"/>
    <rect x="32" y="184" width="24" height="24"/>
    <rect x="96" y="24" width="12" height="12"/><rect x="120" y="24" width="12" height="12"/>
    <rect x="108" y="40" width="12" height="12"/><rect x="132" y="48" width="12" height="12"/>
    <rect x="96" y="64" width="12" height="12"/><rect x="120" y="72" width="12" height="12"/>
    <rect x="24" y="96" width="12" height="12"/><rect x="48" y="108" width="12" height="12"/>
    <rect x="72" y="96" width="12" height="12"/><rect x="96" y="108" width="12" height="12"/>
    <rect x="120" y="96" width="12" height="12"/><rect x="144" y="108" width="12" height="12"/>
    <rect x="168" y="96" width="12" height="12"/><rect x="192" y="108" width="12" height="12"/>
    <rect x="108" y="120" width="12" height="12"/><rect x="132" y="132" width="12" height="12"/>
    <rect x="96" y="144" width="12" height="12"/><rect x="120" y="156" width="12" height="12"/>
    <rect x="144" y="144" width="12" height="12"/><rect x="168" y="156" width="12" height="12"/>
    <rect x="96" y="192" width="12" height="12"/><rect x="120" y="204" width="12" height="12"/>
    <rect x="144" y="192" width="12" height="12"/><rect x="168" y="204" width="12" height="12"/>
    <rect x="192" y="192" width="12" height="12"/>
  </g>
  <text x="120" y="124" font-size="15" font-family="sans-serif" text-anchor="middle" fill="#c00">演示二维码</text>
</svg>`,
)

/** 模拟适配器下的渠道状态：只有小红书是「能用」的，其余如实标注未接通。 */
const DEMO_CHANNELS: PlatformChannel[] = [
  {
    id: 'xhs',
    name: '小红书',
    kind: 'mcp',
    login: 'qrcode',
    state: 'ready',
    account: 'momo',
    detail: '已登录：momo（模拟）',
    endpoint: 'http://127.0.0.1:18060',
    needs: ['扫码登录', '6 张卡片图', '标题 ≤ 20 字'],
    capabilities: ['图文发布', '话题标签'],
    loginHint: '接上真后端（VITE_API_BASE）后这里会展示 MCP 真实二维码',
  },
  {
    id: 'zhihu',
    name: '知乎',
    kind: 'playwright',
    login: 'browser',
    state: 'login_required',
    account: '',
    detail: '未登录（模拟）——点「打开浏览器登录」走桌面窗口人工登录',
    endpoint: 'http://127.0.0.1:18070',
    needs: ['桌面窗口人工登录（风控拦纯 HTTP 扫码）', '标题 + 纯文本正文'],
    capabilities: ['文章发布', '话题标签'],
    loginHint: '点「打开浏览器登录」→ 桌面窗口里扫码/账号登录；正式接口见 apps/zhihu-publisher',
  },
  {
    id: 'bilibili',
    name: 'B 站',
    kind: 'cli',
    login: 'cli',
    state: 'offline',
    account: '',
    detail: 'biliup 未安装，视频投稿通道未启用',
    endpoint: 'biliup CLI',
    needs: ['横版 16:9 视频', '竖版封面'],
    capabilities: ['视频投稿'],
    loginHint: '安装 biliup 后执行 biliup login',
  },
  {
    id: 'x',
    name: 'X（推特）',
    kind: 'export',
    login: 'none',
    state: 'material_only',
    account: '',
    detail: '只把英文 thread 落成本地素材包，不会真的发到 X（模拟）',
    endpoint: '本地素材包（无通道服务）',
    needs: ['英文传播：6-10 条英文 thread'],
    capabilities: ['英文 thread 素材包'],
    loginHint: '不用登录：导出后打开 X 网页端手动发',
  },
]

const DEFAULT_CONFIG: RunConfig = {
  article: { variants: ['xhs-author', 'zhihu-analyst', 'en-analyst'] },
  poster: { size: '36×48 in', venue: 'NeurIPS 2025', theme: 'default', lang: 'en' },
  video: { durationSec: 300, voice: 'zh-CN-XiaoxiaoNeural', aspect: '16:9', narration: '中文' },
  publish: { targets: ['xhs', 'zhihu', 'x'], autoPublish: false },
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
      title: EXAMPLE_PAPER.title,
      source: exampleSource(),
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
      config: { ...DEFAULT_CONFIG, publish: { targets: ['zhihu'], autoPublish: false } },
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
      { ts: Date.now() - 1000 * 60 * 172, level: 'err', text: 'PyMuPDF 解析失败：PDF 第 3 页公式区域乱码' },
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

  // ---------- 平台渠道与登录（模拟） ----------

  private xhsState: PlatformState = 'ready'
  private xhsAccount = 'momo'
  private xhsLoggedInAt = 0
  private zhihuState: PlatformState = 'login_required'
  private zhihuAccount = ''
  private zhihuLoggedInAt = 0

  async listPlatforms(): Promise<PlatformChannel[]> {
    // 演示扫码：取出二维码 6 秒后视为「扫上了」，让弹层的轮询真的有状态变化
    if (this.xhsState !== 'ready' && this.xhsLoggedInAt && Date.now() >= this.xhsLoggedInAt) {
      this.xhsState = 'ready'
      this.xhsAccount = 'momo'
    }
    // 演示「桌面窗口登录」：调过 start 之后 4 秒视为登录完成
    if (this.zhihuState !== 'ready' && this.zhihuLoggedInAt && Date.now() >= this.zhihuLoggedInAt) {
      this.zhihuState = 'ready'
      this.zhihuAccount = 'demo-zhihu'
    }
    return DEMO_CHANNELS.map((c) =>
      c.id === 'zhihu'
        ? {
            ...c,
            state: this.zhihuState,
            account: this.zhihuState === 'ready' ? this.zhihuAccount : '',
            detail:
              this.zhihuState === 'ready'
                ? `已登录：${this.zhihuAccount}（模拟）`
                : c.detail,
          }
        : c.id === 'xhs'
        ? {
            ...c,
            state: this.xhsState,
            account: this.xhsState === 'ready' ? this.xhsAccount : '',
            detail:
              this.xhsState === 'ready'
                ? `已登录：${this.xhsAccount}（模拟）`
                : this.xhsState === 'login_required'
                  ? '未登录（模拟）——点「扫码登录」看登录入口'
                  : c.detail,
          }
        : { ...c },
    )
  }

  async platformLoginQrcode(channelId: string): Promise<PlatformQrcode> {
    if (this.xhsState === 'ready') {
      return { channelId, isLoggedIn: true, img: '', timeout: '0s', expiresAt: Date.now(), account: this.xhsAccount }
    }
    this.xhsLoggedInAt = Date.now() + 6000
    return {
      channelId,
      isLoggedIn: false,
      img: DEMO_QR,
      timeout: '4m0s',
      expiresAt: Date.now() + 240_000,
      account: '',
    }
  }

  async platformLoginStart(channelId: string): Promise<PlatformLoginStart> {
    if (channelId === 'zhihu') {
      this.zhihuLoggedInAt = Date.now() + 4000
      this.zhihuState = 'login_required'
      return { channelId, method: 'browser', started: true, hint: '桌面上会弹出浏览器窗口，请在窗口里完成登录（模拟）' }
    }
    return { channelId, method: 'browser', started: false, hint: '模拟环境只演示知乎的桌面窗口登录' }
  }

  async platformExportDraft(channelId: string, body: PlatformDraftBody) {
    return { dir: `var/artifacts/${channelId}/export/${body.runId ?? 'demo-run'}`, files: ['zhihu_article.md', 'zhihu_publish_request.json'] }
  }

  async platformPublish(channelId: string, body: PlatformPublishRequest): Promise<PlatformPublishResult> {
    if (!body.confirmed) throw new Error('发布不可逆：需要 confirmed=true（人工闸门）')
    await new Promise((r) => window.setTimeout(r, 900))
    return {
      url: 'https://zhuanlan.zhihu.com/p/2084432742410993947',
      title: body.title,
      publishedAt: new Date().toISOString(),
      account: this.zhihuAccount || 'demo-zhihu',
      transport: 'playwright',
    }
  }

  async platformLogout(channelId: string): Promise<PlatformLogoutResult> {
    if (channelId === 'zhihu') {
      this.zhihuState = 'login_required'
      this.zhihuAccount = ''
      this.zhihuLoggedInAt = 0
      return { channelId, message: '模拟器：已把知乎标记为未登录（真实后端会删掉本机 cookies 并回报当前状态）', state: 'login_required' }
    }
    // 模拟器里 B 站的登录态是静态演示值，这里只回执一句话（真实后端会删凭证并重启通道服务）
    if (channelId === 'bilibili') {
      return { channelId, message: '模拟器：B 站登录态未真正清除（真实后端会删掉本机 cookies）', state: 'ready' }
    }
    this.xhsState = 'login_required'
    this.xhsAccount = ''
    this.xhsLoggedInAt = 0
    return { channelId, message: '模拟器：已把小红书标记为未登录', state: 'login_required' }
  }

  /* ---------- 作品库直投（离线演示：形状与真后端一致，值都是示例） ---------- */

  /**
   * 演示用的逐渠道草稿：按渠道取该渠道该投的那份文案（与后端 CHANNEL_PLATFORMS 同口径），
   * 素材直接来自本模拟器的产物，**状态如实标成演示值**，别让人以为真探测过。
   */
  async listRunDrafts(runId: string): Promise<RunDrafts> {
    const run = this.runs.find((r) => r.id === runId) ?? this.runs[0]
    const arts = run.stages.flatMap((s) => s.artifacts)
    const article = arts.find((a) => a.stageId === 'article' && a.kind === 'markdown')
    const poster = arts.find((a) => a.stageId === 'poster' && a.kind === 'image')
    const video = arts.find((a) => a.stageId === 'video' && a.kind === 'video')
    const image = poster?.url ? [{ path: poster.path, name: 'p1.png', url: poster.url }] : []
    const title = run.title.slice(0, 18)
    const body = '（演示正文）这一份是模拟器按渠道拣好的文案，接上真后端后这里读的是真实产物。'

    const drafts: RunDraft[] = DEMO_CHANNELS.map((ch) => {
      const base = {
        channelId: ch.id, name: ch.name, capabilities: ch.capabilities, transport: ch.kind,
        state: ch.state, account: ch.account, detail: ch.detail, hint: '', ready: false,
        hasDraft: true, suitable: true, reason: '', title, body,
        tags: ['论文', '科普'], images: image, video: null as DraftMedia | null,
        cover: image[0] ?? null as DraftMedia | null,
        variant: ch.id === 'zhihu' ? 'xhs' : ch.id,
        variantPlatform: ch.id === 'zhihu' ? 'xhs' : ch.id,
        source: 'https://arxiv.org/abs/2510.05096',
      }
      if (ch.id === 'bilibili') {
        return { ...base, video: video?.url ? { path: video.path, name: 'paper2video.mp4', url: video.url } : null,
          variant: 'xhs', suitable: Boolean(video), reason: video ? '视频投稿（演示值）' : '缺视频：B 站是视频投稿' } as RunDraft
      }
      return base as RunDraft
    })

    return {
      runId: run.id,
      previous: null,
      warnings: ['这里是内置演示数据，不是真实探测结果：接上后端（VITE_API_BASE）后才会读真产物与真登录态'],
      channels: drafts,
    }
  }

  async publishRunWork(runId: string, body: RunPublishRequest): Promise<RunPublishResult> {
    const draft = await this.listRunDrafts(runId)
    // 渠道别名（xiaohongshu ↔ xhs）在前端唯一的事实源是 stores/platforms 的 normalizeChannelId；
    // api 层不许反向 import store（会形成 store → api → store 的循环），这里只做同一张表的最小子集。
    const key = (body.channelId ?? '').trim().toLowerCase()
    const cid = key === 'xiaohongshu' || key === 'redbook' ? 'xhs' : key === 'bili' ? 'bilibili' : key
    const target = draft.channels.find((c) => c.channelId === cid)
    if (!target) throw new Error(`未知渠道：${body.channelId}`)
    const title = body.title?.trim() || target.title || ''
    const base = {
      channelId: target.channelId,
      channelName: target.name,
      files: ['title.txt', 'content.txt', 'tags.txt', 'publish_request.json'],
      exportDir: `var/runs/${runId}/publish/direct/${target.channelId}/export`,
      warnings: draft.warnings,
    }
    if (!target.ready) {
      return { ...base, status: 'blocked', error: { code: target.state.toUpperCase(), message: `演示：${target.name} ${target.detail}` } }
    }
    if (!body.confirmed) {
      await new Promise((r) => window.setTimeout(r, 400))
      return { ...base, status: 'draft',
        receipt: { channel: target.channelId, status: 'draft', title, via: 'work-library' },
        receiptUrl: `/artifacts/${runId}/publish/direct/${target.channelId}/receipt.json` }
    }
    await new Promise((r) => window.setTimeout(r, 1200))
    const receipt = { channel: target.channelId, channelName: target.name, status: 'published', title,
      url: DEMO_PUBLISH_URL[target.channelId] ?? '', via: 'work-library', at: Math.floor(Date.now() / 1000) }
    return { ...base, status: 'published', url: String(receipt.url), account: target.account,
      receipt, receiptUrl: `/artifacts/${runId}/publish/direct/${target.channelId}/receipt.json` }
  }

  /**
   * 模拟器不连后端，给一份与后端 SPEC 同形状的假配置：字段名、分组、kind 都对齐，
   * 这样「设置 → 模型与 API」在 mock 模式下也能完整渲染（值仅供示意，写入会抛错）。
   */
  /** 演示模式没有本机后端，如实汇报「什么都没接通」，界面据此显示演示状态 */
  async env(): Promise<EnvStatus> {
    return {
      intake: { engine: 'local', ocr: false },
      llm: { configured: false, model: '' },
      cards: { enabled: true, cjkFontUsable: true },
      publish: { xiaohongshu: { reachable: false, loggedIn: false, account: '' } },
    }
  }

  async getConfig(): Promise<AppConfig> {
    const mk = (key: string, group: string, label: string, kind: ConfigItem['kind'], value: string, desc: string): ConfigItem => ({
      key, group, label, kind, value, desc, editable: true, restart: false, source: 'mock',
    })
    return {
      envFile: '（模拟器：未连接后端）',
      envFileExists: false,
      items: [
        mk('LLM_BASE_URL', '模型与 API', 'API 地址', 'str', 'https://example.invalid/v1', 'OpenAI 兼容的 base_url'),
        mk('LLM_MODEL', '模型与 API', '模型名', 'str', 'mock-model', '请求体里的 model 字段'),
        mk('LLM_API_KEY', '模型与 API', 'API 密钥', 'secret', 'sk-****mock', '留空 = 不修改'),
        mk('LLM_TIMEOUT_SEC', '模型与 API', '单次调用超时（秒）', 'int', '600', '治卡死的关键旋钮'),
        mk('LLM_MAX_TOKENS', '模型与 API', '默认输出上限（token）', 'int', '16000', '未指定时生效'),
        mk('LLM_MAX_TOKENS_CAP', '模型与 API', '硬上限（0 = 不限）', 'int', '0', '对所有调用生效'),
        mk('XHS_MCP_BASE', '投递渠道', '小红书 MCP 地址', 'str', 'http://127.0.0.1:18060', '渠道服务地址'),
        mk('PAPERCAST_CHANNELS', '投递渠道', '启用的渠道', 'list', 'xiaohongshu,zhihu,bilibili', '逗号分隔'),
      ],
    }
  }

  async patchConfig(): Promise<ConfigPatchResult> {
    throw new Error('模拟器不支持写入配置：请用 VITE_API_BASE 连接真实后端')
  }

  /* ---------- 技能 / 个性化层（模拟器） ---------- */

  /**
   * 模拟器里没有技能目录可读，所以这里给的是**已知的六个风格技能的名字与用途**，
   * 并在 dir 里写明「接上真后端才读得到真实技能目录」—— 不假装读到了本机文件。
   */
  async skills(): Promise<SkillInfo[]> {
    await new Promise((r) => setTimeout(r, 120))
    return MOCK_SKILLS
  }

  async skill(name: string): Promise<SkillDetail> {
    const found = MOCK_SKILLS.find((s) => s.name === name)
    if (!found) throw new Error(`模拟器里没有技能「${name}」`)
    return {
      ...found,
      body: `（模拟器）这里只会显示提示：接上真后端（VITE_API_BASE=http://127.0.0.1:8000）后，` +
        `这里显示的是 ${found.name} 的 SKILL.md 原文 —— 本机路径 ${found.dir}/SKILL.md。`,
      truncated: false,
    }
  }

  /* ---------- 对话与上传（模拟器） ---------- */

  async chat(body: ChatRequest): Promise<ChatReply> {
    await new Promise((r) => setTimeout(r, 300))
    const t = body.message
    const ctx = { runId: body.runId ?? null, hasDigest: false, artifacts: 0 }
    // 意图规则与真后端对齐（app/chat_api.py）：认得出就给动作卡，认不出才给占位回答。
    // 模拟器只覆盖「重跑 / 取数据 / 起停服务」三个能自圆其说的意图，闸门那类要真状态，这里不假装。
    if (/重跑|重新跑|再跑|重来|再来一遍/.test(t)) {
      const src = this.runs.find((r) => r.id === body.runId)?.source ?? exampleSource()
      return {
        reply: `把《${src.title}》原样再跑一遍。前一次有产物的话我不动它，新的一遍会另开一条记录。`,
        model: 'mock',
        context: ctx,
        action: {
          kind: 'run',
          title: `重跑《${src.title}》吗？`,
          detail: '六段会从头再走一遍（十几分钟），中间仍然会在该你确认的地方停下来。',
          params: { kind: src.kind, value: src.value, title: src.title },
          needsConfirm: true,
          confirmLabel: '重跑一遍',
          risk: 'local',
        },
      }
    }
    if (/数据|效果|多少|几个|播放|点赞|收藏|浏览/.test(t)) {
      return {
        reply: '我去各平台取一遍真实数字；取不到的我照实说，不会拿 0 顶替。',
        model: 'mock',
        context: ctx,
        action: {
          kind: 'metrics',
          title: '取一次运营数据',
          detail: '只读各平台，不改任何东西。',
          params: { force: true },
          needsConfirm: false,
          confirmLabel: '取一次',
          risk: 'readonly',
        },
      }
    }
    if (/重启|停掉|启动|拉起/.test(t)) {
      const name = /前端|网页/.test(t) ? 'frontend' : /小红书|mcp/i.test(t) ? 'mcp' : /知乎/.test(t) ? 'zhihu' : /b站|B 站|哔哩/.test(t) ? 'bilibili' : 'backend'
      const action = /重启|重新启动/.test(t) ? 'restart' : /停|关/.test(t) ? 'stop' : 'start'
      const verb = { restart: '重启', stop: '停掉', start: '启动' }[action as 'restart' | 'stop' | 'start']
      return {
        reply: `${verb}会走 ops/ 里的启停脚本真做一次。`,
        model: 'mock',
        context: ctx,
        action: {
          kind: 'service',
          title: `要${verb}吗？`,
          detail: `服务名 ${name}，动作 ${action}。`,
          params: { name, action },
          needsConfirm: true,
          confirmLabel: verb,
          risk: 'local',
        },
      }
    }
    if (/评论|回复|互动|通知/.test(t)) {
      const wantsDraft = /起草|帮我回|回复一下|回一下|怎么回/.test(t)
      return {
        reply: wantsDraft
          ? '（模拟器）我会照读到的评论起草一句；草稿只落盘、不会发出去 —— 发送要你逐条确认（P2）。'
          : '（模拟器）我去读一遍「评论和@」，只读、不回复。',
        model: 'mock',
        context: ctx,
        action: {
          kind: wantsDraft ? 'draft' : 'interactions',
          title: wantsDraft ? '读评论并起草一条回复' : '读一遍评论和@（只读）',
          detail: '只读平台 + 在本机起草；一个字都不会发出去。',
          params: wantsDraft ? {} : { limit: 10 },
          needsConfirm: false,
          confirmLabel: wantsDraft ? '起草' : '读一遍',
          risk: 'readonly',
        },
      }
    }
    return {
      reply:
        '（模拟器）这是占位回答。真实回答由本机后端调用你配置的模型产生，而且只依据这次运行已经落盘的事实源（run.json 与 understand/digest.json）。接上真后端后，同一个问题会得到真正的模型回答。',
      model: 'mock',
      context: ctx,
      action: null,
    }
  }

  /* ---------- 互动（模拟器：形状与后端一致；**没有连平台，也没有真起草**） ---------- */

  async interactions(): Promise<InteractionsResult> {
    await new Promise((r) => setTimeout(r, 200))
    return {
      fetchedAt: Date.now(),
      source: '（模拟器）编的演示数据：没连平台，也没真去读',
      stage: 'P1',
      canSend: false,
      canSendNote: '这里只读和起草；发送要逐条确认（P2），现在一个字都不会发出去',
      unread: { mentions: 2, likes: 5, connections: 1, unread: 8 },
      filtered: 1,
      errors: [],
      gap: '',
      items: [
        {
          id: 'mock-n1',
          kind: 'comment',
          author: '阿岚', authorId: 'mock-u1',
          text: '这个方法能用在临床上吗？我爸的医生也在做类似的方向。',
          workTitle: 'DeepRare', at: Date.now() - 3600_000, liked: false,
          feedId: 'mock-f1', xsecToken: 'mock-token', commentId: 'mock-c1', canReply: true,
        },
        {
          id: 'mock-n2',
          kind: 'comment',
          author: '老周', authorId: 'mock-u2',
          text: '图表里的那个对比实验，样本量是不是有点小？',
          workTitle: 'DeepRare', at: Date.now() - 7200_000, liked: true,
          feedId: 'mock-f1', xsecToken: 'mock-token', commentId: 'mock-c2', canReply: true,
        },
        {
          id: 'mock-n3',
          kind: 'follow',
          author: '小林', authorId: 'mock-u3',
          text: '小林 关注了你',
          workTitle: '', at: Date.now() - 9000_000, liked: false,
          feedId: '', xsecToken: '', commentId: '', canReply: false,
        },
      ],
    }
  }

  async draftReply(body: DraftBody): Promise<DraftResult> {
    await new Promise((r) => setTimeout(r, 400))
    return {
      draft: {
        id: 'mock-draft1',
        at: Date.now(),
        author: body.author ?? '',
        workTitle: body.workTitle ?? '',
        commentText: body.commentText,
        // 模拟器不调模型、也不落盘，所以这里给的是一段**示例**，别把它当成真草稿
        reply: '（模拟器示例）临床验证我们还没做，所以我不能说它现在能用；我在做的是让人更快读懂这类研究。',
        why: '对方问能不能落地：先给边界，再给出路，别承诺没做过的事。',
        model: 'mock',
        stage: 'P1',
        sent: false,
      },
      savedTo: '',
      stage: 'P1',
      canSend: false,
      canSendNote: '（模拟器）没有真起草、也没有落盘 —— 接上真后端才会调用模型并写进 var/interactions/drafts.jsonl。',
    }
  }

  async interactionsReply(): Promise<InteractionReplyResult> {
    // 模拟器**故意**不发：这里没有真平台，装成发成功比报错更坏
    throw new Error('（模拟器）不会替你发：接上真后端才会走平台的写接口（而且还不一定开着发送开关）')
  }

  async uploadPaper(file: File): Promise<UploadResult> {
    await new Promise((r) => setTimeout(r, 200))
    return {
      uploadId: 'up_mock' + Math.random().toString(16).slice(2, 8),
      filename: file.name,
      bytes: file.size,
      sha256: 'mock',
    }
  }

  /* ---------- 运营维护（模拟器：形状与后端一致，数字是编的） ---------- */

  async opsServices(): Promise<OpsService[]> {
    const mk = (name: string, label: string, port: number, up: boolean): OpsService => ({
      name, label, port, up,
      pid: up ? 10000 + port : null,
      url: 'http://127.0.0.1:' + port,
      health: up
        ? { probed: port !== 5178, ok: true, status: 200, elapsedMs: 12, detail: port === 5178 ? '无 HTTP 健康接口（前端静态服务）' : 'HTTP 200' }
        : { probed: false, ok: false, detail: '端口未监听' },
      log: { path: 'var/logs/' + name + '.log', exists: up, size: 4096, updatedAt: Date.now() - 20000 },
      restartHint: './ops/start_all.sh ' + name,
    })
    return [
      mk('backend', '后端 API', 8000, true),
      mk('frontend', '前端 (vite)', 5178, true),
      mk('mcp', '小红书 MCP', 18060, true),
      mk('zhihu', '知乎通道', 18070, false),
      mk('bilibili', 'B 站通道', 18080, false),
    ]
  }

  async opsLogs(name: string, lines = 200, grep = ''): Promise<OpsLog> {
    const demo = [
      'INFO:     127.0.0.1:44130 - "GET /api/health HTTP/1.1" 200 OK',
      'INFO:     127.0.0.1:44148 - "GET /api/platforms HTTP/1.1" 200 OK',
      'WARNING:  单次探测耗时 11.2s（MCP 侧开了一次无头浏览器）',
      'ERROR:    模拟器里的日志是编的，接上真后端后这里读 var/logs/' + name + '.log',
    ].filter((l) => !grep || l.includes(grep))
    return { name, path: 'var/logs/' + name + '.log', lines: demo.slice(-lines), matched: demo.length, size: 8192, truncated: false }
  }

  async opsMetrics(): Promise<OpsMetrics> {
    return {
      fetchedAt: Date.now(),
      channels: [
        {
          id: 'bilibili', name: 'B 站', kind: 'video',
          source: '模拟器演示数据（真后端会用公开 view 接口取真实数字）',
          items: [{
            id: 'BV1DveU6GEPR', url: 'https://www.bilibili.com/video/BV1DveU6GEPR',
            title: '【演示】Paper2Video 论文分享视频', author: '演示账号', publishedAt: Date.now() - 3600_000,
            stats: { view: 128, like: 12, coin: 5, favorite: 9, reply: 3, danmaku: 1, share: 2 },
            source: 'mock',
          }],
          errors: [],
          totals: { view: 128, like: 12, coin: 5, favorite: 9, reply: 3, danmaku: 1, share: 2 },
          gap: '',
        },
        {
          id: 'zhihu', name: '知乎', kind: 'article', source: '模拟器演示数据',
          items: [{
            id: '2084432742410993947', url: 'https://zhuanlan.zhihu.com/p/2084432742410993947',
            title: '【演示】用已登录浏览器抓赞同数', author: '演示账号',
            stats: { like: 7, reply: 2 }, source: 'mock',
          }],
          errors: [], totals: { like: 7, reply: 2 },
          gap: '浏览量知乎不对外提供（只在创作者中心可见）',
        },
        {
          id: 'xiaohongshu', name: '小红书', kind: 'note', source: '模拟器演示数据',
          items: [], errors: [], totals: {},
          account: { name: '演示账号', raw: { fans: 3, liked: 15, collected: 4 } },
          gap: '单篇浏览量在创作者中心，MCP 未覆盖；未登录时账号级数据也拿不到',
        },
      ],
    }
  }

  async opsServiceAction(name: string, action: string) {
    return { service: name, action, output: '模拟器不会真的起停服务：接上真后端（VITE_API_BASE）后这里会调 ops/start_all.sh' }
  }

  async testLlm(): Promise<LlmTestResult> {
    return { ok: false, ms: 0, code: 'MOCK', message: '模拟器不连后端，无法探测', model: '—', baseUrl: '—' }
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
    next.logs.push({ ts: Date.now(), level: 'info', text: `▶ ${next.label}` })
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
