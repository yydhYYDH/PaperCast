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
  runs: '运行记录',
  library: '作品库',
  platforms: '平台账号',
  ops: '运营维护',
  settings: '设置',
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
      <span class="sep" />
      <span class="cur">{{ TITLES[ui.view] }}</span>
      <span class="panel-sub hide-sm">把一篇论文变成大家看得懂的内容</span>
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
      {{ platforms.loading ? '正在检查登录状态…' : '查看平台登录状态' }}
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
    </button>

    <span class="chip" :class="ok === ENV_DEPS.length ? 'ok' : 'warn'" title="本机依赖项的就绪数量">
      <i class="dot" />环境 {{ ok }}/{{ ENV_DEPS.length }}
    </span>
  </header>
</template>

<style scoped>
.top {
  display: flex; align-items: center; gap: 12px;
  padding: 15px 26px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: saturate(180%) blur(8px);
}
.brand { font-family: var(--serif); font-size: 16px; font-weight: 500; color: var(--text); letter-spacing: -0.01em; }
.sep { width: 1px; height: 15px; background: var(--line); }
.cur { font-size: 13px; color: var(--text-2); }
.gap { gap: 8px; }
.demo { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
.demo input { accent-color: var(--text); }
.login-chip { cursor: pointer; transition: 0.15s; }
.login-chip:hover { border-color: #dcdbd6; color: var(--text); }
@media (max-width: 1280px) { .hide-sm { display: none; } }
</style>