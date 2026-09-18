<script setup lang="ts">
import { computed } from 'vue'
import { useRunsStore } from '../stores/runs'
import { useUiStore, type ArtifactTab } from '../stores/ui'
import { STAGE_META } from '../types'
import type { Artifact, StageId } from '../types'

const store = useRunsStore()
const ui = useUiStore()

const TAB_OF: Partial<Record<StageId, ArtifactTab>> = {
  intake: 'digest', understand: 'digest', article: 'article', poster: 'poster', video: 'video', publish: 'publish',
}

interface Group { stage: StageId; runId: string; runTitle: string; items: Artifact[] }

const groups = computed<Group[]>(() => {
  const out: Group[] = []
  for (const run of store.runs) {
    for (const s of run.stages) {
      if (s.artifacts.length) out.push({ stage: s.id, runId: run.id, runTitle: run.title, items: s.artifacts })
    }
  }
  return out
})

function fmtSec(v: string | number | boolean | undefined) {
  const n = Math.floor(Number(v))
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`
}

function open(g: Group, a: Artifact) {
  store.select(g.runId)
  ui.openArtifact(g.stage, a.id)
  ui.setView('workbench')
}
</script>

<template>
  <div class="page">
    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">产物库</span>
        <span class="panel-sub">跨运行汇总 · 共 {{ store.totalArtifacts }} 个产物</span>
        <div class="grow" />
        <span class="panel-sub mono">.papercast/runs/*/</span>
      </header>
    </section>

    <section v-for="g in groups" :key="g.runId + g.stage" class="panel">
      <header class="panel-head">
        <span class="panel-title">{{ STAGE_META[g.stage].label }}</span>
        <span class="chip mono">{{ STAGE_META[g.stage].engine }}</span>
        <div class="grow" />
        <span class="panel-sub ellipsis" style="max-width: 40%">{{ g.runTitle }}</span>
      </header>
      <div class="grid">
        <button v-for="a in g.items" :key="a.id" class="card" @click="open(g, a)">
          <div class="row spread">
            <strong class="ellipsis">{{ a.label }}</strong>
            <span class="chip tiny mono">{{ a.kind }}</span>
          </div>
          <div class="mono path ellipsis">{{ a.path }}</div>
          <div class="row wrap gap">
            <span v-if="a.meta?.pages" class="chip tiny">{{ a.meta.pages }} 页</span>
            <span v-if="a.meta?.words" class="chip tiny">{{ a.meta.words }} 字</span>
            <span v-if="a.meta?.slides" class="chip tiny">{{ a.meta.slides }} 页</span>
            <span v-if="a.meta?.durationSec" class="chip tiny">{{ fmtSec(a.meta.durationSec) }}</span>
            <span v-if="a.meta?.pending" class="chip tiny warn">待渲染</span>
          </div>
        </button>
      </div>
    </section>

    <div v-if="!groups.length" class="panel empty">还没有产物</div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; padding: 13px; }
.card { text-align: left; border: 1px solid var(--line-soft); border-radius: 10px; background: var(--bg-2); padding: 11px 12px; display: flex; flex-direction: column; gap: 7px; transition: 0.15s; font-size: 12.5px; }
.card:hover { border-color: var(--accent); transform: translateY(-1px); }
.path { color: var(--muted-2); font-size: 10.5px; }
.chip.tiny { font-size: 10.5px; padding: 1px 6px; }
.gap { gap: 5px; }
</style>
