<script setup lang="ts">
/**
 * 每日论文 · HuggingFace Daily Papers。
 *
 * 数据来自后端 `GET /api/hf-daily`（HF 官方 JSON 接口，按日期缓存）。每条里 `paper.id`
 * 就是 arXiv 编号，直接喂给我们的 intake —— 点「跑这篇」就按当前风格配置起一条 run。
 *
 * 只读榜单：这里不抓 PDF、不建 run，除非你点那一下。
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { HfDailyPaper, HfDailyResult } from '../api/types'
import { useChatStore } from '../stores/chat'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const runs = useRunsStore()
const chat = useChatStore()

const data = ref<HfDailyResult | null>(null)
const loading = ref(false)
const error = ref('')
/** 日期留空 = HF 的最新一批 */
const day = ref('')
/** 'day' = 按日期/最新；'trending' = HF 趋势榜 */
const mode = ref<'day' | 'trending'>('day')
const starting = ref('')          // 正在开跑的那篇 arxivId

onMounted(() => void load())

async function load(force = false) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    data.value = await api.hfDaily(day.value, mode.value === 'trending' ? 'trending' : '', force)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function setMode(m: 'day' | 'trending') {
  if (mode.value === m) return
  mode.value = m
  void load()
}

function setToday() {
  const d = new Date()
  day.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  void load()
}

const papers = computed(() => data.value?.papers ?? [])

function fmtAuthors(p: HfDailyPaper): string {
  const a = p.authors ?? []
  return a.length > 3 ? `${a.slice(0, 3).join('、')} 等 ${a.length} 人` : a.join('、')
}

function openUrl(url: string) {
  window.open(url, '_blank', 'noreferrer')
}

/** 点「跑这篇」：按当前风格/默认配置起一条 run，然后跳到工作台看进度 */
async function runIt(p: HfDailyPaper) {
  if (starting.value) return
  starting.value = p.arxivId
  try {
    await runs.submit(
      { kind: 'arxiv', value: p.arxivId, title: p.title },
      chat.runConfig(),
    )
    ui.setView('workbench')
    ui.toast(`已经起跑：${p.title.slice(0, 24)}…（去工作台看进度）`, 'info', 5000)
  } catch (e) {
    ui.toast('起跑失败：' + (e as Error).message, 'err', 6000)
  } finally {
    starting.value = ''
  }
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">每日论文</h1>
        <p class="page-lead">
          HuggingFace 的每日精选（Daily Papers），按点赞排序。挑一篇点「跑这篇」，就按当前风格把它做成小红书图文。
        </p>
      </div>
      <span class="meta-line">{{ loading ? '读取中…' : data ? `${data.count} 篇` : '' }}</span>
      <div class="seg sm">
        <button :class="{ on: mode === 'day' }" @click="setMode('day')">当日</button>
        <button :class="{ on: mode === 'trending' }" @click="setMode('trending')">趋势</button>
      </div>
      <input
        v-model="day"
        class="day"
        :disabled="mode === 'trending'"
        placeholder="日期 YYYY-MM-DD（留空=最新）"
        @keyup.enter="load()"
      />
      <button class="btn sm" :disabled="loading || mode === 'trending'" @click="setToday">今天</button>
      <button class="btn sm" :disabled="loading" @click="load(true)">刷新</button>
    </header>

    <p v-if="data?.stale" class="warn-line">
      抓不到 HuggingFace 的新数据，下面是缓存里上一次的结果<template v-if="data.error">（{{ data.error }}）</template>。
      本机要能出网（有代理时后端会走系统代理）。
    </p>
    <p v-if="error" class="err-line">
      读不到每日论文：{{ error }} —— 数据来自 <code>GET /api/hf-daily</code>。
    </p>

    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">
          {{ mode === 'trending' ? '榜单 · 趋势' : data?.date ? `榜单 · ${data.date}` : '榜单 · 最新' }}
        </span>
        <div class="grow" />
        <span class="panel-sub">数据源 huggingface.co/api/daily_papers · 缓存 6 小时</span>
      </header>
      <div class="panel-body">
        <p v-if="loading && !papers.length" class="src">正在拉榜单…</p>
        <ul v-else-if="papers.length" class="papers">
          <li v-for="(p, i) in papers" :key="p.arxivId" class="paper">
            <span class="rank">{{ i + 1 }}</span>
            <div class="grow info">
              <div class="row spread gap">
                <span class="ptitle">{{ p.title }}</span>
                <span v-if="p.upvotes != null" class="chip tiny">{{ p.upvotes }} 赞</span>
              </div>
              <p v-if="p.authors?.length" class="meta">{{ fmtAuthors(p) }}</p>
              <p v-if="p.summary" class="summary">{{ p.summary }}</p>
              <div class="row wrap gap links">
                <button class="link" @click="openUrl(p.arxivUrl)">arXiv:{{ p.arxivId }}</button>
                <button class="link" @click="openUrl(p.pdfUrl)">PDF</button>
                <button v-if="p.githubRepo" class="link" @click="openUrl(p.githubRepo)">代码</button>
              </div>
            </div>
            <button class="btn sm primary" :disabled="!!starting" @click="runIt(p)">
              {{ starting === p.arxivId ? '起跑中…' : '跑这篇' }}
            </button>
          </li>
        </ul>
        <p v-else-if="!loading" class="src">这一天没有拿到论文（换个日期，或点「今天」）。</p>
      </div>
    </section>

    <p class="foot-note">
      榜单只读；「跑这篇」会按你当前的风格配置（默认只做小红书）起一条 run。arXiv 编号即 <code>paper.id</code>。
    </p>
  </div>
</template>

<style scoped>
.page-head { flex-wrap: wrap; gap: 8px; }
.day { width: 210px; }
.meta-line { font-size: 12px; color: var(--muted-2); }
.err-line { color: var(--err); font-size: 12.5px; }
.warn-line {
  font-size: 12px; color: #b45309; background: rgba(245, 158, 11, 0.09);
  border: 1px solid rgba(245, 158, 11, 0.26); border-radius: 10px; padding: 8px 10px; line-height: 1.7;
}
.src { font-size: 12px; color: var(--muted-2); }

.papers { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.paper { display: flex; gap: 12px; align-items: flex-start; padding: 12px 2px; border-bottom: 1px solid var(--line-soft); }
.paper:last-child { border-bottom: none; }
.rank { flex: none; width: 24px; text-align: right; font-family: var(--mono); font-size: 12px; color: var(--muted-2); margin-top: 3px; }
.info { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.ptitle { font-family: var(--serif); font-size: 15px; color: var(--text); line-height: 1.4; }
.meta { font-size: 12px; color: var(--muted); }
.summary {
  font-size: 12.5px; color: var(--muted); line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.links { gap: 10px; margin-top: 2px; }
.link { font: inherit; font-size: 12px; color: var(--accent); background: none; border: none; padding: 0; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.foot-note { font-size: 12px; color: var(--muted-2); padding: 0 2px 8px; line-height: 1.7; }
.foot-note code { font-family: var(--mono); font-size: 11.5px; background: #f1f0ec; padding: 1px 5px; border-radius: 5px; }

@media (max-width: 720px) {
  .paper { flex-wrap: wrap; }
  .day { width: 100%; }
  .paper .btn { order: 3; }
}
</style>
