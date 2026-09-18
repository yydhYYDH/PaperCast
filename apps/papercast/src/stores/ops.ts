import { defineStore } from 'pinia'
import { api } from '../api'
import type { OpsLog, OpsMetrics, OpsService } from '../types'

/**
 * 运营维护：本机服务状态（起停 / 日志）与「发出去的内容现在怎么样了」的运营数据。
 *
 * 与 platforms store 的分工：那边回答「账号能不能投」，这边回答「投出去之后效果如何、机器还健康吗」。
 * 所有数字都来自真实探测，取不到的渠道用 gap 字段如实说明，不编。
 */
export const useOpsStore = defineStore('ops', {
  state: () => ({
    services: [] as OpsService[],
    metrics: null as OpsMetrics | null,
    log: null as OpsLog | null,
    logName: 'backend',
    logLines: 200,
    grep: '',
    autoLog: true,
    loading: false,
    metricsLoading: false,
    acting: '',
    error: '',
    fetchedAt: 0,
    _timer: undefined as number | undefined,
  }),

  getters: {
    downCount(state) {
      return state.services.filter((s) => !s.up).length
    },
    upCount(state) {
      return state.services.filter((s) => s.up).length
    },
    /** 数据看板里的汇总卡片：每渠道一行关键指标 */
    summary(state) {
      const out: { id: string; name: string; metrics: { k: string; v: string }[]; note: string }[] = []
      for (const ch of state.metrics?.channels ?? []) {
        const t = ch.totals || {}
        const metrics: { k: string; v: string }[] = []
        const fmt = (v: unknown) => (typeof v === 'number' ? String(v) : '—')
        if (ch.id === 'bilibili') {
          metrics.push({ k: '播放', v: fmt(t.view) }, { k: '点赞', v: fmt(t.like) },
            { k: '投币', v: fmt(t.coin) }, { k: '收藏', v: fmt(t.favorite) },
            { k: '评论', v: fmt(t.reply) })
        } else if (ch.id === 'zhihu') {
          metrics.push({ k: '赞同', v: fmt(t.like) }, { k: '评论', v: fmt(t.reply) })
        } else if (ch.account) {
          const raw = ch.account.raw || {}
          const pick = (...keys: string[]) => {
            for (const key of keys) if (typeof raw[key] === 'number') return String(raw[key])
            return '—'
          }
          metrics.push({ k: '粉丝', v: pick('fans', 'fansCount', 'fans_count') },
            { k: '获赞', v: pick('liked', 'likedCount', 'liked_count', 'likes') },
            { k: '收藏', v: pick('collected', 'collectedCount', 'collected_count') })
        }
        out.push({ id: ch.id, name: ch.name, metrics, note: ch.gap })
      }
      return out
    },
  },

  actions: {
    async refreshServices(silent = false) {
      if (!silent) this.loading = true
      this.error = ''
      try {
        this.services = await api.opsServices()
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.loading = false
      }
    },

    async loadMetrics(force = false) {
      this.metricsLoading = true
      this.error = ''
      try {
        this.metrics = await api.opsMetrics(force)
        this.fetchedAt = Date.now()
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.metricsLoading = false
      }
    },

    async loadLog(name?: string, opts: { lines?: number; grep?: string; silent?: boolean } = {}) {
      if (name) this.logName = name
      if (opts.lines) this.logLines = opts.lines
      if (opts.grep !== undefined) this.grep = opts.grep
      try {
        this.log = await api.opsLogs(this.logName, this.logLines, this.grep)
      } catch (e) {
        // 日志读不到（服务从没起过）不该把整页搞红，单独记在 error 里
        this.error = (e as Error).message
      }
    },

    async act(name: string, action: 'start' | 'stop' | 'restart') {
      this.acting = name + ':' + action
      this.error = ''
      try {
        const res = await api.opsServiceAction(name, action)
        await this.refreshServices(true)
        await this.loadLog(name, { silent: true })
        return res
      } catch (e) {
        this.error = (e as Error).message
        return null
      } finally {
        this.acting = ''
      }
    },

    startLogPolling() {
      this.stopLogPolling()
      this._timer = window.setInterval(() => {
        if (this.autoLog) void this.loadLog(undefined, { silent: true })
      }, 4000)
    },

    stopLogPolling() {
      if (this._timer !== undefined) window.clearInterval(this._timer)
      this._timer = undefined
    },
  },
})
