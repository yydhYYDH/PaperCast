<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Component } from 'vue'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'
import type { Artifact, PaperRun, Stage } from '../types'
import ArticleViewer from '../components/viewers/ArticleViewer.vue'
import DigestViewer from '../components/viewers/DigestViewer.vue'
import PosterViewer from '../components/viewers/PosterViewer.vue'
import PublishViewer from '../components/viewers/PublishViewer.vue'
import VideoViewer from '../components/viewers/VideoViewer.vue'
import {
  KIND_META, MATERIAL_STAGES, PLATFORM_META, PLATFORM_ORDER,
  aspectOf, platformOf, relativeTime, shapeRank, volumeChips,
} from '../data/library'
import type { PlatformId } from '../data/library'

const store = useRunsStore()
const ui = useUiStore()

interface Item { a: Artifact; run: PaperRun; stage: Stage; ts: number; platform: PlatformId }

/** 全部产物拍平，带上来龙去脉：哪次运行、哪个阶段、什么时候出的、归哪个平台。 */
const items = computed<Item[]>(() => {
  const out: Item[] = []
  for (const run of store.runs) {
    for (const stage of run.stages) {
      for (const a of stage.artifacts) {
        out.push({ a: a, run: run, stage: stage, ts: Number(run.createdAt) || 0, platform: platformOf(a) })
      }
    }
  }
  return out.sort((x, y) => y.ts - x.ts)
})

interface Section { id: string; label: string; hint: string; items: Item[] }

/**
 * 板块 = 平台（用户定的轴，不按运行分），板块内按时间倒序。
 * 素材与中间产物单独放最后一块 —— 否则源论文的 8 张插图会淹没真正的作品。
 */
const sections = computed<Section[]>(() => {
  const works = items.value.filter((i) => MATERIAL_STAGES.indexOf(i.stage.id) < 0)
  const mats = items.value.filter((i) => MATERIAL_STAGES.indexOf(i.stage.id) >= 0)
  const out: Section[] = []
  for (const p of PLATFORM_ORDER) {
    const mine = byKind(works.filter((i) => i.platform === p))
    if (mine.length) out.push({ id: 'sec-' + p, label: PLATFORM_META[p].label, hint: PLATFORM_META[p].hint, items: mine })
  }
  if (mats.length) {
    out.push({
      id: 'sec-source', label: '素材与中间产物',
      hint: '源论文、解析正文、插图与事实源 —— 上面那些作品都是它们长出来的',
      items: byKind(mats),
    })
  }
  return out
})

/** 板块内先分「看的东西 / 读的东西 / 机器文件」，各层内再按时间倒序。 */
function byKind(list: Item[]): Item[] {
  return list.slice().sort((x, y) => (shapeRank(x.a.kind) - shapeRank(y.a.kind)) || (y.ts - x.ts))
}

const total = computed(() => items.value.length)
const runCount = computed(() => new Set(items.value.map((i) => i.run.id)).size)
const latestAt = computed(() => (items.value.length ? relativeTime(items.value[0].ts) : ''))

// ---------------------------------------------------------------- 详情

const openId = ref('')
const detail = computed<Item | null>(() => items.value.filter((i) => i.a.id === openId.value)[0] || null)

const VIEWERS: Record<string, Component> = {
  article: ArticleViewer,
  poster: PosterViewer,
  video: VideoViewer,
  publish: PublishViewer,
  understand: DigestViewer,
}

function viewerFor(stageId: string): Component | null {
  return VIEWERS[stageId] || null
}

function show(i: Item) { openId.value = i.a.id }
function close() { openId.value = '' }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function gotoWorkbench(i: Item) {
  store.select(i.run.id)
  ui.openArtifact(i.stage.id, i.a.id)
  ui.setView('workbench')
}

const copiedId = ref('')
async function copyPath(i: Item) {
  try { await navigator.clipboard.writeText(i.a.path) } catch (e) { /* 剪贴板不可用就静默：路径在详情里能选中 */ }
  copiedId.value = i.a.id
  window.setTimeout(() => { if (copiedId.value === i.a.id) copiedId.value = '' }, 1600)
}

function jump(id: string) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function strip(i: Item) {
  const r = aspectOf(i.a)
  const w = Math.min(52, Math.max(12, 20 * r))
  const h = Math.max(9, Math.min(34, w / r))
  return { width: w.toFixed(1) + 'px', height: h.toFixed(1) + 'px' }
}

function kindOf(a: Artifact) { return KIND_META[a.kind] }
function volume(a: Artifact) { return volumeChips(a) }
function when(i: Item) { return relativeTime(i.ts) }
function dur(a: Artifact) {
  const n = Number((a.meta || {}).durationSec)
  return n ? Math.floor(Math.round(n) / 60) + ':' + String(Math.round(n) % 60).padStart(2, '0') : ''
}
function pending(a: Artifact) { return !!(a.meta || {}).pending }
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">作品库</h1>
        <p class="page-lead">
          跑出来的东西都在这儿：按平台分板块，板块内从新到旧。
          <template v-if="total">共 {{ total }} 件，来自 {{ runCount }} 次运行，最近一次在{{ latestAt }}。</template>
          <template v-else>先跑一篇，文章、海报、视频会自动归到对应平台。</template>
        </p>
      </div>
    </header>

    <nav v-if="sections.length" class="rail">
      <button v-for="s in sections" :key="s.id" class="rail-item" @click="jump(s.id)">
        {{ s.label }}<span class="rail-n mono">{{ s.items.length }}</span>
      </button>
    </nav>

    <section v-for="s in sections" :id="s.id" :key="s.id" class="panel sec">
      <header class="panel-head">
        <h2 class="panel-title">{{ s.label }}</h2>
        <span class="panel-sub">{{ s.hint }}</span>
        <div class="grow" />
        <span class="count mono">{{ s.items.length }}</span>
      </header>

      <div class="cards">
        <article
          v-for="i in s.items"
          :key="i.a.id"
          class="card"
          :class="'shape-' + kindOf(i.a).shape"
          @click="show(i)"
        >
          <div class="card-top">
            <span class="strip" :style="strip(i)" />
            <span class="tag" :class="'tone-' + kindOf(i.a).tone">{{ kindOf(i.a).label }}</span>
            <span v-if="dur(i.a)" class="tag mono">{{ dur(i.a) }}</span>
            <span v-if="pending(i.a)" class="tag tone-amber">待渲染</span>
            <span v-else-if="!i.a.url" class="tag">未导出</span>
            <span class="grow" />
            <span class="when">{{ when(i) }}</span>
          </div>

          <button class="card-title" @click.stop="show(i)">{{ i.a.label }}</button>

          <div class="card-foot">
            <span v-for="v in volume(i.a)" :key="v" class="vol">{{ v }}</span>
            <span class="grow" />
            <a v-if="i.a.url" class="mini" :href="i.a.url" target="_blank" rel="noreferrer" @click.stop>原文件</a>
            <button class="mini" @click.stop="copyPath(i)">{{ copiedId === i.a.id ? '已复制' : '复制路径' }}</button>
            <button class="mini" @click.stop="gotoWorkbench(i)">在运行里</button>
          </div>
        </article>
      </div>
    </section>

    <div v-if="!total" class="panel empty">
      <p class="empty-t">作品库还是空的</p>
      <p class="panel-sub">跑一篇论文，文章、海报、视频会按平台自动归到这里。</p>
      <button class="btn primary" @click="ui.setView('workbench')">去工作台跑一篇</button>
    </div>

    <Teleport to="body">
      <div v-if="detail" class="dlg" @click.self="close">
        <div class="dlg-box" role="dialog" aria-modal="true" :aria-label="detail.a.label">
          <header class="dlg-head">
            <div class="grow">
              <h2 class="dlg-title">{{ detail.a.label }}</h2>
              <p class="dlg-sub">
                {{ PLATFORM_META[detail.platform].label }} · {{ detail.run.title
                }}<template v-if="when(detail)"> · {{ when(detail) }}</template>
              </p>
            </div>
            <button class="mini" @click="close">关闭 · Esc</button>
          </header>

          <div class="dlg-body">
            <component v-if="viewerFor(detail.stage.id)" :is="viewerFor(detail.stage.id)" :run="detail.run" />
            <div v-else class="dlg-plain">
              <p class="panel-sub">这类产物没有内置预览，用下面的按钮看原文件。</p>
              <p class="mono path">{{ detail.a.path }}</p>
            </div>
          </div>

          <footer class="dlg-foot">
            <a v-if="detail.a.url" class="btn" :href="detail.a.url" target="_blank" rel="noreferrer">打开原文件</a>
            <a v-if="detail.a.url" class="btn" :href="detail.a.url" download>下载</a>
            <button class="btn" @click="copyPath(detail)">{{ copiedId === detail.a.id ? '已复制' : '复制路径' }}</button>
            <span class="grow" />
            <button class="btn primary" @click="gotoWorkbench(detail)">在运行里打开</button>
          </footer>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.grow { flex: 1; min-width: 0; }

/* 板块导航：一眼看到有几个平台、各几件 */
.rail { display: flex; flex-wrap: wrap; gap: 6px; margin: -8px 0 -4px; }
.rail-item {
  display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 12.5px;
  padding: 4px 10px; border: 1px solid var(--hairline); border-radius: 999px;
  background: var(--surface); color: var(--ink-2); cursor: pointer; transition: 0.15s;
}
.rail-item:hover { border-color: var(--ink-4); color: var(--ink); }
.rail-item:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.rail-n { font-size: 11px; color: var(--ink-4); }

.sec { scroll-margin-top: 14px; }
.count { font-size: 12px; color: var(--ink-3); }

.cards {
  display: grid; gap: 12px; padding: 16px 20px 20px;
  grid-template-columns: repeat(auto-fill, minmax(292px, 1fr));
}
/* 文本与数据不跟海报挤同一格：通栏，读起来才不费劲 */
.card.shape-doc, .card.shape-data { grid-column: 1 / -1; }

.card {
  display: flex; flex-direction: column; gap: 8px; padding: 12px 13px;
  border: 1px solid var(--hairline); border-radius: var(--radius);
  background: var(--surface); cursor: pointer; transition: border-color 0.15s, transform 0.15s;
}
.card:hover { border-color: var(--ink-4); transform: translateY(-1px); }
.card:has(.card-title:focus-visible) { border-color: var(--accent); }

.card-top { display: flex; align-items: center; gap: 7px; }
/* 按真实宽高比画的小条：横版 / 竖长图 / 16:9 一眼能分出来，不是装饰 */
.strip { display: inline-block; flex: none; border: 1px solid var(--ink-4); border-radius: 2px; background: var(--surface-2); }

.tag {
  font-size: 10.5px; line-height: 1.6; padding: 0 7px; border-radius: 999px;
  background: var(--panel-3); color: var(--ink-3); white-space: nowrap;
}
.tone-red { background: var(--tone-red-bg); color: var(--tone-red-fg); }
.tone-blue { background: var(--tone-blue-bg); color: var(--tone-blue-fg); }
.tone-green { background: var(--tone-green-bg); color: var(--tone-green-fg); }
.tone-amber { background: var(--tone-amber-bg); color: var(--tone-amber-fg); }
.when { font-size: 11px; color: var(--ink-4); white-space: nowrap; }

.card-title {
  font: inherit; font-size: 13.5px; font-weight: 500; line-height: 1.45; text-align: left;
  color: var(--ink); background: none; border: 0; padding: 0; cursor: pointer;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.card-title:hover { text-decoration: underline; text-underline-offset: 3px; }

.card-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.vol { font-size: 11px; color: var(--ink-3); background: var(--surface-2); border: 1px solid var(--hairline); border-radius: 6px; padding: 1px 6px; }

.mini {
  font: inherit; font-size: 11.5px; color: var(--ink-3); background: none; border: 0;
  padding: 2px 3px; cursor: pointer; text-decoration: none; white-space: nowrap;
}
.mini:hover { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }

.empty { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 22px 20px; }
.empty-t { font-family: var(--serif); font-size: 16px; }

.path { color: var(--ink-4); font-size: 11px; word-break: break-all; }

/* 详情：点开才出现，复用工作台已有的 viewer，不另做一套预览 */
.dlg {
  position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center;
  padding: 34px; background: rgba(17, 17, 17, 0.34); backdrop-filter: blur(2px);
}
.dlg-box {
  display: flex; flex-direction: column; width: min(1080px, 100%); max-height: 100%; overflow: hidden;
  background: var(--surface); border: 1px solid var(--hairline); border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
}
.dlg-head { display: flex; align-items: flex-start; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--hairline); }
.dlg-title { font-family: var(--serif); font-size: 17px; line-height: 1.35; }
.dlg-sub { font-size: 12.5px; color: var(--ink-3); margin-top: 3px; }
.dlg-body { overflow: auto; }
.dlg-plain { padding: 20px; }
.dlg-foot { display: flex; align-items: center; gap: 8px; padding: 12px 20px; border-top: 1px solid var(--hairline); background: var(--surface-2); }
</style>
