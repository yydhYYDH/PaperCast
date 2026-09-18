<script setup lang="ts">
import { computed } from 'vue'
import { useRunsStore } from '../stores/runs'
import { RUN_STATUS, fmtAgo } from '../utils'

const store = useRunsStore()
const runs = computed(() => store.runs)
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">运行历史</span>
      <div class="grow" />
      <span class="panel-sub">{{ runs.length }} 条</span>
    </header>
    <div class="list">
      <button
        v-for="r in runs"
        :key="r.id"
        class="item"
        :class="{ on: r.id === store.activeId }"
        @click="store.select(r.id)"
      >
        <span class="dot" :class="RUN_STATUS[r.status].cls" />
        <div class="grow">
          <div class="t ellipsis">{{ r.title }}</div>
          <div class="row wrap meta">
            <span class="mono">{{ fmtAgo(r.createdAt) }}</span>
            <span class="muted-2">·</span>
            <span>{{ RUN_STATUS[r.status].label }}</span>
            <span class="muted-2">·</span>
            <span>{{ r.stages.filter((s) => s.status === 'done').length }}/{{ r.stages.length }} 阶段</span>
            <span class="muted-2">·</span>
            <span>{{ r.stages.reduce((n, s) => n + s.artifacts.length, 0) }} 产物</span>
          </div>
          <div v-if="r.status === 'running' || r.status === 'waiting'" class="bar mini">
            <i :style="{ width: r.stages.reduce((n, s) => n + s.progress, 0) / r.stages.length + '%' }" />
          </div>
        </div>
      </button>
      <div v-if="!runs.length" class="empty">还没有运行记录</div>
    </div>
  </section>
</template>

<style scoped>
.list { display: flex; flex-direction: column; padding: 6px; gap: 3px; max-height: 300px; overflow-y: auto; }
.item { display: flex; gap: 9px; align-items: flex-start; text-align: left; padding: 9px 10px; border-radius: 9px; border: 1px solid transparent; transition: 0.15s; }
.item:hover { background: rgba(255, 255, 255, 0.025); }
.item.on { background: var(--accent-soft); border-color: rgba(90, 162, 255, 0.28); }
.dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 7px; flex: none; background: var(--muted-2); }
.dot.ok { background: var(--ok); }
.dot.err { background: var(--err); }
.dot.warn { background: var(--warn); }
.dot.accent { background: var(--accent); animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.3; } }
.t { font-size: 12.5px; color: var(--text); line-height: 1.5; }
.meta { gap: 4px; font-size: 11px; color: var(--muted); margin-top: 3px; }
.bar.mini { height: 2px; margin-top: 6px; }
</style>
