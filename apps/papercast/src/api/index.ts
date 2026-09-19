import type { PipelineApi } from './types'
import { MockPipelineApi } from './mock'
import { HttpPipelineApi } from './http'

const configuredBase = import.meta.env.VITE_API_BASE as string | undefined

/** 本机地址：写在配置里的 127.0.0.1 只在这台机器上成立 */
function isLoopback(host: string) {
  return host === '127.0.0.1' || host === 'localhost' || host === '0.0.0.0' || host === '[::1]' || host === '::1'
}

/**
 * 手机上打开时，配置里那个 http://127.0.0.1:8000 指的是**手机自己**，照用会一片失败；
 * 这种「页面不在本机」的情况改走同源相对地址（/api、/artifacts），
 * 由 vite dev 的代理转给本机后端（见 vite.config.ts）。本机打开时行为完全不变。
 */
function resolveBase(configured?: string): string | undefined {
  if (!configured) return configured
  const pageIsLocal = isLoopback(location.hostname)
  const pointsToLocal = isLoopback(new URL(configured, location.href).hostname)
  return pointsToLocal && !pageIsLocal ? '' : configured
}

const apiBase = resolveBase(configuredBase)

/** 唯一的 API 入口：配了地址就走真实后端，否则用内置模拟器。 */
// resolveBase 配了地址就一定给出字符串（本机→原地址，手机→空串走同源），?? '' 只是把类型收干净
export const api: PipelineApi = configuredBase ? new HttpPipelineApi(apiBase ?? configuredBase) : new MockPipelineApi()

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
