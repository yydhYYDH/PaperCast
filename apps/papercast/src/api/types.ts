import type { PaperRun, RunConfig, SourceInput, StageId } from '../types'

export interface CreateRunRequest {
  source: SourceInput
  config: RunConfig
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
  dispose(): void
}
