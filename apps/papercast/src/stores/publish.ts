/**
 * 作品库直投：**一件作品 → 一个渠道 → 一次人工确认**。
 *
 * 为什么单独一个 store：这条路径不经过流水线闸门（那条路只有运行正停在 publish 阶段的
 * `waiting` 时才能用，见 components/viewers/PublishViewer.vue）。规则集中写在这里：
 *
 * 1. 真投递前必须过 `ui.askConfirm()` —— 默认动作排第一、按钮是动词、说清账号与不可逆；
 * 2. 「仅存草稿」走后端 `confirmed=false`：只落 export/，一个发布接口都不调；
 * 3. 四种结果（发出了 / 投不了 / 失败了 / 存了草稿）都有回执（气泡 + 面板内回执卡），
 *    不许「点了没反应」；
 * 4. 文案一律用后端拣好的那一份：**前端不挑变体**（渠道 → 变体的规则只存在于后端一处），
 *    界面只允许改标题/正文/标签，改完由后端重新过平台规则。
 */

import { defineStore } from 'pinia'
import { api } from '../api'
import { useRunsStore } from './runs'
import { useUiStore } from './ui'
import type { RunDraft, RunDrafts, RunPublishResult } from '../types'

/** 一个渠道上界面改过的字段；只送非空项，后端没收到就用自己的那份 */
export interface DraftEdit {
  title?: string
  content?: string
  tags?: string
}

/** 渠道别名：作品库传过来的可能是作品归属平台（xhs），草稿里的 id 也是规范 id，两边都要认 */
function sameChannel(a: string, b: string): boolean {
  const norm = (x: string) => {
    const k = (x ?? '').trim().toLowerCase()
    if (k === 'xiaohongshu' || k === 'redbook') return 'xhs'
    if (k === 'bili') return 'bilibili'
    if (k === 'twitter' || k === 'x-com' || k === 'en') return 'x'
    return k
  }
  return norm(a) === norm(b)
}

/**
 * 选出当前该看的那份草稿。**纯函数**：Pinia options store 的 getter 之间互相 `this.draft`
 * 拿不到类型（本仓库其它 store 也没有先例），所以跨 getter 的复用都走这个函数。
 */
function pickDraft(data: RunDrafts | null, channelId: string): RunDraft | null {
  if (!data || !data.channels.length) return null
  return data.channels.find((c) => sameChannel(c.channelId, channelId)) ?? data.channels[0]
}

/** 界面上的文案：改过就用改过的，没改过用后端拣好的那一份 */
function textOf(state: { data: RunDrafts | null; channelId: string; edits: Record<string, DraftEdit> }) {
  const d = pickDraft(state.data, state.channelId)
  const edit = (d && state.edits[d.channelId]) || {}
  return {
    title: edit.title ?? d?.title ?? '',
    content: edit.content ?? d?.body ?? '',
    tags: (edit.tags ?? (d?.tags ?? []).join(' ')).trim(),
  }
}

export const usePublishStore = defineStore('publish', {
  state: () => ({
    /** 面板是否打开 */
    open: false,
    runId: '',
    runTitle: '',
    /** 当前选中的渠道（原始写法，可能是 'xhs'） */
    channelId: '',
    data: null as RunDrafts | null,
    loading: false,
    error: '',
    /** '' | 'draft' | 'publish' —— 正在做什么，用来禁按钮 */
    busy: '' as '' | 'draft' | 'publish',
    /** 最近一次调用的回执（真投递、落草稿都记） */
    result: null as RunPublishResult | null,
    /** 界面改过的文案，按渠道存：切来切去不会把编辑丢掉 */
    edits: {} as Record<string, DraftEdit>,
  }),

  getters: {
    /** 当前渠道的草稿 */
    draft(state): RunDraft | null {
      return pickDraft(state.data, state.channelId)
    },
    /** 当前渠道界面上的文案（改过就用改过的） */
    text(state) {
      return textOf(state)
    },
    /** 这个渠道现在真的能投吗（后端判的 ready + suitable，前端不自己下结论） */
    canPublish(state): boolean {
      const d = pickDraft(state.data, state.channelId)
      return Boolean(d && d.hasDraft && d.suitable && d.ready)
    },
    /** 投不了的说明：优先说后端的原话 */
    blockedReason(state): string {
      const d = pickDraft(state.data, state.channelId)
      if (!d) return ''
      if (!d.hasDraft) return d.reason || '这个渠道拿不到可投的文案'
      if (!d.suitable) return d.reason
      if (!d.ready) return d.reason || d.detail || '渠道还没就绪'
      return ''
    },
    /** 这条运行是不是已经投过一遍了（后端从成片回执里查出来的） */
    previous(state) {
      return state.data?.previous ?? null
    },
  },

  actions: {
    /** 打开面板：带上这条运行与想投的渠道（渠道来自作品库那一件作品的平台） */
    async openFor(runId: string, runTitle: string, channelId = '') {
      this.open = true
      this.runId = runId
      this.runTitle = runTitle
      this.channelId = channelId
      this.result = null
      this.error = ''
      this.data = null
      await this.load()
    },

    close() {
      this.open = false
      this.busy = ''
      this.result = null
      this.error = ''
      // 下次打开重新读：期间渠道可能登录了、产物可能变了
      this.data = null
    },

    /** 读逐渠道草稿（真产物 + 真登录态）。读不到就说读不到，不编。 */
    async load() {
      if (!this.runId) return
      this.loading = true
      this.error = ''
      try {
        const data = await api.listRunDrafts(this.runId)
        // 选中的渠道后端不认识（例如作品库传了 'xiaohongshu' 而规范 id 是 'xhs'）→ 落到真实的那一个
        const picked = pickDraft(data, this.channelId)
        this.channelId = picked?.channelId ?? ''
        this.data = data
      } catch (e) {
        this.error = (e as Error).message
        this.data = null
      } finally {
        this.loading = false
      }
    },

    select(channelId: string) {
      this.channelId = channelId
      this.result = null
    },

    /** 改文案：只存起来，发出时一起带上（改动是否合规由后端再判一次） */
    edit(field: 'title' | 'content' | 'tags', value: string) {
      const d = pickDraft(this.data, this.channelId)
      if (!d) return
      const cur = this.edits[d.channelId] ?? {}
      this.edits[d.channelId] = { ...cur, [field]: value }
    },

    resetEdit() {
      const d = pickDraft(this.data, this.channelId)
      if (d) delete this.edits[d.channelId]
    },

    /** 有改动才带 overrides；标签用空格/逗号分隔，去掉前导 # */
    overrides(): { title?: string; content?: string; tags?: string[] } {
      const d = pickDraft(this.data, this.channelId)
      if (!d) return {}
      const t = textOf(this)
      const out: { title?: string; content?: string; tags?: string[] } = {}
      if (t.title.trim() && t.title.trim() !== (d.title ?? '').trim()) out.title = t.title.trim()
      if (t.content.trim() && t.content.trim() !== (d.body ?? '').trim()) out.content = t.content.trim()
      const tags = t.tags.split(/[\s,，]+/).map((x: string) => x.replace(/^#/, '').trim()).filter(Boolean)
      if (tags.join(' ') !== (d.tags ?? []).join(' ')) out.tags = tags
      return out
    },

    /** 仅存草稿：无副作用，后端只落 export/ */
    async saveDraft() {
      const d = pickDraft(this.data, this.channelId)
      if (!d || this.busy) return
      const ui = useUiStore()
      this.busy = 'draft'
      this.error = ''
      try {
        const res = await api.publishRunWork(this.runId, {
          channelId: d.channelId, confirmed: false, ...this.overrides(),
        })
        this.result = res
        const n = res.files?.length ?? 0
        ui.toast(n
          ? `${d.name}的素材包已存好：${n} 个文件，没有调用任何发布接口`
          : `${d.name}的素材包已存好（后端没回报文件清单）`, 'info')
      } catch (e) {
        this.error = (e as Error).message
        ui.toast(`存草稿失败：${this.error}`, 'err')
      } finally {
        this.busy = ''
      }
    },

    /** 真投递：**不可逆**，所以先过人工确认，再带 confirmed=true 调后端 */
    async deliver() {
      const d = pickDraft(this.data, this.channelId)
      if (!d || this.busy) return
      const ui = useUiStore()
      const runs = useRunsStore()

      const who = d.account ? `当前账号：${d.account}。` : ''
      const prev = this.data?.previous
      const again = prev
        ? `注意：这条运行已经投过一次（${prev.bvid || prev.url || '未知稿件'}），再发一次会重复投递。`
        : ''
      const ok = await ui.askConfirm({
        title: `把这篇作品发到${d.name}？`,
        text: `${who}发出后不可撤销，${d.name}上会立刻公开可见。${again}`,
        okLabel: '确认发布',
        cancelLabel: '再想想',
        tone: 'warn',
      })
      if (!ok) return

      this.busy = 'publish'
      this.error = ''
      try {
        const res = await api.publishRunWork(this.runId, {
          channelId: d.channelId,
          confirmed: true,
          confirmAccount: d.account || undefined,
          ...this.overrides(),
        })
        this.result = res
        this.report(res, d.name)
        // 回执要落进作品库：刷新运行记录（后端已把回执并进总表并登记成产物）
        await runs.refresh(true)
      } catch (e) {
        this.error = (e as Error).message
        ui.toast(`没发出去：${this.error}`, 'err')
      } finally {
        this.busy = ''
      }
    },

    /** 把后端的结果原样说给人听：成功给链接，失败给原因，别让人猜 */
    report(res: RunPublishResult, name: string) {
      const ui = useUiStore()
      const where = res.url || res.remoteId
      if (res.status === 'published') {
        ui.toast(where ? `已发到${name}：${where}` : `已提交到${name}（后端没返回链接）`, 'info', 9000)
      } else if (res.status === 'draft') {
        ui.toast(`${name}：只存了草稿，没有调用发布接口`, 'info')
      } else if (res.status === 'blocked') {
        ui.toast(`${name}投不了：${res.error?.message || '渠道没就绪'}`, 'warn', 9000)
      } else {
        ui.toast(`${name}投递失败：${res.error?.message || '原因不明'}（素材包仍在本地）`, 'err', 9000)
      }
      for (const w of res.warnings ?? []) ui.toast(w, 'warn', 9000)
    },
  },
})
