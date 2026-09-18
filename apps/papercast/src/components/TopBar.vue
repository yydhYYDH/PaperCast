<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ENV_DEPS } from '../data/env'
import { useRunsStore } from '../stores/runs'
import { usePlatformsStore } from '../stores/platforms'
import { useUiStore } from '../stores/ui'
import { PLATFORM_STATE } from '../utils'
import type { ViewId } from '../types'

const store = useRunsStore()
const ui = useUiStore()
const platforms = usePlatformsStore()

const TITLES: Record<ViewId, string> = {
  workbench: '工作台',
  runs: '运行历史',
  library: '产物库',
  platforms: '平台账号',
  settings: '引擎与环境',
}

const ok = computed(() => ENV_DEPS.filter((d) => d.state === 'ok').length)

/** 小红书是唯一有真实登录入口的渠道：状态直接顶到顶栏，没登录时点一下就能扫码 */
const xhs = computed(() => platforms.channel('xhs'))
/** 首次探测要开一次无头浏览器（3–20 秒），这期间也得给个能点的入口，否则顶栏像坏了 */
const probing = computed(() => !xhs.value && !platforms.refreshedAt)

onMounted(() => {
  if (!platforms.channels.length) void platforms.refresh(false)
})
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

    <button
      v-if="probing"
      class="chip login-chip"
      title="正在探测各平台登录态（首次约 3–20 秒）；点进去可看每个渠道的状态与登录入口"
      @click="ui.setView('platforms')"
    >
      <i class="dot" />
      平台账号 · {{ platforms.loading ? '探测中…' : '待探测' }}
      <span class="arrow">→</span>
    </button>

    <button
      v-else-if="xhs"
      class="chip login-chip"
      :class="PLATFORM_STATE[xhs.state].cls"
      :title="xhs.state === 'ready' ? `小红书已登录：${xhs.account || '未知账号'}（点击管理）` : `${xhs.detail}（点击登录）`"
      @click="ui.setView('platforms')"
    >
      <i class="dot" />
      小红书 {{ xhs.state === 'ready' ? (xhs.account || '已登录') : PLATFORM_STATE[xhs.state].label }}
      <span class="arrow">→</span>
    </button>

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
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: saturate(180%) blur(10px);
}
.brand { font-size: 14.5px; letter-spacing: -0.01em; }
.cur { font-size: 13px; color: var(--text-2); }
.gap { gap: 8px; }
.demo { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.demo input { accent-color: var(--accent); }
.login-chip { cursor: pointer; transition: 0.15s; }
.login-chip:hover { border-color: var(--accent); color: var(--text); }
.login-chip .arrow { color: var(--muted-2); }
@media (max-width: 1280px) { .hide-sm { display: none; } }
</style>