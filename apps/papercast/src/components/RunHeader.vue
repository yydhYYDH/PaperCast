<script setup lang="ts">
import { computed } from 'vue'
import type { PaperRun } from '../types'
import { RUN_STATUS, fmtAgo, fmtDuration } from '../utils'

const props = defineProps<{ run: PaperRun }>()
const emit = defineEmits<{ (e: 'cancel'): void }>()

const st = computed(() => RUN_STATUS[props.run.status])
const done = computed(() => props.run.stages.filter((s) => s.status === 'done').length)
const overall = computed(() =>
  Math.round(props.run.stages.reduce((n, s) => n + (s.status === 'skipped' ? 100 : s.progress), 0) / props.run.stages.length),
)
const elapsed = computed(() => {
  const started = props.run.stages.find((s) => s.startedAt)?.startedAt ?? props.run.createdAt
  const ended = props.run.status === 'done' || props.run.status === 'failed' ? Date.now() : Date.now()
  return fmtDuration(Math.max(0, ended - started))
})
const live = computed(() => props.run.status === 'running' || props.run.status === 'waiting' || props.run.status === 'queued')
</script>

<template>
  <section class="panel head-card">
    <div class="panel-body">
      <div class="row spread">
        <div class="grow">
          <div class="row wrap gap">
            <span class="chip" :class="st.cls"><i class="dot" />{{ st.label }}</span>
            <span class="chip mono">{{ run.source.kind === 'arxiv' ? `arXiv:${run.source.value}` : run.source.kind === 'pdf' ? 'PDF' : 'LaTeX' }}</span>
            <span v-if="run.source.venue" class="chip">{{ run.source.venue }}</span>
            <span class="muted mono">{{ fmtAgo(run.createdAt) }} 提交 · 已用 {{ elapsed }}</span>
          </div>
          <h2 class="title">{{ run.title }}</h2>
        </div>
        <div class="row">
          <button v-if="live" class="btn danger sm" @click="emit('cancel')">停止</button>
        </div>
      </div>

      <div class="row spread mt">
        <span class="label">整体进度 {{ done }} / {{ run.stages.length }} 阶段</span>
        <span class="mono muted">{{ overall }}%</span>
      </div>
      <div class="bar mt6"><i :style="{ width: overall + '%' }" /></div>
    </div>
  </section>
</template>

<style scoped>
.head-card { background: linear-gradient(180deg, #fbfcff, var(--panel)); }
.title { font-size: 15.5px; margin-top: 8px; line-height: 1.45; }
.gap { gap: 6px; }
.mt { margin-top: 14px; }
.mt6 { margin-top: 6px; }
</style>
