import type {
  PipelineApi,
  CreateRunRequest,
  AppConfig,
  ConfigItem,
  ConfigPatchResult,
  LlmTestResult,
} from './types'
import type {
  Artifact,
  ArtifactKind,
  LogLine,
  PaperRun,
  PlatformChannel,
  PlatformDraftBody,
  PlatformLoginStart,
  PlatformPublishRequest,
  PlatformPublishResult,
  PlatformQrcode,
  PlatformState,
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
    engine: STAGE_META[id].engine,
    status,
    progress: 0,
    logs: [],
    artifacts: [],
    gate: GATES[id] ? { ...GATES[id]!, options: GATES[id]!.options.map((o) => ({ ...o })) } : undefined,
    checks: CHECKS[id] ? CHECKS[id]!.map((c) => ({ ...c })) : undefined,
  }
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
]

const DEFAULT_CONFIG: RunConfig = {
  article: { variants: ['xhs-author', 'zhihu-analyst'] },
  poster: { size: '36×48 in', venue: 'NeurIPS 2025', theme: 'default', lang: 'en' },
  video: { durationSec: 300, voice: 'zh-CN-XiaoxiaoNeural', aspect: '16:9', narration: '中文' },
  publish: { targets: ['xhs', 'zhihu'], autoPublish: false },
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

  async platformLogout(channelId: string) {
    if (channelId === 'zhihu') {
      this.zhihuState = 'login_required'
      this.zhihuAccount = ''
      this.zhihuLoggedInAt = 0
      return
    }
    if (channelId !== 'xhs') return
    this.xhsState = 'login_required'
    this.xhsAccount = ''
    this.xhsLoggedInAt = 0
  }

  /**
   * 模拟器不连后端，给一份与后端 SPEC 同形状的假配置：字段名、分组、kind 都对齐，
   * 这样「设置 → 模型与 API」在 mock 模式下也能完整渲染（值仅供示意，写入会抛错）。
   */
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
