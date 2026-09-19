/** 平台渠道与登录态：跨视图共享（平台账号页、发布页、顶部状态条）。 */

import { defineStore } from 'pinia'
import { api } from '../api'
import type { PlatformChannel, PlatformQrcode } from '../types'

/** 扫码弹层的阶段：loading=取码中 / waiting=等扫码 / done=已登录 / error=失败或过期 */
export type LoginPhase = 'idle' | 'loading' | 'waiting' | 'done' | 'error'

/** 轮询间隔：后端每次探测都要开一次无头浏览器，别打太密 */
const POLL_MS = 5000

/**
 * 渠道 id 别名：run.config.publish.targets 是自由文本，历史上出现过 'xiaohongshu' 与 'xhs' 两种写法，
 * 前端必须两种都认，否则会被误判成「渠道未就绪」而挡住投递。
 */
const CHANNEL_ALIAS: Record<string, string> = {
  xhs: 'xhs',
  xiaohongshu: 'xhs',
  redbook: 'xhs',
  bilibili: 'bilibili',
  bili: 'bilibili',
  zhihu: 'zhihu',
  // X（推特）：别名 twitter / x-com 都认；历史配置里把英文传播写成 'en' 的也归到 x
  x: 'x',
  twitter: 'x',
  'x-com': 'x',
  en: 'x',
}

/** 把任意写法归一成我们的渠道 id（认不出来就原样小写返回） */
export function normalizeChannelId(id: string): string {
  const key = (id ?? '').trim().toLowerCase()
  return CHANNEL_ALIAS[key] ?? key
}

export const usePlatformsStore = defineStore('platforms', {
  state: () => ({
    channels: [] as PlatformChannel[],
    loading: false,
    error: '',
    refreshedAt: 0,
    workingId: '',
    // 扫码登录弹层
    dialogOpen: false,
    dialogChannelId: '',
    phase: 'idle' as LoginPhase,
    qrcode: null as PlatformQrcode | null,
    message: '',
    _poll: undefined as number | undefined,
    _deadline: 0,
  }),

  getters: {
    /** 按 id 取渠道 */
    channel(state) {
      return (id: string) => state.channels.find((c) => c.id === id)
    },
    readyCount(state): number {
      return state.channels.filter((c) => c.state === 'ready').length
    },
    dialogChannel(state): PlatformChannel | undefined {
      return state.channels.find((c) => c.id === state.dialogChannelId)
    },
    /** 勾选的发布渠道是否都具备投递条件（登录态就绪） */
    targetsReady(state) {
      return (targets: string[]) =>
        targets.length > 0 &&
        targets.every((t) => state.channels.find((c) => c.id === normalizeChannelId(t))?.state === 'ready')
    },
    /** 未就绪的勾选渠道（原始写法），用于给出「为什么不能发布 / 哪些会被跳过」。
     *  `material_only`（X：只出素材包、没有投递通道）**不算未就绪** —— 它不是环境不对，是设计上就不投 */
    targetsBlocked(state) {
      return (targets: string[]) =>
        targets.filter((t) => {
          const s = state.channels.find((c) => c.id === normalizeChannelId(t))?.state
          return s !== 'ready' && s !== 'material_only'
        })
    },
    /** 只出素材包的勾选渠道（X）：单独说一句，不混进「未就绪」 */
    materialOnlyTargets(state) {
      return (targets: string[]) =>
        targets.filter((t) => state.channels.find((c) => c.id === normalizeChannelId(t))?.state === 'material_only')
    },
    /** 至少有一个渠道能走完这一轮 —— 全都没就绪时才拦「确认发布」。
     *  material_only 也算「能走完」：放行它只是落素材包 + draft 回执，不会真发 */
    anyTargetReady(state) {
      return (targets: string[]) =>
        targets.some((t) => {
          const s = state.channels.find((c) => c.id === normalizeChannelId(t))?.state
          return s === 'ready' || s === 'material_only'
        })
    },
  },

  actions: {
    /** force=true 绕过后端 5s 探测缓存（用户点刷新 / 扫码轮询时用） */
    async refresh(force = true) {
      this.loading = true
      this.error = ''
      try {
        this.channels = await api.listPlatforms(force)
        this.refreshedAt = Date.now()
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.loading = false
      }
    },

    /** 打开扫码登录入口。注意：每调一次都会在 MCP 侧新建一个等待会话，所以只在这里调 */
    async openLogin(id: string) {
      this.dialogOpen = true
      this.dialogChannelId = id
      this.phase = 'loading'
      this.message = ''
      this.qrcode = null
      this.stopPoll()
      try {
        const q = await api.platformLoginQrcode(id)
        this.qrcode = q
        if (q.isLoggedIn) {
          this.phase = 'done'
          this.message = q.account ? `已登录：${q.account}` : '已登录，无需扫码'
          await this.refresh(true)
          return
        }
        this.phase = 'waiting'
        this.message = '用小红书 App 扫码；扫码成功后这里会自动检测'
        this._deadline = q.expiresAt || Date.now() + 240_000
        this.startPoll()
      } catch (e) {
        this.phase = 'error'
        this.message = (e as Error).message
      }
    },

    /** 桌面窗口人工登录（知乎）：先起窗口，再轮询渠道状态直到 ready 或超时 */
    async browserLogin(id: string) {
      this.workingId = id
      this.error = ''
      this.message = ''
      try {
        const res = await api.platformLoginStart(id)
        this.message = res.hint
        await this.waitUntilReady(id, 240_000)
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.workingId = ''
      }
    },

    /** 轮询到某个渠道变 ready（登录在浏览器窗口里完成，前端只负责发现它） */
    async waitUntilReady(id: string, timeoutMs: number): Promise<boolean> {
      const deadline = Date.now() + timeoutMs
      while (Date.now() < deadline) {
        await new Promise((r) => window.setTimeout(r, POLL_MS))
        await this.refresh(true)
        const ch = this.channels.find((c) => c.id === id)
        if (ch?.state === 'ready') {
          this.message = `已登录：${ch.account || '未知账号'}`
          return true
        }
      }
      this.error = '等待登录超时：可在桌面窗口重试，或在终端执行 ./apps/zhihu-publisher/scripts/login-headed.sh'
      return false
    },

    closeLogin() {
      this.stopPoll()
      this.dialogOpen = false
      this.phase = 'idle'
      this.qrcode = null
      this.message = ''
    },

    startPoll() {
      this.stopPoll()
      this._poll = window.setInterval(() => void this.pollLogin(), POLL_MS)
    },

    stopPoll() {
      if (this._poll !== undefined) window.clearInterval(this._poll)
      this._poll = undefined
    },

    /** 等扫码期间的轮询：MCP 扫码成功会自己落盘 cookies，这里只负责发现它 */
    async pollLogin() {
      if (this.phase !== 'waiting') return
      if (Date.now() > this._deadline) {
        this.phase = 'error'
        this.message = '二维码已过期，请重新获取'
        this.stopPoll()
        return
      }
      try {
        const channels = await api.listPlatforms(true)
        this.channels = channels
        this.refreshedAt = Date.now()
        const ch = channels.find((c) => c.id === this.dialogChannelId)
        if (ch?.state === 'ready') {
          this.phase = 'done'
          this.message = ch.account ? `登录成功：${ch.account}` : '登录成功'
          this.stopPoll()
        }
      } catch (e) {
        // 单次探测失败不算失败：下一轮继续试（后端或 MCP 短暂重启很常见）
        this.message = `状态探测失败：${(e as Error).message}`
      }
    },

    /** 退出登录（删除本机凭证，不可逆）—— 调用方必须先经用户确认 */
    async logout(id: string) {
      this.workingId = id
      this.error = ''
      try {
        const result = await api.platformLogout(id)
        await this.refresh(true)
        return result
      } catch (e) {
        this.error = (e as Error).message
        return null
      } finally {
        this.workingId = ''
      }
    },
  },
})