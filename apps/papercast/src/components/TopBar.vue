<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useEnvStore } from '../stores/env'
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
  style: '风格',
  ops: '运营维护',
  settings: '设置',
}

const env = useEnvStore()
/** 悬停时逐条说清「哪项还没好」，不暴露端口/工具名 */
const envTip = computed(() => env.rows.map((r) => r.label + '：' + r.detail).join('\n'))

/** 小红书是唯一有真实登录入口的渠道：状态直接顶到顶栏，没登录时点一下就能扫码 */
const xhs = computed(() => platforms.channel('xhs'))
/** 首次探测要开一次无头浏览器（3–20 秒），这期间也得给个能点的入口，否则顶栏像坏了 */
const probing = computed(() => !xhs.value && !platforms.refreshedAt)

onMounted(() => {
  if (!platforms.channels.length) void platforms.refresh(false)
  void env.load()
})
</script>

<template>
  <header class="top">
    <div class="row gap">
      <strong class="brand">Easy-Reach</strong>
      <span class="sep" />
      <span class="cur">{{ TITLES[ui.view] }}</span>
      <span class="panel-sub hide-sm">把一篇论文变成大家看得懂的内容</span>
    </div>

    <div class="grow" />

    <label class="demo" :title="store.autoConfirm ? '闸门自动放行' : '闸门需人工确认'">
      <input v-model="store.autoConfirm" type="checkbox" />
      <!-- 手机上只留「演示」两个字：一整行要放得下品牌、页面名和两个状态胶囊 -->
      <span class="wide">演示模式</span>
      <span class="narrow">演示</span>
    </label>

    <button
      v-if="probing"
      class="chip login-chip"
      title="正在探测各平台登录态（首次约 3–20 秒）；点进去可看每个渠道的状态与登录入口"
      @click="ui.setView('platforms')"
    >
      <i class="dot" />
      <span class="wide">{{ platforms.loading ? '正在检查登录状态…' : '查看平台登录状态' }}</span>
      <span class="narrow">平台</span>
    </button>

    <button
      v-else-if="xhs"
      class="chip login-chip"
      :class="PLATFORM_STATE[xhs.state].cls"
      :title="xhs.state === 'ready' ? `小红书已登录：${xhs.account || '未知账号'}（点击管理）` : `${xhs.detail}（点击登录）`"
      @click="ui.setView('platforms')"
    >
      <i class="dot" />
      <span class="wide">小红书 {{ xhs.state === 'ready' ? (xhs.account || '已登录') : PLATFORM_STATE[xhs.state].label }}</span>
      <span class="narrow">小红书</span>
    </button>

    <button
      class="chip login-chip"
      :class="env.ready ? 'ok' : 'warn'"
      :title="envTip"
      @click="ui.setView('settings')"
    >
      <i class="dot" />
      <span class="wide">{{ env.ready ? '环境就绪' : '待处理 ' + env.pending.length + ' 项' }}</span>
      <span class="narrow">{{ env.ready ? '就绪' : env.pending.length + ' 项' }}</span>
    </button>
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
.narrow { display: none; }

/* 手机：顶栏只留一行 —— 品牌、页面名、演示开关、两个状态胶囊，都要放得下且不换行 */
@media (max-width: 720px) {
  .top { padding: 10px 13px; gap: 8px; flex-wrap: nowrap; overflow: hidden; }
  .brand { font-size: 15px; white-space: nowrap; }
  .cur { font-size: 12.5px; white-space: nowrap; }
  .sep { display: none; }
  .row.gap { gap: 6px; min-width: 0; }
  .demo { font-size: 11.5px; white-space: nowrap; }
  .wide { display: none; }
  .narrow { display: inline; }
  .login-chip { padding: 4px 9px; font-size: 11.5px; white-space: nowrap; }
}
@media (max-width: 1280px) { .hide-sm { display: none; } }
</style>