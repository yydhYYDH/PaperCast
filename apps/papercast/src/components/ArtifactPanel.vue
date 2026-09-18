<script setup lang="ts">
import { computed } from 'vue'
import type { PaperRun } from '../types'
import { useUiStore } from '../stores/ui'
import { STAGE_META } from '../types'
import DigestViewer from './viewers/DigestViewer.vue'
import ArticleViewer from './viewers/ArticleViewer.vue'
import PosterViewer from './viewers/PosterViewer.vue'
import VideoViewer from './viewers/VideoViewer.vue'
import PublishViewer from './viewers/PublishViewer.vue'

const props = defineProps<{ run: PaperRun }>()
const ui = useUiStore()

const TABS = [
  { id: 'digest', label: '论文理解层', stage: 'understand' },
  { id: 'article', label: '文章', stage: 'article' },
  { id: 'poster', label: 'Poster', stage: 'poster' },
  { id: 'video', label: '视频', stage: 'video' },
  { id: 'publish', label: '发布', stage: 'publish' },
] as const

const counts = computed(() =>
  Object.fromEntries(
    TABS.map((t) => [t.id, props.run.stages.find((s) => s.id === t.stage)?.artifacts.length ?? 0]),
  ) as Record<string, number>,
)
</script>

<template>
  <section class="panel viewer">
    <header class="panel-head tabs-head">
      <div class="tabbar">
        <button
          v-for="t in TABS"
          :key="t.id"
          :class="{ on: ui.tab === t.id }"
          @click="ui.openTab(t.id)"
        >
          {{ t.label }}
          <span v-if="counts[t.id]" class="cnt mono">{{ counts[t.id] }}</span>
        </button>
      </div>
    </header>

    <div class="viewer-body">
      <DigestViewer v-if="ui.tab === 'digest'" />
      <ArticleViewer v-else-if="ui.tab === 'article'" :run="run" />
      <PosterViewer v-else-if="ui.tab === 'poster'" :run="run" />
      <VideoViewer v-else-if="ui.tab === 'video'" :run="run" />
      <PublishViewer v-else :run="run" />
    </div>

    <footer class="viewer-foot mono">
      <span class="muted-2">引擎</span>
      <span class="grow ellipsis">{{ STAGE_META[TABS.find((t) => t.id === ui.tab)!.stage].engine }}</span>
      <span class="muted-2">产物根目录</span>
      <span>.papercast/runs/{{ run.id.slice(0, 10) }}/</span>
    </footer>
  </section>
</template>

<style scoped>
.viewer { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.tabs-head { padding: 0 8px; }
.cnt { margin-left: 5px; font-size: 10px; color: var(--muted-2); background: var(--panel-3); padding: 0 4px; border-radius: 5px; }
.viewer-body { flex: 1; min-height: 0; overflow: hidden; }
.viewer-foot { display: flex; align-items: center; gap: 8px; padding: 7px 12px; border-top: 1px solid var(--line-soft); font-size: 11px; color: var(--muted); }
</style>
