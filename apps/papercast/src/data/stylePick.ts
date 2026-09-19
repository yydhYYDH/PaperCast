import type { StyleOption } from '../api/types'

/**
 * 对话里认出来：把用户那句话里的「平台」与「口吻」解析成 variant id。
 *
 * 为什么要这一步：风格页能选，但工作台只有一个输入框（这是既有设计：一个入口、能不选就不选）。
 * 所以「做成小红书+知乎，用机器之心的口吻」这种话必须**真的**改变这一轮生成什么，
 * 而不是只作为一句 brief 文字飘过去 —— brief 改的是语气描述，改不了平台与校验规则。
 *
 * 规则：
 * - 认出平台 → 只出这些平台；只认出口吻 → 平台沿用当前选择；
 * - 两个都没认出来 → **原样返回 base**（等于不改，绝不猜用户想要什么）；
 * - 上限与后端一致（styles.MAX_VARIANTS = 4），多出来的按出现顺序截断。
 */

/** 平台口语词 → id */
const PLATFORM_WORDS: [RegExp, string][] = [
  [/小红书|红书|xiaohongshu|\bxhs\b/i, 'xhs'],
  [/知乎|\bzhihu\b/i, 'zhihu'],
  [/b\s*站|哔哩|bilibili|\bbbili\b/i, 'bilibili'],
  [/英文|英语|english|推特|twitter|\bx\b|linkedin|领英/i, 'en'],
]

/** 口吻口语词 → voice id（顺序即优先级：越具体的越靠前） */
const VOICE_WORDS: [RegExp, string][] = [
  [/专业科普|科普|独立(视角|口吻)?|第三方/i, 'independent'],
  [/白话|拆解|师兄|讲人话|好懂/i, 'peer'],
  [/震惊|爆点|快讯|标题党|耸动/i, 'newsflash'],
  [/专业解读|技术解读|机器之心|解读|技术向/i, 'analyst'],
  [/审稿|评审|reviewer/i, 'reviewer'],
]

export interface StyleIntent {
  platforms: string[]
  voice: string
}

/** 从一句话里解析出平台与口吻；没认出来的部分留空 */
export function parseStyleIntent(text: string): StyleIntent {
  const t = (text || '').trim()
  const platforms: string[] = []
  const all = /全平台|所有平台|每个平台|都来一份|四个平台/.test(t)
  for (const [re, id] of PLATFORM_WORDS) {
    if (re.test(t) && !platforms.includes(id)) platforms.push(id)
  }
  let voice = ''
  for (const [re, id] of VOICE_WORDS) {
    if (re.test(t)) {
      voice = id
      break
    }
  }
  return { platforms: all ? ['xhs', 'zhihu', 'bilibili', 'en'] : platforms, voice }
}

/**
 * 这一轮实际要生成的 variant 列表。
 *
 * @param text  用户这次说的话
 * @param base  当前选择（风格页里勾的；为空说明用户没选，调用方应传「默认配置」）
 * @param max   上限（后端 styles.MAX_VARIANTS）
 */
export function variantsFromText(text: string, base: string[], max: number): string[] {
  const { platforms, voice } = parseStyleIntent(text)
  // 什么都没认出来：保持原配置。注意不能「用 base 的平台 + base 的口吻重算一遍」——
  // 默认配置里各平台的口吻可能不同（xhs-independent + en-analyst），重算会悄悄丢掉一个。
  if (!platforms.length && !voice) return base.slice(0, Math.max(1, max))
  const ids = platforms.length ? platforms : uniquePlatforms(base)
  if (!ids.length) return []
  const wantVoice = voice || voiceOf(base) || ''
  if (!wantVoice) return []
  const out = ids.map((p) => p + '-' + wantVoice)
  return out.slice(0, Math.max(1, max))
}

function splitVariant(v: string): { platform: string; voice: string } | null {
  const i = v.indexOf('-')
  if (i <= 0) return null
  return { platform: v.slice(0, i), voice: v.slice(i + 1) }
}

function uniquePlatforms(variants: string[]): string[] {
  const out: string[] = []
  for (const v of variants) {
    const s = splitVariant(v)
    if (s && !out.includes(s.platform)) out.push(s.platform)
  }
  return out
}

/** 沿用当前选择里的口吻：取第一条的口吻（一份配置通常只有一个口吻，多平台共用） */
export function voiceOf(variants: string[]): string {
  for (const v of variants) {
    const s = splitVariant(v)
    if (s) return s.voice
  }
  return ''
}

/** 把 variant id 变成给人看的一句话（认不出来的原样返回，不假装认识） */
export function styleLabel(variant: string, styles: StyleOption[]): string {
  const hit = styles.find((s) => s.variant === variant)
  return hit ? hit.platformLabel + ' · ' + hit.short : variant
}
