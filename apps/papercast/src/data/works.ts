/**
 * 作品库的「作品」模型：**一件 = 一次运行里、面向一个平台的那份稿子**。
 *
 * 为什么要这层推导：用户在小红书看到的是一篇图文、在 B 站看到的是一条视频，
 * 而不是 run_xxx/article/cards/p1.png 这种文件。所以一件作品要有自己的封面、标题、
 * 正文/成片入口，以及「发了没有」。
 *
 * 两个数据来源，都读真产物，读不到就说读不到，不编：
 *   1) 产物本身（卡片 / 横版配图 / 成片 / 正文）—— PaperRun.stages[].artifacts；
 *   2) 发布回执 publish/receipts.json —— 每个渠道实际投的标题、状态、为什么没投成。
 *
 * 回执是**可选**的：发布阶段还没走到时没有回执，这时状态由阶段状态推（waiting=等你确认），
 * 标题退回「待发布标题 title.txt」，再退回论文标题。
 */
import type { Artifact, ChannelReceipt, PaperRun, RunReceipts, Stage } from '../types'
import { PLATFORM_META, PLATFORM_ORDER, fmtDuration, relativeTime } from './library'
import type { PlatformId } from './library'

export type WorkState =
  | 'published'   // 真发出去了
  | 'awaiting'    // 卡在发布前的人工闸门
  | 'draft'       // 只落了素材包
  | 'blocked'     // 渠道没就绪（未登录 / 服务离线）
  | 'failed'      // 投了但失败
  | 'unpublished' // 还没轮到发布
  | 'incomplete'  // 这次运行没跑完

export interface Work {
  key: string
  run: PaperRun
  platform: PlatformId
  /** 点进去看什么：一篇文字稿，还是一条片子 */
  kind: 'article' | 'video'
  title: string
  /** 标题的出处：回执标题（这个渠道真发的那份）/ 待发布标题 / 论文原标题 */
  titleFrom: 'receipt' | 'export' | 'paper'
  /** 文案变体名（xhs-independent 之类，见后端 app/styles.py）；空串表示回执没写 */
  variant: string
  /** 这个平台没有专属文案、借了别家那份时，在这里说清楚 */
  borrowed: string
  cover?: Artifact
  /** 真卡片 / 配图，详情里横滑（小红书那几张 1080×1440 的图） */
  shots: Artifact[]
  reader?: Artifact
  video?: Artifact
  state: WorkState
  /** 一句人话说明「为什么是这个状态」 */
  note: string
  link: string
  /** 最多三个数字，别的细节收进详情 */
  stats: string[]
  at: number
}

export interface WorkSection {
  id: string
  label: string
  platform: PlatformId
  unit: string
  min: number
  ratio: number
  /** 一句结论：「都存成了草稿」「2 件发出去了」 */
  note: string
  list: Work[]
}

/* ---------------------------------------------------------------- 状态词表 */

export const STATE_CHIP: Record<WorkState, { label: string; cls: string }> = {
  published: { label: '已发布', cls: 'ok' },
  awaiting: { label: '等你确认', cls: 'warn' },
  draft: { label: '存了草稿', cls: '' },
  blocked: { label: '渠道没就绪', cls: 'warn' },
  failed: { label: '没发成功', cls: 'err' },
  unpublished: { label: '还没发', cls: '' },
  incomplete: { label: '没跑完', cls: '' },
}

/* ---------------------------------------------------------------- 小工具 */

function stageOf(run: PaperRun, id: string): Stage | undefined {
  return run.stages.find((s) => s.id === id)
}

/** 这个阶段里的图（按需还可用 kind 收窄） */
function images(run: PaperRun, stageId: string): Artifact[] {
  return (stageOf(run, stageId)?.artifacts ?? []).filter((a) => a.kind === 'image' && !!a.url)
}

function find(list: Artifact[], re: RegExp): Artifact | undefined {
  return list.find((a) => re.test(a.path))
}

/**
 * 产物路径/标签里的平台记号。
 * 英文这条必须带词边界 —— 直接 /en/ 会命中 content.txt、understand 这些词，
 * 曾经因此凭空多出一个「英文」板块（42 件里混进 10 件假的）。
 */
const TOKEN_RE: Record<PlatformId, RegExp> = {
  xhs: /xhs|xiaohongshu/,
  zhihu: /zhihu/,
  bilibili: /bili/,
  // X 的稿子就是 article 阶段的 en 变体（en-analyst.md / poster-en.png），记号仍是 en
  x: /(^|[^a-z])en([^a-z]|$)/,
  generic: /$^/,
}

function words(run: PaperRun): number {
  const n = Number((find(stageOf(run, 'article')?.artifacts ?? [], /article\/export\/content\.txt$/)?.meta || {}).words)
  return Number.isFinite(n) ? n : 0
}

/* ---------------------------------------------------------------- 一个平台要摆什么 */

interface Lineup {
  cover?: Artifact
  reader?: Artifact
  video?: Artifact
  shots: Artifact[]
}

/** 正文候选：先要这个平台自己的变体，再退中文优先的那份，最后退历史 export/ */
function readerFor(run: PaperRun, token: string): Artifact | undefined {
  const all = stageOf(run, 'article')?.artifacts ?? []
  const mds = all.filter((a) => a.kind === 'markdown' && !!a.url)
  const mine = mds.find((a) => new RegExp(token).test(a.path))
  return mine ?? mds[0] ?? find(all, /article\/export\/content\.txt$/)
}

function lineupFor(run: PaperRun, p: PlatformId): Lineup {
  const cards = images(run, 'article').filter((a) => /article\/cards\//.test(a.path)).sort((x, y) => x.path.localeCompare(y.path))
  const posters = images(run, 'poster')
  const videoImgs = images(run, 'video')
  const videos = (stageOf(run, 'video')?.artifacts ?? []).filter((a) => a.kind === 'video' && !!a.url)
  const mainPoster = find(posters, /poster\/poster\.png$/)
  const videoCover = find(videoImgs, /video\/cover\.png$/)

  if (p === 'xhs') {
    return {
      // 小红书的第一张卡片就是它在手机上真正的封面（1080×1440，3:4）
      cover: cards[0] ?? find(posters, /poster-xhs-long\.png$/),
      reader: readerFor(run, 'xhs'),
      shots: cards,
    }
  }
  if (p === 'zhihu') {
    // 知乎的封面是它自己的横版配图；没有就退正文里第一张图，别拿会议海报母版顶替
    return {
      cover: find(posters, /poster-zhihu\.png$/) ?? videoCover ?? images(run, 'intake')[0],
      reader: readerFor(run, 'zhihu'),
      shots: [],
    }
  }
  if (p === 'bilibili') {
    // 成片或 B 站横屏封面，二选一得有 —— 都没有就不算「B 站上的那一件」
    const biliCover = find(posters, /poster-bili-cover\.png$/)
    if (!videoCover && !biliCover) return { shots: [] }
    return {
      cover: videoCover ?? biliCover,
      video: find(videos, /video\/video\.mp4$/) ?? videos[0],
      shots: [],
    }
  }
  if (p === 'x') {
    // 英文 thread 是「真出了才有」：没有 en 专属产物就不该凭空摆一件出来
    const en = TOKEN_RE.x
    const hasEn = (stageOf(run, 'article')?.artifacts ?? []).concat(posters).some((a) => en.test(a.path))
    if (!hasEn) return { shots: [] }
    // X 没有专属海报（poster 阶段只出主海报 + 小红书 / 知乎 / B 站三张）—— 用主海报当封面，不编一张
    return { cover: find(posters, /poster-en\.png$/) ?? mainPoster, reader: readerFor(run, en.source), shots: [] }
  }
  return { cover: mainPoster ?? videoCover, reader: readerFor(run, '.'), video: find(videos, /video\/video\.mp4$/), shots: cards }
}

/** 这个运行在这个平台上到底有没有东西可看 */
function lineupHas(l: Lineup): boolean {
  return !!(l.cover || l.reader || l.video || l.shots.length)
}

/** 运行声明的发布目标（xhs / zhihu / bilibili / x），别名归一到 PLATFORM_META.channel */
const TARGET_ALIAS: Record<string, string> = {
  xhs: 'xiaohongshu', xiaohongshu: 'xiaohongshu', redbook: 'xiaohongshu',
  bili: 'bilibili',
  twitter: 'x', 'x-com': 'x', en: 'x',
}

function targets(run: PaperRun): Set<string> {
  const ids = (run.config?.publish?.targets ?? []).map((t) => TARGET_ALIAS[(t || '').toLowerCase()] ?? t)
  return new Set(ids)
}

/* ---------------------------------------------------------------- 发布状态 */

const CHANNEL_LABEL: Record<PlatformId, string> = {
  xhs: '小红书', zhihu: '知乎', bilibili: 'B站', x: 'X（推特）', generic: '',
}

/** 发布阶段的检查项里写着「渠道状态：小红书 → 未登录」，这是最诚实的「为什么还没发」 */
function channelCheckNote(pub: Stage | undefined, p: PlatformId): string {
  const name = CHANNEL_LABEL[p]
  if (!pub || !name) return ''
  // 只看**没过**的那条：渠道状态检查通过时 detail 是「账号 YYDH（已登录）」，
  // 那不是「没就绪」的理由，别拿它当状态说明。
  const hit = (pub.checks ?? []).find((c) => c.label === '渠道状态：' + name && c.state === 'fail')
  return hit ? hit.detail : ''
}

function resolveState(run: PaperRun, p: PlatformId, rec?: ChannelReceipt): { state: WorkState; note: string; link: string } {
  if (rec) {
    const link = rec.url || ''
    const who = rec.account ? '账号 ' + rec.account : ''
    if (rec.status === 'published') return { state: 'published', note: who, link }
    if (rec.status === 'failed') return { state: 'failed', note: rec.error?.message || '投递没成功', link }
    if (rec.status === 'blocked') return { state: 'blocked', note: rec.error?.message || rec.state?.detail || '渠道当时不可用', link }
    if (rec.status === 'skipped') return { state: 'unpublished', note: rec.error?.message || '这一轮没有投它', link }
    // draft：素材包落了盘，但一次发布接口都没调
    return { state: 'draft', note: rec.state?.detail || '素材包已落在本地，等你去发', link }
  }

  const pub = stageOf(run, 'publish')
  if (pub?.status === 'waiting' && pub.gate && !pub.gate.resolved) {
    return { state: 'awaiting', note: channelCheckNote(pub, p) || '发布前要你点头，我不会自己发', link: '' }
  }
  if (pub?.status === 'running') return { state: 'awaiting', note: '正在投递', link: '' }
  if (pub?.status === 'failed') {
    // 发布这一步没跑成：先说清是哪个渠道当时不可用，而不是笼统的「失败」
    const why = channelCheckNote(pub, p)
    if (why) return { state: 'blocked', note: why, link: '' }
    // 这一步失败跟这个平台无关时别硬说「没跑完」——它只是这一轮没排到
    if (PLATFORM_META[p].channel && !targets(run).has(PLATFORM_META[p].channel)) {
      return { state: 'unpublished', note: '这一轮的发布目标里没有它', link: '' }
    }
    return { state: 'incomplete', note: '发布这一步没跑成，稿子本身是好的', link: '' }
  }
  if (pub?.status === 'done') {
    return { state: 'unpublished', note: '这一轮没排到它（回执里没有这个渠道）', link: '' }
  }
  if (run.status === 'failed') return { state: 'incomplete', note: '这次运行没跑完，发布没开始', link: '' }
  if (!pub || pub.status === 'pending') return { state: 'unpublished', note: '还没走到发布', link: '' }
  return { state: 'unpublished', note: '', link: '' }
}

/* ---------------------------------------------------------------- 组装 */

export interface Extras {
  /** run.id -> 发布回执总表 */
  receipts: Record<string, RunReceipts | null>
  /** run.id -> article/export/title.txt 的内容（回执没有时的兜底标题） */
  titles: Record<string, string>
}

export function buildWorks(runs: PaperRun[], extras: Extras): Work[] {
  const out: Work[] = []
  for (const run of runs) {
    const rec = extras.receipts[run.id] ?? null
    const goal = targets(run)
    let any = false

    for (const p of PLATFORM_ORDER) {
      const l = lineupFor(run, p)
      if (!lineupHas(l)) continue
      // 有专属产物、或是这一轮的发布目标，才算得上「这个平台的作品」；
      // 「跨平台」只在别处都没东西时兜底，免得同一张海报出现两遍。
      const mine = PLATFORM_META[p].channel === '' ? !any : goal.has(PLATFORM_META[p].channel) || isSpecific(run, p)
      if (!mine) continue
      any = true

      const channelId = PLATFORM_META[p].channel
      const channelRec = channelId ? rec?.channels?.[channelId] : undefined
      const { state, note, link } = resolveState(run, p, channelRec)

      const exportTitle = (extras.titles[run.id] ?? '').trim()
      const titleFrom: Work['titleFrom'] = channelRec?.title ? 'receipt' : exportTitle ? 'export' : 'paper'
      const title = (channelRec?.title || exportTitle || run.title).trim()

      const reader = l.reader
      const borrowed =
        p !== 'generic' && reader && !TOKEN_RE[p].test(reader.path)
          ? '这个平台没有专属文案，这份借的是「' + PLATFORM_META[platformTokenOf(reader.path)].label + '」的稿子'
          : ''

      out.push({
        key: run.id + ':' + p,
        run, platform: p,
        kind: l.video ? 'video' : 'article',
        title,
        titleFrom,
        variant: channelRec?.variant || '',
        borrowed,
        cover: l.cover,
        shots: l.shots,
        reader,
        video: l.video,
        state, note, link,
        stats: statsFor(run, p, l, channelRec),
        at: channelRec?.at ? channelRec.at * 1000 : Number(run.createdAt) || 0,
      })
    }
  }
  return out
}

/** 产物路径里带哪个平台的记号（借稿说明用） */
function platformTokenOf(path: string): PlatformId {
  const p = path.toLowerCase()
  if (/zhihu/.test(p)) return 'zhihu'
  if (/bili/.test(p)) return 'bilibili'
  if (/xhs|xiaohongshu/.test(p)) return 'xhs'
  if (TOKEN_RE.x.test(p)) return 'x'
  return 'generic'
}

/** 这个运行有没有这个平台的专属产物（而不是靠「发布目标」蹭上的） */
function isSpecific(run: PaperRun, p: PlatformId): boolean {
  const re = TOKEN_RE[p]
  const all = (stageOf(run, 'article')?.artifacts ?? []).concat(stageOf(run, 'poster')?.artifacts ?? [])
  return all.some((a) => re.test(a.path))
}

function statsFor(run: PaperRun, p: PlatformId, l: Lineup, rec?: ChannelReceipt): string[] {
  const out: string[] = []
  const vmeta = (l.video?.meta ?? {}) as Record<string, number>
  if (p === 'bilibili' && vmeta.durationSec) out.push(fmtDuration(Number(vmeta.durationSec)))

  const enWords = Number((l.reader?.meta || {}).words)
  if (p === 'x') {
    // 英文 thread 按词数说：回执里的 contentChars 是字符数，写成「字」会被读成中文篇幅
    if (enWords) out.push(enWords.toLocaleString('zh-CN') + ' 词')
    else if (rec?.contentChars) out.push(rec.contentChars.toLocaleString('zh-CN') + ' 字符')
  } else if (rec?.contentChars) out.push(rec.contentChars.toLocaleString('zh-CN') + ' 字')
  else if (p !== 'bilibili' && words(run)) out.push(words(run).toLocaleString('zh-CN') + ' 字')

  if (l.shots.length) out.push(l.shots.length + ' 张卡片')
  else if (rec?.imageCount) out.push(rec.imageCount + ' 张配图')
  else if (p === 'zhihu' && images(run, 'intake').length) out.push(images(run, 'intake').length + ' 张配图')

  const w = Number(vmeta.w ?? 0)
  const h = Number(vmeta.h ?? 0)
  if (p === 'bilibili' && w && h) out.push(w + '×' + h)
  return out.slice(0, 3)
}

/* ---------------------------------------------------------------- 分块 */

export function sectionsOf(works: Work[]): WorkSection[] {
  const out: WorkSection[] = []
  for (const p of PLATFORM_ORDER) {
    const list = works.filter((w) => w.platform === p).sort((x, y) => y.at - x.at)
    if (!list.length) continue
    const meta = PLATFORM_META[p]
    out.push({
      id: 'sec-' + p, label: meta.label, platform: p, unit: meta.unit, min: meta.min, ratio: meta.ratio,
      note: sectionNote(list), list,
    })
  }
  return out
}

/** 板块结论句：先说「发没发出去」，这是这一页最要紧的一句话 */
function sectionNote(list: Work[]): string {
  const n = list.length
  const pub = list.filter((w) => w.state === 'published').length
  const draft = list.filter((w) => w.state === 'draft').length
  const wait = list.filter((w) => w.state === 'awaiting' || w.state === 'blocked').length
  if (pub === n) return '全部发出去了'
  if (pub) return pub + ' 件发出去了，其余 ' + (n - pub) + ' 件还在本地'
  if (draft === n) return '都存成了草稿，等你去发'
  if (draft) return draft + ' 件已存草稿，' + (n - draft) + ' 件还没发'
  if (wait === n) return '等你确认后才发'
  if (wait) return wait + ' 件等你确认，其余还没发'
  return '都还没发出去'
}

/** 全页结论：平台数 / 件数 / 已发出 */
export function headline(works: Work[], sections: WorkSection[]): string {
  if (!works.length) return '跑一篇论文，文章、海报、视频会自动归到这里。'
  const pub = works.filter((w) => w.state === 'published').length
  const head = '已经做出来的 ' + works.length + ' 件稿子按平台摆在这儿（' + sections.length + ' 个平台）'
  if (!pub) return head + '：都还没发出去，素材包都在本地。'
  return head + '：' + pub + ' 件已经发出去了。'
}

export { relativeTime }
