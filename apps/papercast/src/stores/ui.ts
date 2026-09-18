import { defineStore } from 'pinia'
import type { StageId, ViewId } from '../types'

export type ArtifactTab = 'digest' | 'article' | 'poster' | 'video' | 'publish'

const FROM_STAGE: Partial<Record<StageId, ArtifactTab>> = {
  intake: 'digest',
  understand: 'digest',
  article: 'article',
  poster: 'poster',
  video: 'video',
  publish: 'publish',
}

export type ToastTone = 'info' | 'warn' | 'err'

export interface Toast {
  id: number
  text: string
  tone: ToastTone
}

export interface AskOptions {
  title: string
  text?: string
  okLabel?: string
  cancelLabel?: string
  tone?: ToastTone
}

let toastSeq = 0
let askSeq = 0

export const useUiStore = defineStore('ui', {
  state: () => ({
    view: 'workbench' as ViewId,
    tab: 'digest' as ArtifactTab,
    selectedArtifactId: '' as string,
    expanded: {} as Record<string, boolean>,
    toasts: [] as Toast[],
    ask: null as (AskOptions & { id: number }) | null,
    _resolveAsk: null as null | ((ok: boolean) => void),
  }),
  actions: {
    setView(view: ViewId) {
      this.view = view
    },

    /** 一句话回执（右下角气泡）：任何「点了之后发生了什么」都应该走这里 */
    toast(text: string, tone: ToastTone = 'info', ms = 6000) {
      const id = ++toastSeq
      this.toasts.push({ id, text, tone })
      window.setTimeout(() => this.dismissToast(id), ms)
    },
    dismissToast(id: number) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },

    /** 应用内确认框（替代 window.confirm，样式统一、可读性更好） */
    askConfirm(opts: AskOptions): Promise<boolean> {
      return new Promise((resolve) => {
        this._resolveAsk = resolve
        this.ask = { ...opts, id: ++askSeq }
      })
    },
    answerAsk(ok: boolean) {
      this.ask = null
      const fn = this._resolveAsk
      this._resolveAsk = null
      fn?.(ok)
    },
    openTab(tab: ArtifactTab) {
      this.tab = tab
    },
    /** 点击阶段卡片里的产物 → 打开对应预览 */
    openArtifact(stageId: StageId, artifactId: string) {
      this.tab = FROM_STAGE[stageId] ?? this.tab
      this.selectedArtifactId = artifactId
    },
    toggle(key: string, fallback = false) {
      this.expanded[key] = !(this.expanded[key] ?? fallback)
    },
    isOpen(key: string, fallback = false) {
      return this.expanded[key] ?? fallback
    },
  },
})
