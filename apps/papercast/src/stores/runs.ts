import { defineStore } from 'pinia'
import { api } from '../api'
import { useUiStore } from './ui'
import type { PaperRun, RunConfig, SourceInput, StageId } from '../types'

const POLL_MS = 400

/** 只在这些状态下轮询，避免空转 */
const LIVE = new Set(['queued', 'running', 'waiting'])

function signature(r: PaperRun) {
  return r.status + '|' + r.stages.map((s) => `${s.id}:${s.status}:${Math.round(s.progress)}:${s.logs.length}`).join(',')
}

export const useRunsStore = defineStore('runs', {
  state: () => ({
    runs: [] as PaperRun[],
    activeId: null as string | null,
    busy: false,
    error: '',
    /** 演示模式：闸门不阻塞，自动放行 */
    autoConfirm: false,
    apiLabel: api.label,
    _poll: undefined as number | undefined,
    _sigs: {} as Record<string, string>,
    _autoDone: {} as Record<string, boolean>,
  }),

  getters: {
    active(state): PaperRun | undefined {
      return state.runs.find((r) => r.id === state.activeId)
    },
    liveRun(state): PaperRun | undefined {
      return state.runs.find((r) => LIVE.has(r.status))
    },
    totalArtifacts(state): number {
      return state.runs.reduce((n, r) => n + r.stages.reduce((m, s) => m + s.artifacts.length, 0), 0)
    },
  },

  actions: {
    async bootstrap() {
      try {
        this.runs = await api.listRuns()
        this.activeId = this.runs[0]?.id ?? null
        this.syncSignatures()
        this.ensurePolling()
      } catch (e) {
        this.error = (e as Error).message
      }
    },

    syncSignatures() {
      this._sigs = Object.fromEntries(this.runs.map((r) => [r.id, signature(r)]))
    },

    async submit(source: SourceInput, config: RunConfig) {
      this.busy = true
      this.error = ''
      try {
        const run = await api.createRun({ source, config })
        this.runs.unshift(run)
        this.activeId = run.id
        this._sigs[run.id] = signature(run)
        this.ensurePolling()
        return run
      } catch (e) {
        this.error = (e as Error).message
        return undefined
      } finally {
        this.busy = false
      }
    },

    select(id: string) {
      this.activeId = id
    },

    /**
     * 人工闸门：确认或打回。返回是否真的成功。
     *
     * 这里**必须自己接住失败**（落单待认领·①）：后端在「重启后没有活跃任务」时返 409，
     * 而调用点（阶段卡 / 对话里的闸门提问 / 发布页三个按钮）全都没有 try/catch ——
     * 失败会变成无人接的 promise rejection：用户点了放行，界面永远停在「等待放行」且一句解释都没有。
     * 所以：失败 → toast 出原因 + 拉一次真实状态 + 返回 false（**不抛**，免得又造出无人接的 rejection）。
     */
    async confirm(stageId: StageId, optionId: string): Promise<boolean> {
      const run = this.active
      if (!run) return false
      try {
        await api.resolveGate(run.id, stageId, optionId)
      } catch (e) {
        useUiStore().toast('这一步没放行成功：' + (e as Error).message + '（多半是服务重启后这次运行已不在等它了，重新发起一次即可）', 'err')
        await this.refresh(true)
        return false
      }
      await this.refresh(true)
      return true
    },

    async cancel(): Promise<boolean> {
      const run = this.active
      if (!run) return false
      try {
        await api.cancelRun(run.id)
      } catch (e) {
        useUiStore().toast('没停掉：' + (e as Error).message, 'err')
        await this.refresh(true)
        return false
      }
      await this.refresh(true)
      return true
    },

    async refresh(force = false) {
      const id = this.activeId
      if (!id) return
      const fresh = await api.getRun(id)
      if (!fresh) return
      const sig = signature(fresh)
      const idx = this.runs.findIndex((r) => r.id === id)
      if (force || this._sigs[id] !== sig) {
        this._sigs[id] = sig
        if (idx >= 0) this.runs.splice(idx, 1, fresh)
      }
      // 演示模式：自动放行闸门
      if (this.autoConfirm) {
        for (const s of fresh.stages) {
          if (s.status === 'waiting' && s.gate && !s.gate.resolved) {
            const key = `${fresh.id}:${s.id}`
            if (!this._autoDone[key]) {
              this._autoDone[key] = true
              window.setTimeout(() => {
                // 409（重启后没人等）要复位标记，否则演示模式会永远不再重试且毫无提示
                void api
                  .resolveGate(fresh.id, s.id, s.gate!.options[0]!.id)
                  .then(() => this.refresh(true))
                  .catch(() => {
                    this._autoDone[key] = false
                  })
              }, 900)
            }
          }
        }
      }
      if (!fresh || !LIVE.has(fresh.status)) this.stopPollingIfIdle()
    },

    stopPollingIfIdle() {
      const anyLive = this.runs.some((r) => LIVE.has(r.status))
      if (!anyLive) this.stopPolling()
    },

    ensurePolling() {
      const anyLive = this.runs.some((r) => LIVE.has(r.status))
      if (!anyLive || this._poll !== undefined) return
      this._poll = window.setInterval(() => void this.refresh(), POLL_MS)
    },

    stopPolling() {
      if (this._poll !== undefined) window.clearInterval(this._poll)
      this._poll = undefined
    },
  },
})
