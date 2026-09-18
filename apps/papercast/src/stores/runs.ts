import { defineStore } from 'pinia'
import { api } from '../api'
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

    async confirm(stageId: StageId, optionId: string) {
      const run = this.active
      if (!run) return
      await api.resolveGate(run.id, stageId, optionId)
      await this.refresh(true)
    },

    async cancel() {
      const run = this.active
      if (!run) return
      await api.cancelRun(run.id)
      await this.refresh(true)
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
                void api.resolveGate(fresh.id, s.id, s.gate!.options[0]!.id).then(() => this.refresh(true))
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
