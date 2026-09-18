import type { PipelineApi } from './types'
import { MockPipelineApi } from './mock'
import { HttpPipelineApi } from './http'

const apiBase = import.meta.env.VITE_API_BASE as string | undefined

/** 唯一的 API 入口：有 VITE_API_BASE 就走真实后端，否则用内置模拟器。 */
export const api: PipelineApi = apiBase ? new HttpPipelineApi(apiBase) : new MockPipelineApi()

/**
 * 后端给的资源地址是**相对**的（/artifacts/... 、二维码 img 也可能是 / 开头），
 * 直接塞进 fetch/src 会解析成前端 dev server 的地址而 404，这里统一补成绝对地址。
 */
export function assetUrl(url?: string): string {
  if (!url) return ''
  if (!url.startsWith('/') || !apiBase) return url
  return apiBase.replace(/\/$/, '') + url
}

export type { PipelineApi, CreateRunRequest } from './types'
