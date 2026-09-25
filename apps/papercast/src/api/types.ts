import type {
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
  RunConfig,
  RunDrafts,
  RunPublishRequest,
  RunPublishResult,
  SourceInput,
  StageId,
} from '../types'

export interface CreateRunRequest {
  source: SourceInput
  config: RunConfig
}

/** 配置中心（GET /api/config）：密钥只回打码值，永不回明文 */
export type ConfigKind = 'str' | 'int' | 'bool' | 'list' | 'secret'

export interface ConfigItem {
  key: string
  group: string
  label: string
  kind: ConfigKind
  desc: string
  /** false = 由运行环境注入（ops/start_all.sh），改了也不生效 */
  editable: boolean
  /** true = 改了要重启后端才生效；其余热生效 */
  restart: boolean
  /** 当前值；密钥为打码值，如 sk-****PUYh */
  value: string
  /** 值来自哪里：default | .env | environment | dsh-credential | unset */
  source: string
  configured?: boolean
}

export interface AppConfig {
  envFile: string
  envFileExists: boolean
  items: ConfigItem[]
}

export interface UploadResult {
  uploadId: string
  filename: string
  bytes: number
  sha256: string
}

export interface ChatRequest {
  message: string
  runId?: string | null
  history?: { role: string; content: string }[]
}

/**
 * 一句话能变成一张**动作卡**（后端 app/chat_api.py 的「意图 → 动作提案」）：
 * 对话里渲染成「一句话 + 一个动词按钮」，点了才真的执行 —— 服务端不会因为一句话就投递或起停进程。
 */
export type ChatActionKind = 'gate' | 'metrics' | 'service' | 'run' | 'interactions' | 'draft' | 'reply'
export type ChatActionRisk = 'readonly' | 'local' | 'public'

export interface ChatAction {
  kind: ChatActionKind
  title: string
  detail?: string
  /** 执行参数，按 kind 不同；全部由后端给出，前端不猜 */
  params: Record<string, unknown>
  /** false = 只读动作，前端直接执行（少一次点击）；true = 必须用户点那个按钮 */
  needsConfirm: boolean
  confirmLabel: string
  /** public = 真的发到平台上、撤不回来；界面上按危险动作渲染 */
  risk: ChatActionRisk
}

/**
 * 互动 P1（后端 app/interactions.py）：**只读**评论/通知 + 起草回复，发送是 P2 且要逐条确认。
 * 契约里写死了 canSend: false —— 前端别自己发明一个「发送」按钮。
 */
export interface InteractionItem {
  id: string
  /** comment = 真评论（有 commentId 才谈得上回）；其余是关注/点赞这类通知 */
  kind: string
  author: string
  authorId: string
  text: string
  workTitle: string
  at: number
  liked: boolean
  feedId: string
  /** 访问令牌：只用于 P2 的回复，**不要**写进日志/文档/截图 */
  xsecToken: string
  commentId: string
  canReply: boolean
}

export interface InteractionsResult {
  fetchedAt: number
  source: string
  stage: string
  canSend: boolean
  canSendNote: string
  unread: { mentions?: number; likes?: number; connections?: number; unread?: number } | null
  items: InteractionItem[]
  /** 平台上被过滤掉（已删除/不可见）的条数 —— 让「列表比实际少」这件事可见 */
  filtered: number
  errors: string[]
  /** 读不到时的原因（读到了就是空串）。前端照原话说，别拿「0 条评论」顶替 */
  gap: string
}

export interface DraftBody {
  commentText: string
  author?: string
  workTitle?: string
  note?: string
}

export interface InteractionDraft {
  id: string
  at: number
  author: string
  workTitle: string
  commentText: string
  reply: string
  why: string
  model: string
  stage: string
  /** 恒为 false：P1 只落盘 */
  sent: boolean
  saveError?: string
}

export interface DraftResult {
  draft: InteractionDraft
  savedTo: string
  stage: string
  canSend: boolean
  canSendNote: string
}

/**
 * P2：把一条起草好的回复真发出去。**必须** confirmed=true（后端还会查开关与限速）。
 * 这是全项目唯一替人「说话」的地方，所以前端一律先过 ui.askConfirm 再调。
 */
export interface InteractionReplyBody {
  content: string
  commentId?: string
  feedId?: string
  /** 访问令牌：只在内存里过一手，不写日志、不进证据截图 */
  xsecToken?: string
  userId?: string
  draftId?: string
  confirmed: boolean
}

export interface InteractionReplyResult {
  sent: boolean
  at: number
  content: string
  target: string
  savedTo: string
  stage: string
  note: string
}

export interface ChatReply {
  reply: string
  model: string
  context: { runId: string | null; hasDigest: boolean; artifacts: number }
  /** 认不出意图时为 null（那就是一次普通的问答） */
  action?: ChatAction | null
}

export interface PlatformLogoutResult {
  channelId: string
  /** 人话回执：清了什么、现在是什么状态 */
  message: string
  state?: string
  account?: string
  restartOutput?: string[]
}

export interface ConfigPatchResult {
  changed: string[]
  envFile: string
  applied: boolean
  restartNeeded?: string[]
}

export interface LlmTestResult {
  ok: boolean
  ms: number
  reply?: string
  code?: string
  message?: string
  model: string
  baseUrl: string
}

/** 本机运行环境（后端 GET /api/env 的真实探测结果；只取界面要用的部分） */
export interface EnvStatus {
  intake: { engine: string; ocr: boolean }
  llm: { configured: boolean; model: string }
  cards: { enabled: boolean; cjkFontUsable: boolean }
  publish: { xiaohongshu?: { reachable: boolean; loggedIn: boolean; account: string } }
}

/** 风格技能：描述来自 SKILL.md 的 frontmatter（原文要再调 skill()） */
export interface SkillInfo {
  name: string
  description: string
  /** repo = 本仓库 .dsh/skills（跟着代码走）· user = ~/.agents/skills（ops/install_skills.sh 装的） */
  origin: 'repo' | 'user'
  dir: string
  root: string
  /** 分册文件名（「展开还能看更多」），没有就是空数组 */
  references: string[]
  /** 是不是风格类技能（前端把它们排在「风格」一组里） */
  style: boolean
}

export interface SkillDetail extends SkillInfo {
  body: string
  truncated: boolean
}

/* --------------------------------------------------------------------------- */
/* 文章风格：平台 × 讲述者人格（后端 app/styles.py 是唯一真源）                    */
/* --------------------------------------------------------------------------- */

/** 一条风格（风格页显示成「小红书 · 专业科普」）。字段与后端 style_menu() 一一对应 */
export interface StyleOption {
  /** "{platform}-{voice}"，就是发给后端的 config.article.variants 元素 */
  variant: string
  platform: string
  platformLabel: string
  voice: string
  /** 口语化的风格名（专业科普 / 震惊流 / 白话拆解 …） */
  short: string
  /** 一句话：这条读起来什么样 */
  hint: string
  /** 参考锚点（新智元式 / 机器之心式 …），只作说明，不当风格名 */
  anchor: string
  /** 日志与文档里的规范名，如「小红书 × 第三人称独立视角」 */
  label: string
  sampled: string
  output: string
  bodyMin: number
  bodyMax: number
  unit: string
  allowFormula: boolean
  tagsMin: number
  tagsMax: number
  titleWeightMax: number | null
  titleCharsMax: number | null
  cards: boolean
}

/** 一条 HF Daily Paper（GET /api/hf-daily） */
export interface HfDailyPaper {
  arxivId: string
  title: string
  summary: string
  upvotes: number | null
  publishedAt: string
  authors: string[]
  thumbnail: string
  githubRepo: string
  arxivUrl: string
  pdfUrl: string
}

export interface HfDailyResult {
  date: string
  /** '' = 按日期/最新；'trending' = 趋势榜 */
  sort?: string
  fetchedAt: number
  count: number
  papers: HfDailyPaper[]
  /** true = 抓不到新的，回的是旧缓存（界面要如实说） */
  stale: boolean
  error: string
}

export interface StyleMenu {
  default: { platform: string; voice: string; variant: string }
  maxVariants: number
  platforms: { id: string; label: string }[]
  voices: { id: string; label: string; short: string; hint: string }[]
  styles: StyleOption[]
}

export interface PipelineApi {
  /** 人类可读的实现说明，显示在设置里 */
  readonly label: string
  listRuns(): Promise<PaperRun[]>
  createRun(req: CreateRunRequest): Promise<PaperRun>
  getRun(id: string): Promise<PaperRun | undefined>
  cancelRun(id: string): Promise<void>
  /** 人工闸门：确认或打回某一阶段 */
  resolveGate(runId: string, stageId: StageId, optionId: string): Promise<void>
  /** 平台渠道与登录态（force 绕过后端 5s 探测缓存） */
  listPlatforms(force?: boolean): Promise<PlatformChannel[]>
  /** 取扫码登录二维码；每次调用都会新建一次 MCP 侧等待会话，只在用户点击时调 */
  platformLoginQrcode(channelId: string): Promise<PlatformQrcode>
  /** 起桌面窗口人工登录（知乎）；调用后轮询 listPlatforms 看 state 是否变 ready */
  platformLoginStart(channelId: string): Promise<PlatformLoginStart>
  /** **无副作用**：把待发内容落到导出目录（闸门未放行时用这条） */
  platformExportDraft(channelId: string, body: PlatformDraftBody): Promise<{ dir: string; files: string[] }>
  /** **真实投递**：必须 confirmed=true（人工闸门放行后） */
  platformPublish(channelId: string, body: PlatformPublishRequest): Promise<PlatformPublishResult>
  /** 退出登录（删除本机凭证，不可逆）。返回后端如实写的执行结果，用于向用户回执。 */
  platformLogout(channelId: string): Promise<PlatformLogoutResult>

  /* ---------- 作品库直投：不走流水线闸门的那条发布路径 ---------- */
  /** 这次运行的逐渠道待发草稿：真产物 + 真登录态 + 「为什么投不了」 */
  listRunDrafts(runId: string): Promise<RunDrafts>
  /** 把作品投到一个渠道：confirmed=false 只落 export/（无副作用），true 才真投递。
   *  形态按渠道默认走（小红书图文、B 站视频），要成片走下面的 publishRunVideo。 */
  publishRunWork(runId: string, body: RunPublishRequest): Promise<RunPublishResult>
  /** 把作品发成成片（小红书视频笔记 / B 站投稿）：形态选错代价大，所以单独一个端点 */
  publishRunVideo(runId: string, body: RunPublishRequest): Promise<RunPublishResult>

  /* ---------- 对话 ---------- */
  /** 一问一答：回答只依据该运行已落盘的事实源（见后端 app/chat_api.py） */
  chat(body: ChatRequest): Promise<ChatReply>

  /* ---------- 互动（P1：只读 + 起草，不发送） ---------- */
  /** 读一遍小红书「评论和@」（只读）。读不到会返回 gap 说明原因，不是异常 */
  interactions(limit?: number): Promise<InteractionsResult>
  /** 给一条评论起草回复：**只落盘，不发送**（发送是 P2，要逐条确认） */
  draftReply(body: DraftBody): Promise<DraftResult>
  /** P2：把一条**已确认**的回复真发出去（后端开关默认关着，关着会回 SEND_DISABLED） */
  interactionsReply(body: InteractionReplyBody): Promise<InteractionReplyResult>
  /** 上传 PDF/LaTeX 包，拿到 uploadId（createRun 的 source.value 用它） */
  uploadPaper(file: File): Promise<UploadResult>

  /* ---------- 技能 / 个性化层 ---------- */
  /** 本机能找到的技能（风格技能排在前面）：只读 SKILL.md 的 frontmatter，改不了任何东西 */
  skills(): Promise<SkillInfo[]>
  /** 一个技能的 SKILL.md 原文（前端「看它的规矩」用） */
  skill(name: string): Promise<SkillDetail>
  /** 文章风格清单：平台 × 讲述者人格（风格页用它渲染「小红书 · 专业科普」这类条目） */
  styles(): Promise<StyleMenu>

  /* ---------- 每日论文 ---------- */
  /** HuggingFace Daily Papers：date 留空取最新；sort='trending' 取趋势榜；force 绕过缓存重新抓 */
  hfDaily(date?: string, sort?: string, force?: boolean): Promise<HfDailyResult>


  /* ---------- 运营维护 ---------- */
  /** 本机五个服务的真实状态（端口 / pid / 健康 / 日志） */
  opsServices(): Promise<OpsService[]>
  /** 读 var/logs/<name>.log 的尾巴 */
  opsLogs(name: string, lines?: number, grep?: string): Promise<OpsLog>
  /** 运营数据：本机发现的已发布内容 + 各平台真实互动数字 */
  opsMetrics(force?: boolean): Promise<OpsMetrics>
  /** 起 / 停 / 重启某个服务（走 ops/start_all.sh、ops/stop_all.sh） */
  opsServiceAction(name: string, action: 'start' | 'stop' | 'restart'): Promise<{ service: string; action: string; output: string }>
  /** 本机运行环境的真实探测结果（模型是否配好、中文字体、发布服务是否在线） */
  env(): Promise<EnvStatus>
  /** 配置中心：回显全部可配项（密钥打码）。模拟器返回假配置，写入会抛错 */
  getConfig(): Promise<AppConfig>
  /** 按白名单写 .env 并热生效；密钥留空/省略 = 不修改 */
  patchConfig(values: Record<string, string>): Promise<ConfigPatchResult>
  /** 连通性探针：用当前配置发一个最小请求，回显延迟与模型回话 */
  testLlm(): Promise<LlmTestResult>
  dispose(): void
}
