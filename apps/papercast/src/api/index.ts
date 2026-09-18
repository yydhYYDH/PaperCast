import type { PipelineApi } from './types'
import { MockPipelineApi } from './mock'
import { HttpPipelineApi } from './http'

const apiBase = import.meta.env.VITE_API_BASE as string | undefined

/** 唯一的 API 入口：有 VITE_API_BASE 就走真实后端，否则用内置模拟器。 */
export const api: PipelineApi = apiBase ? new HttpPipelineApi(apiBase) : new MockPipelineApi()

export type { PipelineApi, CreateRunRequest } from './types'
