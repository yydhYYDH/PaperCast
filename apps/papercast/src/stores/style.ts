import { defineStore } from 'pinia'
import { api } from '../api'
import type { SkillInfo, StyleMenu, StyleOption } from '../api/types'
import { exampleRunConfig } from '../data/example'
import { styleLabel } from '../data/stylePick'

/**
 * 个性化层：两件事，彼此不混。
 *
 * 1. **这一轮内容写成什么样** —— 平台 × 口吻（「小红书 · 专业科普」「知乎 · 专业解读」…）。
 *    选项与约束来自后端 app/styles.py（GET /api/styles），选中的 id 直接就是这次运行的
 *    config.article.variants —— 不是装饰开关，也不只是写进 brief 的一句话。
 * 2. **界面/文档长什么样** —— 仓库自己的风格技能（papercast-frontend 等）。
 *    本机 ~/.agents/skills 装的第三方技能不在这里展示（用户 2026-09-19 明确要求）。
 *
 * 选择只存在浏览器本地（localStorage），不进 git、不上传。
 */

const KEY = 'papercast.style'
const KEY_PICKED = 'papercast.style.picked'
export const DEFAULT_STYLE = 'papercast-frontend'

function readPicked(): string[] {
  try {
    const raw = localStorage.getItem(KEY_PICKED)
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export const useStyleStore = defineStore('style', {
  state: () => ({
    skills: [] as SkillInfo[],
    /** 平台 × 口吻的清单（GET /api/styles）；null = 还没读到 */
    menu: null as StyleMenu | null,
    /** 当前界面/文档风格技能名 */
    current: (typeof localStorage !== 'undefined' && localStorage.getItem(KEY)) || DEFAULT_STYLE,
    /** 风格页里勾的内容风格；空数组 = 没勾，用工作台默认 */
    picked: (typeof localStorage !== 'undefined' ? readPicked() : []) as string[],
    loading: false,
    error: '',
    menuError: '',
  }),

  getters: {
    currentSkill(state): SkillInfo | undefined {
      return state.skills.find((s) => s.name === state.current)
    },
    /** 只列仓库自带（跟着代码走）的技能：本机 ~/.agents/skills 那批不展示 */
    styleSkills(state): SkillInfo[] {
      return state.skills.filter((s) => s.style && s.origin === 'repo')
    },
    otherSkills(state): SkillInfo[] {
      return state.skills.filter((s) => !s.style && s.origin === 'repo')
    },
    /** 被隐藏的用户级技能数（如实说明，不假装本机只有两个技能） */
    hiddenSkillCount(state): number {
      return state.skills.filter((s) => s.origin !== 'repo').length
    },
    /** 选了风格却找不到（比如换机器、技能没装）时如实说，不假装生效 */
    missing(state): boolean {
      return !!state.skills.length && !state.skills.some((s) => s.name === state.current)
    },

    /* ---------- 内容风格（平台 × 口吻） ---------- */

    styles(state): StyleOption[] {
      return state.menu?.styles ?? []
    },
    maxVariants(state): number {
      return state.menu?.maxVariants ?? 4
    },
    /** 风格页按平台分组渲染：一组 = 一个平台 + 它下面的几种口吻 */
    platformGroups(state): { id: string; label: string; rows: StyleOption[] }[] {
      const out: { id: string; label: string; rows: StyleOption[] }[] = []
      for (const s of state.menu?.styles ?? []) {
        let g = out.find((x) => x.id === s.platform)
        if (!g) {
          g = { id: s.platform, label: s.platformLabel, rows: [] }
          out.push(g)
        }
        g.rows.push(s)
      }
      return out
    },
    /** 这次真正会生成的变体：勾了就用勾的，没勾用工作台默认配置 */
    effectiveVariants(state): string[] {
      return state.picked.length ? state.picked : (exampleRunConfig().article.variants ?? [])
    },
    effectiveIsDefault(state): boolean {
      return state.picked.length === 0
    },
    /** 给人看的一句话：「小红书 · 专业科普、知乎 · 专业解读」 */
    effectiveLabel(state): string {
      const list = state.picked.length ? state.picked : (exampleRunConfig().article.variants ?? [])
      const styles = state.menu?.styles ?? []
      return list.map((v) => styleLabel(v, styles)).join('、')
    },
  },

  actions: {
    async load(force = false) {
      if (this.loading) return
      if (this.skills.length && this.menu && !force) return
      this.loading = true
      this.error = ''
      this.menuError = ''
      try {
        this.skills = await api.skills()
      } catch (e) {
        this.error = (e as Error).message
      }
      try {
        this.menu = await api.styles()
      } catch (e) {
        this.menuError = (e as Error).message
      } finally {
        this.loading = false
      }
    },

    /** 勾 / 取消一条内容风格；超过后端上限时如实说，不静默丢 */
    toggle(variant: string): { ok: boolean; reason: string } {
      const i = this.picked.indexOf(variant)
      if (i >= 0) {
        this.picked.splice(i, 1)
        this.savePicked()
        return { ok: true, reason: '' }
      }
      if (this.picked.length >= this.maxVariants) {
        return { ok: false, reason: '一次最多 ' + this.maxVariants + ' 个平台风格（每个都要单独生成一遍）' }
      }
      this.picked.push(variant)
      this.savePicked()
      return { ok: true, reason: '' }
    },

    clearPicked() {
      this.picked = []
      this.savePicked()
    },

    savePicked() {
      try {
        localStorage.setItem(KEY_PICKED, JSON.stringify(this.picked))
      } catch {
        /* 隐私模式下写不了，就当这次会话内生效 */
      }
    },

    use(name: string) {
      this.current = name
      try {
        localStorage.setItem(KEY, name)
      } catch {
        /* 同上 */
      }
    },

    /**
     * 界面/文档风格写进这次运行的 brief：**用户自己说的话在前，风格在后** ——
     * 用户的具体要求永远优先于风格的一句话说明。
     */
    buildBrief(userWords: string): string {
      const k = this.currentSkill
      const styleLine = k
        ? '风格（' + k.name + '）：' + k.description
        : '风格（' + this.current + '）：按仓库默认的编辑风格来'
      const mine = userWords.trim()
      return [mine, styleLine].filter(Boolean).join('；')
    },
  },
})
