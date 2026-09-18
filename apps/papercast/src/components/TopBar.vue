<script setup lang="ts">
import { computed } from 'vue'
import { ENV_DEPS } from '../data/env'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'
import type { ViewId } from '../types'

const store = useRunsStore()
const ui = useUiStore()

const TITLES: Record<ViewId, string> = {
  workbench: '工作台',
  runs: '运行历史',
  library: '产物库',
  settings: '引擎与环境',
}

const ok = computed(() => ENV_DEPS.filter((d) => d.state === 'ok').length)
</script>

<template>
  <header class="top">
    <div class="row gap">
      <strong class="brand">PaperCast</strong>
      <span class="muted-2">/</span>
      <span class="cur">{{ TITLES[ui.view] }}</span>
      <span class="panel-sub hide-sm">论文 → 文章 · Poster · 视频</span>
    </div>

    <div class="grow" />

    <label class="demo" :title="store.autoConfirm ? '闸门自动放行' : '闸门需人工确认'">
      <input v-model="store.autoConfirm" type="checkbox" />
      <span>演示模式</span>
    </label>
    <span class="chip" :class="ok === ENV_DEPS.length ? 'ok' : 'warn'">
      <i class="dot" />依赖 {{ ok }}/{{ ENV_DEPS.length }}
    </span>
    <span class="chip mono" :title="store.apiLabel">
      {{ store.apiLabel.includes('mock') ? 'mock adapter' : 'http adapter' }}
    </span>
  </header>
</template>

<style scoped>
.top {
  display: flex; align-items: center; gap: 10px;
  padding: 11px 16px 11px 18px;
  border-bottom: 1px solid var(--line-soft);
  background: linear-gradient(180deg, rgba(19, 26, 40, 0.9), rgba(10, 13, 19, 0.6));
  backdrop-filter: blur(6px);
}
.brand { font-size: 14.5px; letter-spacing: -0.01em; }
.cur { font-size: 13px; color: var(--text-2); }
.gap { gap: 8px; }
.demo { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.demo input { accent-color: var(--accent); }
@media (max-width: 1280px) { .hide-sm { display: none; } }
</style>
