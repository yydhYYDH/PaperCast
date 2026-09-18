import type {
  PaperRun,
  PlatformChannel,
  PlatformDraftBody,
  PlatformLoginStart,
  PlatformPublishRequest,
  PlatformPublishResult,
  PlatformQrcode,
  RunConfig,
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
  /** 退出登录（清 cookies，不可逆） */
  platformLogout(channelId: string): Promise<void>
  /** 配置中心：回显全部可配项（密钥打码）。模拟器返回假配置，写入会抛错 */
  getConfig(): Promise<AppConfig>
  /** 按白名单写 .env 并热生效；密钥留空/省略 = 不修改 */
  patchConfig(values: Record<string, string>): Promise<ConfigPatchResult>
  /** 连通性探针：用当前配置发一个最小请求，回显延迟与模型回话 */
  testLlm(): Promise<LlmTestResult>
  dispose(): void
}
