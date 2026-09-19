import type { PipelineApi, CreateRunRequest } from './types'
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
  RunDrafts,
  RunPublishRequest,
  RunPublishResult,
  StageId,
} from '../types'
import type {
  AppConfig,
  ChatReply,
  ChatRequest,
  ConfigPatchResult,
  SkillDetail,
  SkillInfo,
  DraftBody,
  DraftResult,
  EnvStatus,
  InteractionReplyBody,
  InteractionReplyResult,
  InteractionsResult,
  LlmTestResult,
  PlatformLogoutResult,
  UploadResult,
} from './types'

/**
 * 真实后端适配器（骨架）。
 *
 * 契约（与 Paper2Slides 的 /api/chat + /api/status 形状对齐，改为资源式）：
 *   POST   /api/runs                      -> PaperRun
 *   GET    /api/runs                      -> PaperRun[]
 *   GET    /api/runs/:id                  -> PaperRun
 *   POST   /api/runs/:id/cancel           -> 204
 *   POST   /api/runs/:id/stages/:sid/gate -> { optionId } -> 204
 *   GET    /api/runs/:id/events           -> SSE（可选，未接时退化为轮询）
 *   GET    /api/platforms                 -> PlatformChannel[]（渠道登录态）
 *   GET    /api/platforms/:id/login/qrcode-> PlatformQrcode（扫码登录）
 *   POST   /api/platforms/:id/login/start -> PlatformLoginStart（桌面窗口人工登录）
 *   POST   /api/platforms/:id/export      -> { dir, files }（只落盘，无副作用）
 *   POST   /api/platforms/:id/publish     -> PlatformPublishResult（必须 confirmed=true）
 *   POST   /api/platforms/:id/login/logout-> 204
 *   GET    /api/runs/:id/drafts           -> RunDrafts（作品库直投：逐渠道待发草稿）
 *   POST   /api/runs/:id/publish          -> RunPublishResult（一个渠道一次确认；confirmed 才真投）
 *   GET    /api/ops/services              -> OpsService[]（五个服务的端口/pid/健康/日志）
 *   POST   /api/ops/services/:name/:action-> 起停服务（start|stop|restart）
 *   GET    /api/ops/logs?name=&lines=     -> OpsLog（var/logs/*.log 的尾巴）
 *   GET    /api/ops/metrics               -> OpsMetrics（已发布内容的浏览/点赞等）
 *   GET    /api/config                    -> AppConfig（全部可配项，密钥打码）
 *   PATCH  /api/config                    -> { values } -> ConfigPatchResult（写 .env 并热生效）
 *   POST   /api/config/test               -> LlmTestResult（连通性探针）
 *
 * 运行前设置 VITE_API_BASE=http://127.0.0.1:8000 即自动切换到这个实现，
 * 前端组件与 store 无需改动。
 */
export class HttpPipelineApi implements PipelineApi {
  readonly label: string

  constructor(private base: string) {
    this.label = `HTTP · ${base}`
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(this.base.replace(/\/$/, '') + path, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
    if (!res.ok) throw new Error(await this.why(res, init?.method ?? 'GET', path))
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
  }

  /**
   * 出错时说人话：后端所有错误都是 `{ error: { code, message } }`（见 app/main.py 的 fail()），
   * 而 `POST /x -> 409` 这种机械信息会被原样弹给用户 —— 「发布失败」和「为什么失败」是两回事。
   */
  private async why(res: Response, method: string, path: string): Promise<string> {
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } }
      const err = body?.error
      if (err?.message) return err.code ? `${err.message}（${err.code}）` : err.message
    } catch (e) {
      // 不是 JSON（网关 / 代理返回的 HTML）→ 退到状态码
    }
    return `${method} ${path} -> ${res.status}`
  }

  listRuns() {
    return this.json<PaperRun[]>('/api/runs')
  }

  createRun(req: CreateRunRequest) {
    return this.json<PaperRun>('/api/runs', { method: 'POST', body: JSON.stringify(req) })
  }

  getRun(id: string) {
    return this.json<PaperRun | undefined>(`/api/runs/${id}`)
  }

  async cancelRun(id: string) {
    await this.json<void>(`/api/runs/${id}/cancel`, { method: 'POST' })
  }

  async resolveGate(runId: string, stageId: StageId, optionId: string) {
    await this.json<void>(`/api/runs/${runId}/stages/${stageId}/gate`, {
      method: 'POST',
      body: JSON.stringify({ optionId }),
    })
  }

  // ---------- 平台渠道与登录 ----------

  listPlatforms(force = false) {
    return this.json<PlatformChannel[]>(`/api/platforms${force ? '?force=1' : ''}`)
  }

  platformLoginQrcode(channelId: string) {
    return this.json<PlatformQrcode>(`/api/platforms/${channelId}/login/qrcode`)
  }

  platformLoginStart(channelId: string) {
    return this.json<PlatformLoginStart>(`/api/platforms/${channelId}/login/start`, { method: 'POST' })
  }

  platformExportDraft(channelId: string, body: PlatformDraftBody) {
    return this.json<{ dir: string; files: string[] }>(`/api/platforms/${channelId}/export`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  platformPublish(channelId: string, body: PlatformPublishRequest) {
    return this.json<PlatformPublishResult>(`/api/platforms/${channelId}/publish`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  platformLogout(channelId: string) {
    return this.json<PlatformLogoutResult>(`/api/platforms/${channelId}/login/logout`, { method: 'POST' })
  }

  /* ---------- 作品库直投 ---------- */

  listRunDrafts(runId: string) {
    return this.json<RunDrafts>(`/api/runs/${runId}/drafts`)
  }

  publishRunWork(runId: string, body: RunPublishRequest) {
    return this.json<RunPublishResult>(`/api/runs/${runId}/publish`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  /* ---------- 对话 ---------- */

  chat(body: ChatRequest) {
    return this.json<ChatReply>('/api/chat', { method: 'POST', body: JSON.stringify(body) })
  }

  uploadPaper(file: File) {
    const form = new FormData()
    form.append('file', file, file.name)
    // 必须让浏览器自己带 multipart boundary：不能沿用 json() 默认的 application/json
    return this.json<UploadResult>('/api/uploads', { method: 'POST', body: form, headers: {} })
  }

  /* ---------- 技能 / 个性化层 ---------- */

  skills() {
    return this.json<SkillInfo[]>('/api/skills')
  }

  skill(name: string) {
    return this.json<SkillDetail>('/api/skills/' + encodeURIComponent(name))
  }

  /* ---------- 运营维护 ---------- */

  opsServices() {
    return this.json<OpsService[]>('/api/ops/services')
  }

  opsLogs(name: string, lines = 200, grep = '') {
    const qs = new URLSearchParams({ name, lines: String(lines) })
    if (grep) qs.set('grep', grep)
    return this.json<OpsLog>('/api/ops/logs?' + qs.toString())
  }

  opsMetrics(force = false) {
    return this.json<OpsMetrics>('/api/ops/metrics' + (force ? '?force=true' : ''))
  }

  /** 读一遍互动（只读）；读不到由后端如实写进 gap，不抛错 */
  interactions(limit = 10) {
    return this.json<InteractionsResult>(`/api/interactions?limit=${limit}`)
  }

  /** 起草回复：后端只落盘、不发送（发送是 P2，要逐条确认） */
  draftReply(body: DraftBody) {
    return this.json<DraftResult>('/api/interactions/draft', { method: 'POST', body: JSON.stringify(body) })
  }

  /** P2：真发一条（后端要 confirmed=true + 开关打开 + 没超限速，三者缺一就报错） */
  interactionsReply(body: InteractionReplyBody) {
    return this.json<InteractionReplyResult>('/api/interactions/reply', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  opsServiceAction(name: string, action: 'start' | 'stop' | 'restart') {
    return this.json<{ service: string; action: string; output: string }>(`/api/ops/services/${name}/${action}`, { method: 'POST' })
  }

  env() {
    return this.json<EnvStatus>('/api/env')
  }

  getConfig() {
    return this.json<AppConfig>('/api/config')
  }

  patchConfig(values: Record<string, string>) {
    return this.json<ConfigPatchResult>('/api/config', {
      method: 'PATCH',
      body: JSON.stringify({ values }),
    })
  }

  testLlm() {
    return this.json<LlmTestResult>('/api/config/test', { method: 'POST' })
  }

  dispose() {}
}
