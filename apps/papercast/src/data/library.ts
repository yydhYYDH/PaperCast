/**
 * 作品库的「平台归属」与「按类型怎么呈现」——集中一处，视图里不再散落判断。
 *
 * 为什么需要推导：产物落盘命名里带平台记号（poster-xhs-long.png、poster-zhihu.png、
 * poster-bili-cover.png、article/zhihu-analyst.md），但 Artifact 上没有独立的 platform 字段。
 * 所以只能按这套命名约定从 path + label 推。已向后台提建议补 meta.platform；
 * 真补上之后，只需要改这里的 platformOf() 一处，视图不用动。
 */
import type { Artifact, ArtifactKind } from '../types'

export type PlatformId = 'xhs' | 'zhihu' | 'bilibili' | 'en' | 'generic'

export type Tone = 'red' | 'blue' | 'green' | 'amber' | 'ink'

export interface PlatformMeta { label: string; hint: string; tone: Tone }

/** 板块顺序：三个真实渠道 → 英文变体 → 不针对单一平台的跨平台作品。 */
export const PLATFORM_ORDER: PlatformId[] = ['xhs', 'zhihu', 'bilibili', 'en', 'generic']

export const PLATFORM_META: Record<PlatformId, PlatformMeta> = {
  xhs: { label: '小红书', hint: '竖长图与短文案，手机上看', tone: 'red' },
  zhihu: { label: '知乎', hint: '长文与横版配图，给深度读者', tone: 'blue' },
  bilibili: { label: 'B 站', hint: '成片视频与横屏封面', tone: 'green' },
  en: { label: '英文', hint: '英文变体，本轮只生成不发布', tone: 'amber' },
  generic: { label: '跨平台', hint: '海报母版、成片、发布回执这类不针对单一平台的作品', tone: 'ink' },
}

/** 命名记号 → 平台。顺序有意义：先命中的先算。 */
const TOKENS: Array<[RegExp, PlatformId]> = [
  [/xiaohongshu|xhs/, 'xhs'],
  [/zhihu/, 'zhihu'],
  [/bilibili|bili/, 'bilibili'],
  [/(^|[^a-z])en([^a-z]|$)/, 'en'],
]

export function platformOf(a: Artifact): PlatformId {
  const hay = ((a.path || '') + ' ' + (a.label || '')).toLowerCase()
  for (const pair of TOKENS) if (pair[0].test(hay)) return pair[1]
  return 'generic'
}

/** 素材与中间产物（不算"作品"）：源 PDF、解析正文、图表、事实源。 */
export const MATERIAL_STAGES: string[] = ['intake', 'understand']

export interface KindMeta { label: string; tone: Tone; shape: 'visual' | 'doc' | 'data' }

/** 类型决定卡片长什么样：看的东西（图/视频）、读的东西（长文/文本）、机器文件（json）。 */
export const KIND_META: Record<ArtifactKind, KindMeta> = {
  image: { label: '海报 / 图', tone: 'green', shape: 'visual' },
  video: { label: '视频', tone: 'red', shape: 'visual' },
  markdown: { label: '长文', tone: 'blue', shape: 'doc' },
  html: { label: '网页', tone: 'blue', shape: 'doc' },
  text: { label: '文本', tone: 'ink', shape: 'doc' },
  pptx: { label: '幻灯片', tone: 'blue', shape: 'doc' },
  json: { label: '数据', tone: 'ink', shape: 'data' },
}

const SHAPE_RANK: Record<string, number> = { visual: 0, doc: 1, data: 2 }

export function shapeRank(kind: ArtifactKind): number {
  return SHAPE_RANK[KIND_META[kind].shape]
}

function num(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/** 人话体量：有什么说什么，没有的就不占位。 */
export function volumeChips(a: Artifact): string[] {
  const m = a.meta || {}
  const out: string[] = []
  const words = num(m.words)
  if (words) out.push(words.toLocaleString('zh-CN') + ' 字')
  const pages = num(m.pages)
  if (pages) out.push(pages + ' 页')
  const sec = num(m.durationSec) ?? num(m.duration)
  if (sec) out.push(fmtDuration(sec))
  const w = num(m.width) ?? num(m.w)
  const h = num(m.height) ?? num(m.h)
  if (w && h) out.push(w + '×' + h)
  if (a.bytes) out.push(fmtBytes(Number(a.bytes)))
  return out
}

export function fmtDuration(sec: number): string {
  const n = Math.max(0, Math.round(sec))
  return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0')
}

export function fmtBytes(n: number): string {
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

/**
 * 真实宽高比（有像素信息才算）。卡片左上那条小细条按它画 —— 是真实数据，
 * 不是装饰：横版海报、竖长图、16:9 成片一眼能分出来。没有像素信息就按类型兜底。
 */
export function aspectOf(a: Artifact): number {
  const m = a.meta || {}
  const w = num(m.width) ?? num(m.w)
  const h = num(m.height) ?? num(m.h)
  if (w && h) return w / h
  return a.kind === 'video' ? 16 / 9 : 1.5
}

export function relativeTime(ts: number, now: number = Date.now()): string {
  if (!ts) return ''
  const min = Math.round((now - ts) / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return min + ' 分钟前'
  const hr = Math.round(min / 60)
  if (hr < 24) return hr + ' 小时前'
  const day = Math.round(hr / 24)
  if (day < 8) return day + ' 天前'
  const d = new Date(ts)
  return d.getMonth() + 1 + ' 月 ' + d.getDate() + ' 日'
}
