import { defineStore } from 'pinia'
import { api } from '../api'
import type { EnvStatus } from '../api/types'

/**
 * 本机运行环境。
 *
 * 只做一件事：把后端 GET /api/env 的真实探测结果，翻译成**用户能看懂、能行动**的几条。
 * 界面不出现端口、库名、CLI 名这些实现细节（那些在文档里）；这里只回答
 * 「还有什么没弄好、我该去做什么」。
 */
export interface EnvRow {
  id: string
  label: string
  state: 'ok' | 'warn'
  detail: string
}

/** 演示模式（没有本机后端）下只说这是演示数据，不装成体检报告 */
export const DEMO_ROWS: EnvRow[] = [
  { id: 'demo', label: '演示模式', state: 'warn', detail: '当前用的是内置示例数据，没有连接本机后端' },
]

export const useEnvStore = defineStore('env', {
  state: () => ({
    status: null as EnvStatus | null,
    loading: false,
    error: '',
    loadedAt: 0,
  }),

  getters: {
    isDemo: () => !import.meta.env.VITE_API_BASE,

    rows(state): EnvRow[] {
      if (this.isDemo) return DEMO_ROWS
      const s = state.status
      if (!s) return []

      const rows: EnvRow[] = []
      rows.push({
        id: 'llm',
        label: '写作模型',
        state: s.llm.configured ? 'ok' : 'warn',
        detail: s.llm.configured
          ? (s.llm.model ? '使用 ' + s.llm.model : '已配置')
          : '还没填密钥：论文理解与写作会失败，在下面的「模型与 API」里填',
      })
      rows.push({
        id: 'intake',
        label: '论文解析',
        state: 'ok',
        detail: s.intake.ocr ? '本机完成，扫描件也能识别' : '本机完成，原文件不外传',
      })
      rows.push({
        id: 'cards',
        label: '图文卡片',
        state: s.cards.enabled && s.cards.cjkFontUsable ? 'ok' : 'warn',
        detail: !s.cards.enabled
          ? '已关闭，不产出卡片图'
          : s.cards.cjkFontUsable
            ? '中文字体就绪'
            : '缺中文字体，卡片上的中文会变方块',
      })
      const xhs = s.publish && s.publish.xiaohongshu
      rows.push({
        id: 'xhs',
        label: '小红书发布',
        state: xhs && xhs.reachable && xhs.loggedIn ? 'ok' : 'warn',
        detail: !xhs || !xhs.reachable
          ? '本机服务没在跑：联网投递暂不可用，素材仍会照常导出'
          : xhs.loggedIn
            ? ('已登录 ' + (xhs.account || '')).trim()
            : '未登录：到「平台账号」页扫码即可',
      })
      return rows
    },

    /** 还没弄好的条目，用来做提示文案 */
    pending(state): EnvRow[] {
      return this.rows.filter((r: EnvRow) => r.state === 'warn')
    },

    /** 全部就绪（没有可行动的待办） */
    ready(state): boolean {
      return this.rows.length > 0 && this.pending.length === 0
    },
  },

  actions: {
    async load(force = false) {
      if (this.loading) return
      if (!force && this.loadedAt && Date.now() - this.loadedAt < 15000) return
      this.loading = true
      this.error = ''
      try {
        this.status = await api.env()
        this.loadedAt = Date.now()
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e)
      } finally {
        this.loading = false
      }
    },
  },
})
