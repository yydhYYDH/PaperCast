<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { api, assetUrl } from '../api'
import { usePlatformsStore } from '../stores/platforms'

const store = usePlatformsStore()
const now = ref(Date.now())
let tick: number | undefined

// 只在弹层打开时跑秒表，用于二维码倒计时
watch(
  () => store.dialogOpen,
  (open) => {
    if (open && tick === undefined) tick = window.setInterval(() => (now.value = Date.now()), 1000)
    else if (!open && tick !== undefined) {
      window.clearInterval(tick)
      tick = undefined
    }
  },
)
onUnmounted(() => { if (tick !== undefined) window.clearInterval(tick) })

const isMock = api.label.includes('mock')
/** 弹层只有两种来源：小红书（MCP 页内二维码）与 B 站（biliup 出的码）——文案随之切换 */
const isBili = computed(() => store.dialogChannelId === 'bilibili')
const producer = computed(() => (isBili.value ? 'bilibili-publisher :18080（底层 biliup）' : 'xiaohongshu-mcp :18060'))
const fixCmd = computed(() => (isBili.value ? './ops/start_all.sh bilibili' : './ops/start_all.sh mcp'))
const appHint = computed(() =>
  isBili.value ? '打开 B 站 App → 我的 → 右上角扫一扫' : '打开小红书 App → 我 → 左上角扫一扫',
)
const cookieNote = computed(() =>
  isBili.value ? 'cookies 已落在本机 bilibili-publisher，投稿时才会用到' : 'cookies 已落在本机 MCP 目录，发布时才会用到',
)
const loadingNote = computed(() =>
  isBili.value
    ? '正在让本机 biliup 出二维码…（要先起一次浏览器会话，通常 10–25 秒）'
    : '正在向本机 MCP 申请二维码…（MCP 需要开一次无头浏览器，通常 3–10 秒）',
)
const img = computed(() => assetUrl(store.qrcode?.img))
const remain = computed(() => Math.max(0, Math.ceil(((store.qrcode?.expiresAt ?? 0) - now.value) / 1000)))

function fmt(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
</script>

<template>
  <Teleport to="body">
    <div v-if="store.dialogOpen" class="mask" @click.self="store.closeLogin()">
      <section class="dlg panel">
        <header class="panel-head">
          <span class="panel-title">扫码登录 · {{ store.dialogChannel?.name ?? store.dialogChannelId }}</span>
          <span v-if="store.phase === 'waiting'" class="chip warn"><i class="dot" />{{ fmt(remain) }}</span>
          <span v-else-if="store.phase === 'done'" class="chip ok"><i class="dot" />已登录</span>
          <div class="grow" />
          <button class="btn sm ghost" @click="store.closeLogin()">关闭</button>
        </header>

        <div class="body">
          <div v-if="store.phase === 'loading'" class="slot">
            <div class="spinner" />
            <p class="panel-sub">{{ loadingNote }}</p>
          </div>

          <div v-else-if="store.phase === 'waiting'" class="slot">
            <img v-if="img" class="qr" :src="img" alt="登录二维码" />
            <div v-else class="slot-empty">通道服务未返回二维码图片</div>
            <p class="hint">{{ appHint }}</p>
            <p class="panel-sub remain">二维码有效期 {{ fmt(remain) }}；扫码成功后弹层会自动关闭</p>
          </div>

          <div v-else-if="store.phase === 'done'" class="slot">
            <div class="ok-mark">✓</div>
            <p class="hint">{{ store.message }}</p>
            <p class="panel-sub">{{ cookieNote }}</p>
          </div>

          <div v-else class="slot">
            <div class="err-mark">!</div>
            <p class="hint">{{ store.message || '获取二维码失败' }}</p>
            <p class="panel-sub">先确认通道服务在跑：<span class="mono">{{ fixCmd }}</span></p>
          </div>
        </div>

        <footer class="foot">
          <p class="panel-sub grow">
            {{ store.dialogChannel?.loginHint }}
            <br />
            二维码由本机 <span class="mono">{{ producer }}</span> 生成，账号凭证只落本机，不上传。
          </p>
          <button
            v-if="store.phase === 'waiting' || store.phase === 'error'"
            class="btn sm"
            @click="store.openLogin(store.dialogChannelId)"
          >
            重新获取二维码
          </button>
        </footer>

        <p v-if="isMock" class="mock-note">
          当前是内置模拟器：这里显示的是演示二维码，不会真的登录。接真后端（VITE_API_BASE=http://127.0.0.1:8000）后即为真实登录入口。
        </p>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.42); backdrop-filter: blur(4px); display: grid; place-items: center; z-index: 50; padding: 20px; }
.dlg { width: 100%; max-width: 420px; box-shadow: var(--shadow-lg); }
.body { padding: 16px 18px 4px; }
.slot { display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center; min-height: 236px; justify-content: center; }
.slot-empty { width: 220px; height: 220px; display: grid; place-items: center; border: 1px dashed var(--line); border-radius: 10px; color: var(--muted-2); font-size: 12.5px; }
.qr { width: 220px; height: 220px; background: #fff; border-radius: 12px; padding: 8px; border: 1px solid var(--line); box-shadow: 0 10px 26px -16px rgba(16, 24, 40, 0.5); }
.hint { font-size: 13px; color: var(--text); }
.remain { font-size: 11.5px; }
.foot { display: flex; gap: 12px; align-items: flex-end; padding: 12px 18px 14px; border-top: 1px solid var(--line-soft); }
.foot .panel-sub { line-height: 1.6; font-size: 11.5px; }
.spinner { width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--line); border-top-color: var(--accent); animation: rot 0.9s linear infinite; }
@keyframes rot { to { transform: rotate(360deg); } }
.ok-mark { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; font-size: 22px; color: var(--ok); background: rgba(53, 211, 154, 0.14); border: 1px solid rgba(53, 211, 154, 0.4); }
.err-mark { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; font-size: 22px; color: var(--err); background: rgba(255, 95, 126, 0.12); border: 1px solid rgba(255, 95, 126, 0.4); }
.mock-note { margin: 0; padding: 9px 18px 12px; font-size: 11.5px; color: var(--warn); border-top: 1px dashed var(--line-soft); }
</style>