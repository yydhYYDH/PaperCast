import type { PipelineApi, CreateRunRequest } from './types'
import type { PaperRun, StageId } from '../types'

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
    if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} -> ${res.status}`)
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
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

  dispose() {}
}
