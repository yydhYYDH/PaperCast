/** 领域模型：一条「论文 → 多形态产物」的运行 */

export type ViewId = 'workbench' | 'runs' | 'library' | 'platforms' | 'ops' | 'settings'

export type StageId = 'intake' | 'understand' | 'article' | 'poster' | 'video' | 'publish'

export type StageStatus = 'pending' | 'running' | 'waiting' | 'done' | 'failed' | 'skipped'

export type RunStatus = 'queued' | 'running' | 'waiting' | 'done' | 'failed'

export type SourceKind = 'arxiv' | 'pdf' | 'latex'

export type ArtifactKind =
  | 'markdown'
  | 'html'
  | 'image'
  | 'video'
  | 'json'
  | 'pptx'
  | 'text'

export interface SourceInput {
  kind: SourceKind
  /** arxiv id / 上传文件名 / latex 工程目录名 */
  value: string
  title?: string
  authors?: string[]
  venue?: string
  pages?: number
  bytes?: number
}

export interface Artifact {
  id: string
  stageId: StageId
  kind: ArtifactKind
  label: string
  /** 虚拟产物路径，如 .papercast/runs/<id>/article/zhihu-analyst.md */
  path: string
  /** 前端预览地址（本地 samples 或后端静态目录） */
  url?: string
  bytes?: number
  meta?: Record<string, string | number | boolean>
}

export interface LogLine {
  ts: number
  level: 'info' | 'ok' | 'warn' | 'err'
  text: string
}

/** 人工确认闸门：真实 skill 链在关键决策点会停等用户确认 */
export interface StageGate {
  id: string
  label: string
  detail: string
  options: { id: string; label: string; hint?: string }[]
  resolved?: string
}

export interface Stage {
  id: StageId
  label: string
  /** 这一阶段复用的开源实现 */
  engine: string
  status: StageStatus
  progress: number
  startedAt?: number
  endedAt?: number
  logs: LogLine[]
  artifacts: Artifact[]
  gate?: StageGate
  /** 评分/校验条目，例如 poster 的几何检查与盲读测验 */
  checks?: { label: string; state: 'pass' | 'fail' | 'run'; detail: string }[]
}

export interface PaperDigest {
  arxivId: string
  title: string
  authors: string[]
  venue: string
  year: number
  abstractCn: string
  keywords: string[]
  contributions: string[]
  method: string
  results: { label: string; value: string; note: string }[]
  figures: { id: string; caption: string; source: string }[]
  limitations: string[]
  stagesNote: string
}

/* ---------- 运营维护 ---------- */

export interface OpsHealth {
  probed: boolean
  ok: boolean | null
  status?: number
  elapsedMs?: number
  detail: string
}

export interface OpsService {
  name: string
  label: string
  port: number
  up: boolean
  pid: number | null
  url: string
  health: OpsHealth
  log: { path: string; exists: boolean; size: number; updatedAt: number }
  restartHint: string
}

export interface OpsLog {
  name: string
  path: string
  lines: string[]
  matched: number
  size: number
  truncated: boolean
}

export interface OpsMetricItem {
  id: string
  url: string
  title: string
  author?: string
  publishedAt?: number
  stats: Record<string, number | null>
  source: string
}

export interface OpsMetricChannel {
  id: string
  name: string
  kind: string
  source: string
  items: OpsMetricItem[]
  errors: string[]
  totals: Record<string, number>
  gap: string
  account?: { name: string; raw: Record<string, unknown> }
}

export interface OpsMetrics {
  fetchedAt: number
  channels: OpsMetricChannel[]
}

export interface ArticleVariant {
  /** "{platform}-{voice}"，例如 zhihu-analyst */
  id: string
  /** 与后端 app/styles.py 的 PLATFORMS 一致（后端 models.py 已含 "en"，漏加会导致收不到英文变体） */
  platform: 'xhs' | 'zhihu' | 'bilibili' | 'en'
  voice: string
  label: string
  url: string
  words?: number
}

export interface RunConfig {
  /** 用户自由文本指令（「这篇论文我想出成什么格式」）。只影响风格/体裁/篇幅/侧重，
   *  不改变事实层；适用边界见后端 app/prompts.py 的 BRIEF_RULES，遵从度由 brief_checks 机检 */
  brief?: string
  article: { variants: string[] }
  poster: { size: string; venue: string; theme: string; lang: string }
  video: { durationSec: number; voice: string; aspect: '16:9' | '9:16'; narration: string }
  publish: { targets: string[]; autoPublish: boolean }
}

export interface PaperRun {
  id: string
  createdAt: number
  title: string
  source: SourceInput
  status: RunStatus
  stages: Stage[]
  config: RunConfig
  digest?: PaperDigest
  articles?: ArticleVariant[]
}

/** 平台渠道与登录态（与后端 GET /api/platforms 一致） */
export type PlatformState = 'ready' | 'login_required' | 'offline' | 'unconfigured' | 'blocked'

/** 登录方式：qrcode=现场扫码 / browser=桌面窗口人工登录 / env=配置凭证 / cli=命令行登录 / none=无 */
export type PlatformLogin = 'qrcode' | 'browser' | 'env' | 'cli' | 'none'

export interface PlatformChannel {
  id: string
  name: string
  kind: 'mcp' | 'playwright' | 'openapi' | 'cli'
  login: PlatformLogin
  state: PlatformState
  /** 已登录账号；未登录为空串 */
  account: string
  /** 人类可读的一句话状态，直接显示 */
  detail: string
  /** 渠道服务地址（MCP base / API 域名 / CLI 名） */
  endpoint: string
  /** 投递这个渠道需要什么 */
  needs: string[]
  capabilities: string[]
  /** 怎么把这个渠道接通（未接通时显示） */
  loginHint: string
}

/** 桌面窗口人工登录（知乎）：调用后 state 变 ready 即成功 */
export interface PlatformLoginStart {
  channelId: string
  method: 'browser'
  started: boolean
  pid?: number
  hint: string
}

/** 待发布内容（知乎通道：标题 + 纯文本正文，可选图片/话题） */
export interface PlatformDraftBody {
  title: string
  content: string
  images?: string[]
  tags?: string[]
  /** 关联的 run id：给了就在通道侧落一份回执 */
  runId?: string
}

/** 真实投递请求：**必须 confirmed=true**（人工闸门放行） */
export interface PlatformPublishRequest extends PlatformDraftBody {
  confirmed: boolean
  /** 可选的账号二次校验：与当前登录账号不一致时通道侧拒绝发布 */
  confirmAccount?: string
}

export interface PlatformPublishResult {
  url: string
  title: string
  publishedAt: string
  account: string
  transport?: string
  receipt?: string
}

/** 扫码登录二维码。timeout 是 MCP 给的字符串（"4m0s"），expiresAt 是毫秒时间戳 */
export interface PlatformQrcode {
  channelId: string
  isLoggedIn: boolean
  img: string
  timeout: string
  expiresAt: number
  account: string
}

export const STAGE_ORDER: StageId[] = ['intake', 'understand', 'article', 'poster', 'video', 'publish']

export const STAGE_META: Record<StageId, { label: string; hint: string }> = {
  intake: { label: '输入归一化', hint: 'PDF / arXiv / LaTeX → 统一 paper 模型' },
  understand: { label: '论文理解层', hint: '唯一事实源：贡献 / 方法 / 证据 / 图表' },
  article: { label: '文章生成', hint: '平台体裁 × 讲述者人格（小红书 / 知乎 / B站）' },
  poster: { label: 'Poster 生成', hint: '排版、作图、盲读校验' },
  video: { label: '视频合成', hint: '幻灯片 → 旁白 → 配音 → 合成 + 封面' },
  publish: { label: '发布与运营', hint: '小红书 / 知乎 / B 站，人工确认后发出' },
}
