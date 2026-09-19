<script setup lang="ts">
/**
 * 作品库：**已经做出来的稿子，按平台摆出来**。
 *
 * 一件作品 = 一次运行里面向一个平台的那份稿子（见 data/works.ts）：
 *   · 卡片上直接放**真封面**（小红书那张 3:4 卡片、知乎横版配图、B 站 16:9 封面），
 *     B 站这一件同时给封面与成片；
 *   · 卡片右下角是**发布状态**（已发布 / 等你确认 / 存了草稿 / 没发成功），
 *     状态与「为什么是这个状态」都来自发布回执与发布阶段的检查项，不编；
 *   · 点开就是这一件本身：一篇文章（渲染后的正文）或一条视频（真播放器），
 *     右边一条窄栏说清状态、来源论文与可以做的动作。
 *
 * 原来的这一页是按「产物文件」罗列的（一张张 p1.png / video.mp4），用户看到的是文件，
 * 不是作品，所以这里改成以「平台上的那一件」为单位。
 */
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { assetUrl } from '../api'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'
import type { PaperRun, RunReceipts } from '../types'
import { PLATFORM_META, relativeTime } from '../data/library'
import { STATE_CHIP, buildWorks, headline, sectionsOf } from '../data/works'
import type { Extras, Work } from '../data/works'

const store = useRunsStore()
const ui = useUiStore()
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })

/* ---------------------------------------------------------------- 回执与标题 */

const extras = ref<Extras>({ receipts: {}, titles: {} })
const loading = ref(true)
const copyId = ref('')
let loadedKey = ''

function artifactUrl(run: PaperRun, stageId: string, re: RegExp): string {
  const art = (run.stages.find((s) => s.id === stageId)?.artifacts ?? []).find((a) => re.test(a.path))
  return art?.url ? assetUrl(art.url) : ''
}

/**
 * 每个运行拉两样小文件：发布回执总表（这件发了没有、投的是哪份标题）与待发布标题。
 * 回执读不到就不读 —— 状态退回「发布阶段走到哪一步」，标题退回论文标题，都是实话。
 */
async function loadExtras(runs: PaperRun[]) {
  const receipts: Record<string, RunReceipts | null> = {}
  const titles: Record<string, string> = {}
  await Promise.all(runs.map(async (run) => {
    const recUrl = artifactUrl(run, 'publish', /publish\/receipts\.json$/)
    if (recUrl) {
      try {
        const res = await fetch(recUrl)
        receipts[run.id] = res.ok ? ((await res.json()) as RunReceipts) : null
      } catch (e) { receipts[run.id] = null }
    } else {
      receipts[run.id] = null
    }
    // 待发布标题单独读一份：没有渠道的件（英文变体）拿不到回执里的标题，只能靠它
    const tUrl = artifactUrl(run, 'article', /article\/export\/title\.txt$/)
    if (!tUrl) return
    try {
      const res = await fetch(tUrl)
      if (res.ok) titles[run.id] = (await res.text()).trim()
    } catch (e) { /* 标题读不到就用论文标题兜底 */ }
  }))
  extras.value = { receipts, titles }
  loading.value = false
}

// 运行的 id 集合，或某个运行的发布产物数变化（刚投完/刚存草稿）时重读回执
const extrasKey = computed(() => store.runs
  .map((r) => r.id + ':' + ((r.stages.find((s) => s.id === 'publish')?.artifacts ?? []).length))
  .join('|'))

watch(extrasKey, (key) => {
  if (!key) { loading.value = false; return }
  if (key === loadedKey) return
  loadedKey = key
  void loadExtras(store.runs)
}, { immediate: true })

/* ---------------------------------------------------------------- 作品 */

const works = computed(() => buildWorks(store.runs, extras.value))
const sections = computed(() => sectionsOf(works.value))
const lead = computed(() => headline(works.value, sections.value))
const hasRuns = computed(() => store.runs.length > 0)

/**
 * 每个平台先摆最新的一批封面，更早的折成一行 —— 这台机器上跑过 20 多次，
 * 全铺开来是 40 多张长得差不多的封面，反而看不出「这次做出来了什么」。
 */
const FEATURED = 6
const unfolded = ref<Record<string, boolean>>({})
function visible(s: { id: string; list: Work[] }): Work[] {
  return unfolded.value[s.id] ? s.list : s.list.slice(0, FEATURED)
}
function olderOf(s: { list: Work[] }): Work[] { return s.list.slice(FEATURED) }
function toggleOlder(id: string) { unfolded.value = { ...unfolded.value, [id]: !unfolded.value[id] } }

function chipOf(w: Work) { return STATE_CHIP[w.state] }
function when(w: Work) { return relativeTime(w.at) }
function coverOf(w: Work) { return w.cover?.url ? assetUrl(w.cover.url) : '' }
function shelfStyle(s: { min: number }) {
  return { gridTemplateColumns: 'repeat(auto-fill, minmax(' + s.min + 'px, 1fr))' }
}

/** 封面加载失败（后端没导出这张图）时不摆一个破图，退回「这一件没有成图」 */
const broken = ref<Record<string, boolean>>({})
function onCoverError(w: Work) { if (w.cover) broken.value = { ...broken.value, [w.cover.id]: true } }
function coverOk(w: Work) { return !!w.cover?.url && !broken.value[w.cover.id] }

/* ---------------------------------------------------------------- 点开一件 */

const current = ref<Work | null>(null)
const bodyHtml = ref('')
const bodyState = ref<'idle' | 'loading' | 'error'>('idle')

const siblings = computed(() => current.value
  ? works.value.filter((w) => w.run.id === current.value!.run.id)
  : [])

watch(current, async (w) => {
  bodyHtml.value = ''
  bodyState.value = 'idle'
  if (!w?.reader?.url) return
  bodyState.value = 'loading'
  try {
    const res = await fetch(assetUrl(w.reader.url))
    if (!res.ok) throw new Error(String(res.status))
    const text = await res.text()
    // 纯文本导出的稿件没有 markdown 结构，按空行切段，别挤成一坨
    const body = w.reader.kind === 'markdown'
      ? text
      : text.split(/\n+/).map((l) => l.trim()).filter(Boolean).join('\n\n')
    bodyHtml.value = md.render(body)
    bodyState.value = 'idle'
  } catch (e) {
    bodyState.value = 'error'
  }
})

function open(w: Work) {
  current.value = w
  ui.openArtifact(w.reader ? w.reader.stageId : 'video', w.reader?.id || w.video?.id || w.cover?.id || '')
}
function close() { current.value = null; bodyHtml.value = ''; bodyState.value = 'idle' }

function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && current.value) close() }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function gotoRun(w: Work) {
  store.select(w.run.id)
  ui.setView('workbench')
  void ui.toast('已切到「工作台」的这次运行：' + w.run.title, 'info')
}

async function copyPath(text: string) {
  try { await navigator.clipboard.writeText(text) } catch (e) { /* 剪贴板不可用时路径在详情里能选中 */ }
  copyId.value = text
  window.setTimeout(() => { if (copyId.value === text) copyId.value = '' }, 1600)
}

function jump(id: string) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const TITLE_FROM: Record<Work['titleFrom'], string> = {
  receipt: '这个渠道实际投递的标题',
  export: '这一轮待发布的标题',
  paper: '论文原标题（还没生成平台标题）',
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">作品库</h1>
        <p class="page-lead">
          {{ lead }}
          <span v-if="loading && hasRuns" class="quiet">正在核对发布回执…</span>
        </p>
      </div>
    </header>

    <nav v-if="sections.length > 1" class="jump">
      <button v-for="s in sections" :key="s.id" class="jump-item" @click="jump(s.id)">
        {{ s.label }}<span class="mono jump-n">{{ s.list.length }}</span>
      </button>
    </nav>

    <div v-if="loading && hasRuns && !sections.length" class="panel reading">
      正在读这一批作品的封面与发布回执…
    </div>

    <section v-for="s in sections" :id="s.id" :key="s.id" class="panel sec">
      <header class="panel-head">
        <h2 class="panel-title">{{ s.label }}</h2>
        <span class="sec-unit">{{ s.list.length }} {{ s.unit }}</span>
        <div class="grow" />
        <span class="sec-note">{{ s.note }}</span>
      </header>

      <div class="shelf" :style="shelfStyle(s)">
        <article
          v-for="w in visible(s)"
          :key="w.key"
          class="work"
          :class="'ratio-' + s.platform"
          role="button"
          tabindex="0"
          :aria-label="w.title"
          @click="open(w)"
          @keydown.enter.prevent="open(w)"
          @keydown.space.prevent="open(w)"
        >
          <div class="shot">
            <img
              v-if="coverOk(w)"
              :src="coverOf(w)"
              :alt="s.label + '封面：' + w.title"
              loading="lazy"
              @error="onCoverError(w)"
            />
            <div v-else class="blank">
              <span class="blank-k">{{ s.label }}</span>
              <span class="blank-t">{{ w.kind === 'video' ? '这一条只有成片' : '这一件没有成图' }}</span>
            </div>
          </div>

          <div class="work-body">
            <h3 class="work-title">{{ w.title }}</h3>
            <p v-if="w.stats.length || when(w)" class="work-meta">
              <span v-if="w.stats.length">{{ w.stats.join(' · ') }}</span>
              <span v-if="w.stats.length && when(w)" class="dot-sep">·</span>
              <span v-if="when(w)">{{ when(w) }}</span>
            </p>
            <div class="work-foot">
              <span class="chip tiny" :class="chipOf(w).cls"><i class="dot" />{{ chipOf(w).label }}</span>
              <span class="grow" />
              <span class="work-kind">{{ w.kind === 'video' ? '看片' : '读稿' }}</span>
            </div>
          </div>
        </article>
      </div>

      <div v-if="olderOf(s).length" class="older">
        <button class="older-t" @click="toggleOlder(s.id)">
          {{ unfolded[s.id] ? '收起更早的' : '更早的 ' + olderOf(s).length + ' 件还在本地 · 展开看' }}
        </button>
        <ul v-if="unfolded[s.id]" class="older-list">
          <li v-for="w in olderOf(s)" :key="w.key">
            <button class="older-row" @click="open(w)">
              <span class="older-title">{{ w.title }}</span>
              <span class="chip tiny" :class="chipOf(w).cls"><i class="dot" />{{ chipOf(w).label }}</span>
              <span class="older-stats">{{ w.stats.join(' · ') }}</span>
              <span class="older-when">{{ when(w) }}</span>
            </button>
          </li>
        </ul>
      </div>
    </section>

    <div v-if="!sections.length && !loading" class="panel empty">
      <p class="empty-t">作品库还是空的</p>
      <p class="panel-sub">跑一篇论文，文章、海报、视频会按平台自动归到这里；这里看到的封面就是它们真正长出来的样子。</p>
      <button class="btn primary" @click="ui.setView('workbench')">去工作台跑一篇</button>
    </div>

    <!-- ---------------- 点开一件：一篇文章 / 一条视频 + 一条状态栏 ---------------- -->
    <Teleport to="body">
      <div v-if="current" class="dlg" @click.self="close">
        <div class="dlg-box" role="dialog" aria-modal="true" :aria-label="current.title">
          <header class="dlg-head">
            <div class="grow">
              <h2 class="dlg-title">{{ current.title }}</h2>
              <p class="dlg-sub">
                {{ PLATFORM_META[current.platform].label }} · {{ current.kind === 'video' ? '视频' : '文章' }}
                <template v-if="when(current)"> · {{ when(current) }}</template>
                · 来自《{{ current.run.title }}》
              </p>
            </div>
            <span class="chip" :class="chipOf(current).cls"><i class="dot" />{{ chipOf(current).label }}</span>
            <button class="mini" @click="close">关闭 · Esc</button>
          </header>

          <div class="dlg-body">
            <div class="detail">
              <div class="preview">
                <video
                  v-if="current.video?.url"
                  class="player"
                  :src="assetUrl(current.video.url)"
                  :poster="coverOf(current)"
                  controls
                  playsinline
                  preload="metadata"
                />

                <div v-if="current.shots.length" class="stills">
                  <a
                    v-for="(s, i) in current.shots"
                    :key="s.id"
                    class="still"
                    :href="assetUrl(s.url)"
                    target="_blank"
                    rel="noreferrer"
                    :title="'打开第 ' + (i + 1) + ' 张原图'"
                  >
                    <img :src="assetUrl(s.url)" :alt="'第 ' + (i + 1) + ' 张：' + s.label" loading="lazy" />
                    <span class="still-n mono">{{ i + 1 }}</span>
                  </a>
                </div>

                <div v-if="bodyState === 'loading'" class="preview-note">正在读这份稿子…</div>
                <div v-else-if="bodyState === 'error'" class="preview-note">
                  这份稿子读不出来（可能还没导出）。路径：<span class="mono">{{ current.reader?.path }}</span>
                </div>
                <article v-else-if="bodyHtml" class="reader prose" v-html="bodyHtml" />

                <div v-else-if="!current.video" class="preview-note">
                  这一件只有成图，没有可读的正文 —— 上面那些图就是它。
                </div>
              </div>

              <aside class="side">
                <div class="side-block">
                  <div class="label">发布状态</div>
                  <span class="chip" :class="chipOf(current).cls"><i class="dot" />{{ chipOf(current).label }}</span>
                  <p class="side-note">{{ current.note || '这一件还没有发布记录。' }}</p>
                  <a v-if="current.link" class="btn sm" :href="current.link" target="_blank" rel="noreferrer">去平台上看看</a>
                  <button
                    v-else-if="current.state === 'draft' || current.state === 'blocked' || current.state === 'awaiting'"
                    class="btn sm"
                    @click="ui.setView('platforms'); close()"
                  >去平台账号看看登录态</button>
                </div>

                <div class="side-block">
                  <div class="label">这一件</div>
                  <ul class="kv">
                    <li v-if="current.stats.length"><span>体量</span><b>{{ current.stats.join(' · ') }}</b></li>
                    <li v-if="current.cover"><span>封面</span><b>{{ current.cover.label }}</b></li>
                    <li v-if="current.video"><span>成片</span><b>{{ current.video.label }}</b></li>
                    <li v-if="current.variant"><span>文案</span><b class="mono">{{ current.variant }}</b></li>
                    <li><span>标题</span><b>{{ TITLE_FROM[current.titleFrom] }}</b></li>
                  </ul>
                  <p v-if="current.borrowed" class="side-note">{{ current.borrowed }}</p>
                </div>

                <div class="side-block">
                  <div class="label">动作</div>
                  <div class="acts">
                    <a v-if="current.reader?.url" class="btn sm" :href="assetUrl(current.reader.url)" target="_blank" rel="noreferrer">打开原稿</a>
                    <a v-if="current.video?.url" class="btn sm" :href="assetUrl(current.video.url)" target="_blank" rel="noreferrer">打开成片</a>
                    <button v-if="current.cover" class="btn sm" @click="copyPath(current.cover.path)">
                      {{ copyId === current.cover.path ? '已复制' : '复制封面路径' }}
                    </button>
                    <button class="btn sm" @click="gotoRun(current)">在运行里打开</button>
                  </div>
                </div>

                <div v-if="siblings.length > 1" class="side-block">
                  <div class="label">同一批的其它件</div>
                  <div class="sibs">
                    <button
                      v-for="s in siblings"
                      :key="s.key"
                      class="pill"
                      :class="{ on: s.key === current.key }"
                      @click="open(s)"
                    >
                      {{ PLATFORM_META[s.platform].label }} · {{ s.kind === 'video' ? '视频' : '文章' }}
                    </button>
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.grow { flex: 1; min-width: 0; }
/* 小字专用墨色：--ink-4 / --ink-3 在白底上过不了 4.5:1，这里用一个 5.4:1 的灰 */
.page, .dlg { --small-ink: #6b6963; }
.quiet { color: var(--small-ink); }

/* 平台跳转：一眼看到有几个平台、各几件 */
.jump { display: flex; flex-wrap: wrap; gap: 6px; margin: -8px 0 -4px; }
.jump-item {
  display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 12.5px;
  padding: 4px 10px; border: 1px solid var(--hairline); border-radius: 999px;
  background: var(--surface); color: var(--ink-2); cursor: pointer; transition: 0.15s;
}
.jump-item:hover { border-color: var(--ink-4); color: var(--ink); }
.jump-item:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.jump-n { font-size: 11px; color: var(--small-ink); }

.sec { scroll-margin-top: 14px; }
.sec-unit { font-size: 12.5px; color: var(--small-ink); }
.sec-note { font-size: 12.5px; color: var(--small-ink); }
.reading { padding: 22px 20px; color: var(--small-ink); font-size: 13.5px; }

/* ---------- 封面墙：格子宽度跟着平台自己的封面比例走 ---------- */
.shelf { display: grid; gap: 16px; padding: 18px 20px 22px; }

.work {
  display: flex; flex-direction: column; overflow: hidden; text-align: left;
  border: 1px solid var(--hairline); border-radius: var(--radius); background: var(--surface);
  cursor: pointer; transition: border-color 0.15s, transform 0.15s;
}
.work:hover { border-color: var(--ink-4); transform: translateY(-1px); }
.work:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.shot { position: relative; background: var(--surface-2); border-bottom: 1px solid var(--hairline); }
.ratio-xhs .shot { aspect-ratio: 3 / 4; }
.ratio-zhihu .shot { aspect-ratio: 4 / 3; }
.ratio-bilibili .shot { aspect-ratio: 16 / 9; }
.ratio-generic .shot { aspect-ratio: 3 / 2; }
.shot img { width: 100%; height: 100%; object-fit: cover; display: block; }
/* 小红书没有 3:4 卡片时会退到竖长图（1080×2400）：从上往下裁，标题那块才留得住 */
.ratio-xhs .shot img { object-position: center top; }

.blank { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 16px; }
.blank-k { font-family: var(--serif); font-size: 16px; color: var(--ink-3); }
.blank-t { font-size: 11.5px; color: var(--small-ink); }

.work-body { display: flex; flex-direction: column; gap: 7px; padding: 12px 13px 11px; }
.work-title {
  font-family: var(--serif); font-size: 15px; font-weight: 500; line-height: 1.45; color: var(--ink);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.work-meta { font-size: 11.5px; color: var(--small-ink); display: flex; flex-wrap: wrap; gap: 5px; align-items: baseline; }
.dot-sep { color: var(--ink-4); }
.work-foot { display: flex; align-items: center; gap: 8px; margin-top: 2px; }
.work-kind { font-size: 11px; color: var(--small-ink); }

/* 更早的那些件：一行一件，不用封面再占一遍地方 */
.older { padding: 0 20px 18px; }
.older-t {
  font: inherit; font-size: 12.5px; color: var(--small-ink); padding: 6px 0; cursor: pointer;
}
.older-t:hover { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }
.older-list { list-style: none; margin: 4px 0 0; padding: 0; border-top: 1px solid var(--line-soft); }
.older-list li { border-bottom: 1px solid var(--line-soft); }
.older-row {
  display: flex; align-items: center; gap: 12px; width: 100%; padding: 9px 2px;
  font: inherit; text-align: left; cursor: pointer;
}
.older-row:hover { background: var(--surface-2); }
.older-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.older-title { flex: 1; min-width: 0; font-family: var(--serif); font-size: 13.5px; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.older-stats, .older-when { font-size: 11.5px; color: var(--small-ink); white-space: nowrap; }
.older-when { min-width: 62px; text-align: right; }

.empty-t { font-family: var(--serif); font-size: 16px; }

/* ---------- 点开的详情：左边真身，右边状态 ---------- */
.dlg {
  position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center;
  padding: 30px; background: rgba(17, 17, 17, 0.34); backdrop-filter: blur(2px);
}
.dlg-box {
  display: flex; flex-direction: column; width: min(1220px, 100%); height: min(90vh, 100%); overflow: hidden;
  background: var(--surface); border: 1px solid var(--hairline); border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
}
.dlg-head { display: flex; align-items: flex-start; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--hairline); }
.dlg-title { font-family: var(--serif); font-size: 17px; line-height: 1.35; }
.dlg-sub { font-size: 12.5px; color: var(--small-ink); margin-top: 3px; }
.dlg-body { flex: 1; min-height: 0; overflow: auto; }

.detail { display: grid; grid-template-columns: minmax(0, 1fr) 274px; align-items: start; }
.preview { min-width: 0; }
.player { display: block; width: 100%; max-height: 62vh; background: #000; }

/* 真卡片：小红书那几张 1080×1440，按原样摆出来，点开看原图 */
.stills { display: flex; gap: 12px; padding: 16px 20px 4px; overflow-x: auto; border-bottom: 1px solid var(--hairline); }
.still { position: relative; flex: none; height: 330px; border: 1px solid var(--hairline); border-radius: 10px; overflow: hidden; background: var(--surface-2); }
.still img { height: 100%; width: auto; display: block; }
.still-n { position: absolute; left: 8px; bottom: 6px; font-size: 11px; color: #fff; background: rgba(17, 17, 17, 0.55); border-radius: 999px; padding: 1px 8px; }

.reader { padding: 20px 24px 34px; max-width: 72ch; font-size: 15px; line-height: 1.9; color: var(--ink-2); }
.reader :deep(h1) { font-size: 22px; margin: 0 0 14px; }
.reader :deep(h2) { font-size: 18px; margin: 24px 0 10px; }
.reader :deep(h3) { font-size: 15.5px; margin: 20px 0 8px; }
.reader :deep(p) { margin: 0 0 12px; }
.reader :deep(ul), .reader :deep(ol) { margin: 0 0 12px; padding-left: 22px; }
.reader :deep(li) { margin: 4px 0; }
.reader :deep(code) { font-family: var(--mono); font-size: 13px; background: var(--panel-3); padding: 1px 6px; border-radius: 5px; }
.reader :deep(blockquote) { margin: 12px 0; padding: 2px 0 2px 14px; border-left: 2px solid var(--hairline); color: var(--ink-3); }
.reader :deep(a) { color: var(--accent); }
.preview-note { padding: 20px 24px; font-size: 13px; color: var(--small-ink); }

.side { border-left: 1px solid var(--hairline); background: var(--surface-2); padding: 18px; display: flex; flex-direction: column; gap: 18px; }
.side-block { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.side-note { font-size: 12.5px; color: var(--small-ink); line-height: 1.7; }
.kv { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; width: 100%; }
.kv li { display: flex; gap: 10px; font-size: 12.5px; align-items: baseline; }
.kv span { flex: none; width: 42px; color: var(--small-ink); }
.kv b { font-weight: 400; color: var(--ink-2); word-break: break-word; }
.acts { display: flex; flex-wrap: wrap; gap: 7px; }
.sibs { display: flex; flex-wrap: wrap; gap: 6px; }

.mini {
  font: inherit; font-size: 11.5px; color: var(--ink-3); background: none; border: 0;
  padding: 2px 3px; cursor: pointer; text-decoration: none; white-space: nowrap;
}
.mini:hover { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }

@media (max-width: 1180px) {
  .detail { grid-template-columns: minmax(0, 1fr); }
  .side { border-left: 0; border-top: 1px solid var(--hairline); }
  .still { height: 240px; }
}
@media (max-width: 720px) {
  .dlg { padding: 0; }
  .dlg-box { height: 100%; width: 100%; border-radius: 0; border: 0; }
}
</style>
