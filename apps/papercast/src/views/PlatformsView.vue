<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { usePlatformsStore } from '../stores/platforms'
import { useUiStore } from '../stores/ui'
import { PLATFORM_STATE, fmtAgo } from '../utils'

const store = usePlatformsStore()
const ui = useUiStore()
const copied = ref('')

onMounted(() => void store.refresh(false))

const LOGIN_LABEL: Record<string, string> = {
  qrcode: '扫码登录',
  browser: '桌面窗口登录',
  env: '配置凭证',
  cli: '命令行登录',
  none: '不支持登录',
}

const readyCount = computed(() => store.readyCount)

/** 把技术端点说成人话（页面上不出现 localhost:18070 这种字符串） */
const PLAIN_ENDPOINT: Record<string, string> = {
  'http://127.0.0.1:18060': '本机的小红书服务',
  'http://127.0.0.1:18070': '本机的知乎服务',
  'http://127.0.0.1:18080': '本机的 B 站服务',
}
function plainEndpoint(endpoint: string) {
  if (!endpoint) return ''
  if (PLAIN_ENDPOINT[endpoint]) return PLAIN_ENDPOINT[endpoint]
  if (endpoint.includes('127.0.0.1') || endpoint.includes('localhost')) return '本机服务'
  return endpoint
}
const total = computed(() => store.channels.length)

async function copy(text: string, id: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = id
    window.setTimeout(() => { if (copied.value === id) copied.value = '' }, 1600)
  } catch {
    copied.value = ''
  }
}

async function doLogout(id: string, name: string, account: string) {
  const ok = await ui.askConfirm({
    title: `退出 ${name} 的登录？`,
    text: `会删除本机保存的登录凭证（当前账号：${account || '未知'}）。这一步不可撤销，下次要发布时得重新登录一次。`,
    okLabel: '退出登录',
    cancelLabel: '再想想',
    tone: 'err',
  })
  if (!ok) return
  const result = await store.logout(id)
  if (result) ui.toast(result.message, result.state === 'ready' ? 'warn' : 'info', 9000)
  else if (store.error) ui.toast('退出登录失败：' + store.error, 'err')
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">平台账号</h1>
        <p class="page-lead">
          这里管「往哪里发」。点一下就能扫码或打开登录窗口，登录一次之后，发布时不用再输密码。
        </p>
      </div>
      <span class="chip" :class="readyCount ? 'ok' : 'warn'"><i class="dot" />已登录 {{ readyCount }}/{{ total }}</span>
      <span v-if="store.refreshedAt" class="meta-line">{{ fmtAgo(store.refreshedAt) }}前更新</span>
      <button class="btn" :disabled="store.loading" @click="store.refresh(true)">{{ store.loading ? '查看中…' : '刷新状态' }}</button>
    </header>

    <section class="panel">
      <div class="panel-body notes">
        <p class="panel-sub">
          「刷新状态」会真的去每一个平台看一次，所以第一次可能要等十几秒。
          没登录的渠道会如实写清楚，不会假装能用。
        </p>
        <p class="panel-sub">
          登录信息只存在这台电脑上，只在你在发布页点了「确认发布」之后才会用到。
        </p>
        <p v-if="store.error" class="err-line">查看状态失败：{{ store.error }}</p>
      </div>
    </section>

    <section v-for="c in store.channels" :key="c.id" class="panel ch" :class="c.state">
      <header class="panel-head">
        <strong class="ch-name">{{ c.name }}</strong>
        <span class="chip" :class="PLATFORM_STATE[c.state].cls"><i class="dot" />{{ PLATFORM_STATE[c.state].label }}</span>
        <span v-if="c.account" class="chip accent">账号 {{ c.account }}</span>
        <div class="grow" />
        <span class="panel-sub ellipsis" style="max-width: 40%">{{ plainEndpoint(c.endpoint) }}</span>
      </header>

      <div class="panel-body stack">
        <div class="row wrap gap">
          <span v-for="n in c.needs" :key="n" class="chip tiny">{{ n }}</span>
          <span v-for="k in c.capabilities" :key="k" class="chip tiny accent">{{ k }}</span>
        </div>
        <p class="detail">{{ c.detail }}</p>
        <p v-if="c.state !== 'ready'" class="hint-line">
          <span class="label">怎么接通</span>
          <span class="mono grow ellipsis">{{ c.loginHint }}</span>
          <button class="btn sm ghost" @click="copy(c.loginHint, c.id)">{{ copied === c.id ? '已复制' : '复制命令' }}</button>
        </p>

        <div class="row wrap gap">
          <!-- 扫码登录：小红书（MCP 页内二维码）/ B 站（biliup 出的码，通道服务取图给前端） -->
          <template v-if="c.login === 'qrcode'">
            <button
              class="btn primary sm"
              :disabled="store.workingId === c.id || c.state === 'offline' || c.state === 'unconfigured'"
              @click="store.openLogin(c.id)"
            >
              {{ store.workingId === c.id ? '获取二维码…' : c.state === 'ready' ? '重新扫码 / 切换账号' : '扫码登录' }}
            </button>
            <button v-if="c.state === 'ready'" class="btn sm danger" :disabled="store.workingId === c.id" @click="doLogout(c.id, c.name, c.account)">
              {{ store.workingId === c.id ? '正在退出…' : '退出登录' }}
            </button>
            <span class="panel-sub">用手机扫这个码就登录好了，登录状态保存在本机</span>
          </template>
          <!-- 桌面窗口人工登录：知乎（风控会拦纯 HTTP 扫码，必须真人过窗口） -->
          <template v-else-if="c.login === 'browser'">
            <button class="btn primary sm" :disabled="store.workingId === c.id" @click="store.browserLogin(c.id)">
              {{ store.workingId === c.id ? '等待窗口登录…' : c.state === 'ready' ? '重新登录 / 切换账号' : '打开浏览器登录' }}
            </button>
            <button v-if="c.state === 'ready'" class="btn sm danger" :disabled="store.workingId === c.id" @click="doLogout(c.id, c.name, c.account)">
              退出登录
            </button>
            <span class="panel-sub">桌面会弹出浏览器窗口，扫码或账号登录（含人机验证）；登录态落在本机 zhihu-publisher，真实发布仍需人工闸门</span>
          </template>
          <!-- 凭证 / CLI 类渠道 -->
          <template v-else>
            <button class="btn sm" disabled>{{ LOGIN_LABEL[c.login] }}：需在服务端配置</button>
            <span class="panel-sub">接入后这里的按钮会变成真实登录入口</span>
          </template>
        </div>
      </div>
    </section>

    <!-- 首屏骨架：真实探测要开无头浏览器，先让用户看到「在探测」而不是空白 -->
    <section v-if="!store.channels.length && (store.loading || !store.refreshedAt)" class="panel">
      <header class="panel-head">
        <span class="panel-title">正在探测各平台登录态…</span>
        <div class="grow" />
        <span class="panel-sub">首次约 3–20 秒（小红书要真的开一次无头浏览器）</span>
      </header>
      <div class="panel-body stack">
        <div v-for="i in 4" :key="i" class="skeleton-row">
          <span class="sk sk-w"></span><span class="sk sk-s"></span><span class="sk sk-l"></span>
        </div>
      </div>
    </section>

    <div v-else-if="!store.channels.length" class="panel empty">
      <p>还没有渠道数据。</p>
      <p class="panel-sub">接上真后端后这里会列出小红书 / 知乎 / B 站三个渠道。</p>
    </div>
  </div>
</template>

<style scoped>
.notes { display: flex; flex-direction: column; gap: 7px; }
.notes .panel-sub { line-height: 1.7; }
.ch-name { font-size: 14px; }
.stack { display: flex; flex-direction: column; gap: 9px; }
.gap { gap: 6px; }
.detail { font-size: 13px; color: var(--text-2); }
.hint-line { display: flex; align-items: center; gap: 8px; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 8px; padding: 7px 10px; }
.hint-line .label { flex: none; }
.chip.tiny { font-size: 10.5px; padding: 1px 6px; }
.err-line { color: var(--err); font-size: 12px; }
.ch.ready { border-color: rgba(16, 185, 129, 0.3); }
.ch.login_required, .ch.blocked { border-color: rgba(245, 158, 11, 0.32); }
.ch.offline { border-color: rgba(239, 68, 68, 0.28); }
.skeleton-row { display: flex; align-items: center; gap: 10px; }
.sk { height: 13px; border-radius: 6px; background: linear-gradient(90deg, var(--panel-3), var(--panel-2), var(--panel-3)); background-size: 200% 100%; animation: sk 1.4s ease-in-out infinite; }
.sk-w { width: 92px; } .sk-s { width: 60px; } .sk-l { flex: 1; }
@keyframes sk { 0% { background-position: 0% 0; } 100% { background-position: -200% 0; } }
</style>