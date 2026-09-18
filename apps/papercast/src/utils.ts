import type { PlatformState, RunStatus, StageStatus } from './types'

export function fmtBytes(n?: number) {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1048576).toFixed(2)} MB`
}

export function fmtDuration(ms: number) {
  if (ms < 1000) return '0s'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

export function fmtClock(ts: number) {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

export function fmtAgo(ts: number) {
  const s = Math.round((Date.now() - ts) / 1000)
  if (s < 60) return `${s} 秒前`
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`
  return `${Math.floor(s / 86400)} 天前`
}

export const RUN_STATUS: Record<RunStatus, { label: string; cls: string }> = {
  queued: { label: '排队中', cls: 'warn' },
  running: { label: '运行中', cls: 'accent' },
  waiting: { label: '待确认', cls: 'warn' },
  done: { label: '已完成', cls: 'ok' },
  failed: { label: '失败', cls: 'err' },
}

export const STAGE_STATUS: Record<StageStatus, { label: string; cls: string }> = {
  pending: { label: '等待', cls: '' },
  running: { label: '进行中', cls: 'accent' },
  waiting: { label: '待确认', cls: 'warn' },
  done: { label: '完成', cls: 'ok' },
  failed: { label: '失败', cls: 'err' },
  skipped: { label: '跳过', cls: '' },
}

/** 平台渠道登录态 → chip 文案与配色 */
export const PLATFORM_STATE: Record<PlatformState, { label: string; cls: string }> = {
  ready: { label: '已登录', cls: 'ok' },
  login_required: { label: '需扫码登录', cls: 'warn' },
  offline: { label: '服务离线', cls: 'err' },
  unconfigured: { label: '未配置', cls: '' },
  blocked: { label: '受限', cls: 'warn' },
}

/* 各阶段复用了哪些开源实现，只写在 docs/research/upstream-repos.md 里，不在界面上出现。 */
