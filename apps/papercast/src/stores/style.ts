import { defineStore } from 'pinia'
import { api } from '../api'
import type { SkillInfo } from '../api/types'

/**
 * 个性化层：风格技能（styles as skills）。
 *
 * 三件事，彼此不混：
 * 1. **界面长什么样** —— 由本仓库的 `papercast-frontend` 技能管（那是它的活，不是这里的开关）；
 * 2. **这一轮内容长什么样** —— 由这里选的风格决定：写进这次运行的 `brief`（后端 app/prompts.py
 *    有 BRIEF_RULES 约束它，`brief_checks` 会机检遵从度，所以风格是真生效、可核对的）；
 * 3. 选了什么 —— 只存在浏览器本地（localStorage），不进 git、不上传。
 */

const KEY = 'papercast.style'
export const DEFAULT_STYLE = 'papercast-frontend'

export const useStyleStore = defineStore('style', {
  state: () => ({
    skills: [] as SkillInfo[],
    /** 当前风格技能名 */
    current: (typeof localStorage !== 'undefined' && localStorage.getItem(KEY)) || DEFAULT_STYLE,
    loading: false,
    error: '',
  }),

  getters: {
    currentSkill(state): SkillInfo | undefined {
      return state.skills.find((s) => s.name === state.current)
    },
    /** 界面上一句话就够：名字 + 它管什么 */
    currentLabel(state): string {
      return state.skills.find((s) => s.name === state.current)?.description
        ? state.current
        : state.current
    },
    styleSkills(state): SkillInfo[] {
      return state.skills.filter((s) => s.style)
    },
    otherSkills(state): SkillInfo[] {
      return state.skills.filter((s) => !s.style)
    },
    /** 选了风格却找不到（比如换机器、技能没装）时如实说，不假装生效 */
    missing(state): boolean {
      return !!state.skills.length && !state.skills.some((s) => s.name === state.current)
    },
  },

  actions: {
    async load(force = false) {
      if (this.loading) return
      if (this.skills.length && !force) return
      this.loading = true
      this.error = ''
      try {
        this.skills = await api.skills()
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.loading = false
      }
    },

    use(name: string) {
      this.current = name
      try {
        localStorage.setItem(KEY, name)
      } catch {
        /* 隐私模式下写不了，就当这次会话内生效 */
      }
    },

    /**
     * 把风格写进这次运行的 brief：**用户自己说的话在前，风格在后** ——
     * 用户的具体要求永远优先于风格的一句话说明。
     */
    buildBrief(userWords: string): string {
      const k = this.currentSkill
      const styleLine = k
        ? `风格（${k.name}）：${k.description}`
        : `风格（${this.current}）：按仓库默认的编辑风格来`
      const mine = userWords.trim()
      return [mine, styleLine].filter(Boolean).join('；')
    },
  },
})
