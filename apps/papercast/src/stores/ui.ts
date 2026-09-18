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

export const useUiStore = defineStore('ui', {
  state: () => ({
    view: 'workbench' as ViewId,
    tab: 'digest' as ArtifactTab,
    selectedArtifactId: '' as string,
    expanded: {} as Record<string, boolean>,
  }),
  actions: {
    setView(view: ViewId) {
      this.view = view
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
