<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { usePlatformsStore } from '../stores/platforms'
import { PLATFORM_STATE, fmtAgo } from '../utils'

const store = usePlatformsStore()
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
  const ok = window.confirm(`退出 ${name} 登录？\n\n将删除本机 cookies（当前账号：${account || '未知'}），下次发布前需要重新登录。`)
  if (!ok) return
  await store.logout(id)
}
</script>

<template>
  <div class="page">
    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">平台账号</span>
        <span class="panel-sub">发布渠道的登录入口与账号状态</span>
        <div class="grow" />
        <span class="chip" :class="readyCount ? 'ok' : 'warn'"><i class="dot" />已登录 {{ readyCount }}/{{ total }}</span>
        <span v-if="store.refreshedAt" class="panel-sub mono">{{ fmtAgo(store.refreshedAt) }}探测</span>
        <button class="btn sm" :disabled="store.loading" @click="store.refresh(true)">{{ store.loading ? '探测中…' : '刷新状态' }}</button>
      </header>
      <div class="panel-body notes">
        <p class="panel-sub">
          「刷新状态」会真实探测每一个渠道：小红书走本机 <span class="mono">xiaohongshu-mcp</span>、知乎走 <span class="mono">zhihu-publisher</span>、
          B 站走 <span class="mono">bilibili-publisher</span>（底层 biliup），小红书与 B 站的扫码登录都能在本页完成。
          <strong>没接通的渠道如实显示未配置或受限，不假装可用。</strong>
        </p>
        <p class="panel-sub">
          登录态只用于「人工闸门放行之后」的真实投递；闸门没放行时，凭证不会被动用。
        </p>
        <p v-if="store.error" class="err-line">探测失败：{{ store.error }}</p>
      </div>
    </section>

    <section v-for="c in store.channels" :key="c.id" class="panel ch" :class="c.state">
      <header class="panel-head">
        <strong class="ch-name">{{ c.name }}</strong>
        <span class="chip" :class="PLATFORM_STATE[c.state].cls"><i class="dot" />{{ PLATFORM_STATE[c.state].label }}</span>
        <span v-if="c.account" class="chip accent">账号 {{ c.account }}</span>
        <span class="chip mono">{{ c.kind }}</span>
        <div class="grow" />
        <span class="panel-sub mono ellipsis" style="max-width: 40%">{{ c.endpoint }}</span>
      </header>

      <div class="panel-body stack">
        <div class="row wrap gap">
          <span v-for="n in c.needs" :key="n" class="chip tiny">{{ n }}</span>
          <span v-for="k in c.capabilities" :key="k" class="chip tiny accent">{{ k }}</span>
        </div>
        <p class="detail">{{ c.detail }}</p>
        <p v-if="c.state !== 'ready'" class="hint-line">
          <span class="label">接通方式</span>
          <span class="mono grow ellipsis">{{ c.loginHint }}</span>
          <button class="btn sm ghost" @click="copy(c.loginHint, c.id)">{{ copied === c.id ? '已复制' : '复制' }}</button>
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
              {{ store.workingId === c.id ? '处理中…' : '退出登录（清 cookies）' }}
            </button>
            <span class="panel-sub">{{ c.id === 'bilibili' ? '二维码由本机 biliup 生成，扫码成功后 cookies 落在 bilibili-publisher' : '扫码成功后 cookies 自动落在本机 MCP 目录' }}</span>
          </template>
          <!-- 桌面窗口人工登录：知乎（风控会拦纯 HTTP 扫码，必须真人过窗口） -->
          <template v-else-if="c.login === 'browser'">
            <button class="btn primary sm" :disabled="store.workingId === c.id" @click="store.browserLogin(c.id)">
              {{ store.workingId === c.id ? '等待窗口登录…' : c.state === 'ready' ? '重新登录 / 切换账号' : '打开浏览器登录' }}
            </button>
            <button v-if="c.state === 'ready'" class="btn sm danger" :disabled="store.workingId === c.id" @click="doLogout(c.id, c.name, c.account)">
              退出登录（清 cookies）
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