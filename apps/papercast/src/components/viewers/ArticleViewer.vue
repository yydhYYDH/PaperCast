<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import type { Artifact, PaperRun } from '../../types'
import { assetUrl } from '../../api'

const props = defineProps<{ run: PaperRun }>()

const md = new MarkdownIt({ html: false, linkify: true, breaks: false })

const variants = computed(() =>
  props.run.stages.find((s) => s.id === 'article')?.artifacts.filter((a) => a.kind === 'markdown') ?? [],
)
const current = ref<Artifact | null>(null)
const source = ref('')
const loading = ref(false)
const mode = ref<'reader' | 'wechat' | 'cards'>('reader')

watch(
  variants,
  (list) => {
    if (!current.value || !list.find((a) => a.id === current.value!.id)) current.value = list[0] ?? null
  },
  { immediate: true },
)

watch(
  current,
  async (a) => {
    source.value = ''
    if (!a?.url) return
    loading.value = true
    try {
      const res = await fetch(assetUrl(a.url))
      source.value = await res.text()
    } catch {
      source.value = '> 示例文件未找到'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

/** 公式先以 TeX 源码呈现，接后端后换成 KaTeX 渲染 */
const rendered = computed(() => {
  const html = md.render(source.value)
  return html
    .replace(/\$\$([\s\S]+?)\$\$/g, (_m, tex) => `<div class="texblock"><span class="tex-tag">TeX</span>${escapeHtml(tex.trim())}</div>`)
    .replace(/\$([^$\n]+?)\$/g, (_m, tex) => `<code class="tex-inline">${escapeHtml(tex.trim())}</code>`)
})

function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const isXhs = computed(() => current.value?.id.includes('xhs') ?? false)

/** 小红书：按「第N张」拆卡 */
const cards = computed(() => {
  const parts = source.value.split(/\n(?=##\s*第)/).filter((p) => p.trim())
  const tags = parts.length ? (parts[parts.length - 1]!.match(/^#[^\n]*/m)?.[0] ?? '') : ''
  return parts.map((p) => {
    const lines = p.split('\n').filter((l) => l.trim())
    const head = (lines[0] ?? '').replace(/^##\s*/, '')
    return { head, body: lines.slice(1).join('\n') }
  }).filter((c) => c.head.startsWith('第'))
    .map((c) => ({ ...c, body: c.body.replace(/^#[^\n]*/gm, '').trim(), }))
    .concat(tags ? [{ head: '话题标签', body: tags }] : [])
})

const words = computed(() => source.value.replace(/\s/g, '').length)

watch(isXhs, (v) => { mode.value = v ? 'cards' : 'reader' }, { immediate: true })
</script>

<template>
  <div class="article">
    <div class="toolbar">
      <div class="tabbar">
        <button
          v-for="a in variants"
          :key="a.id"
          :class="{ on: current?.id === a.id }"
          @click="current = a"
        >
          {{ a.label }}
        </button>
      </div>
      <div class="grow" />
      <div class="seg sm">
        <button :class="{ on: mode === 'reader' }" @click="mode = 'reader'">阅读</button>
        <button v-if="!isXhs" :class="{ on: mode === 'wechat' }" @click="mode = 'wechat'">手机预览</button>
        <button v-if="isXhs" :class="{ on: mode === 'cards' }" @click="mode = 'cards'">卡片</button>
      </div>
    </div>

    <div v-if="!variants.length" class="empty">文章阶段尚未产出</div>
    <div v-else-if="loading" class="empty">加载中…</div>

    <div v-else class="stage">
      <div v-if="mode === 'reader'" class="reader prose" v-html="rendered" />
      <div v-else-if="mode === 'wechat'" class="phone-wrap">
        <div class="phone">
          <div class="phone-bar">手机预览 · 图文排版</div>
          <div class="reader prose phone-body" v-html="rendered" />
        </div>
      </div>
      <div v-else class="cards">
        <div v-for="(c, i) in cards" :key="i" class="xcard">
          <div class="xcard-top">
            <span class="mono xt">{{ String(i + 1).padStart(2, '0') }}</span>
            <strong>{{ c.head }}</strong>
          </div>
          <pre class="xcard-body">{{ c.body }}</pre>
          <div class="xcard-foot mono">3:4 · 1080×1440 · 小红书</div>
        </div>
      </div>
    </div>

    <footer class="foot mono">
      <span>{{ current?.path }}</span>
      <span class="muted">· {{ words }} 字</span>
      <span class="grow" />
      <span class="muted">公式以 TeX 源码展示，接入后端后走 KaTeX</span>
    </footer>
  </div>
</template>

<style scoped>
.article { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--line-soft); }
.seg.sm button { padding: 4px 9px; font-size: 11.5px; }
.stage { flex: 1; overflow-y: auto; min-height: 0; }
.reader { padding: 18px 22px; max-width: 720px; }
.reader :deep(.texblock) { position: relative; font-family: var(--mono); font-size: 12.5px; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 9px; padding: 12px 12px 12px 14px; margin: 0 0 14px; color: var(--ink-2); white-space: pre-wrap; }
.reader :deep(.tex-tag) { position: absolute; top: -8px; right: 10px; font-size: 9.5px; background: var(--panel-3); border: 1px solid var(--line); color: var(--muted); padding: 0 5px; border-radius: 5px; }
.reader :deep(.tex-inline) { font-family: var(--mono); font-size: 12.5px; background: var(--accent-soft); color: var(--accent); padding: 1px 5px; border-radius: 5px; }
.phone-wrap { display: flex; justify-content: center; padding: 18px; }
.phone { width: 390px; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45); }
.phone-bar { background: #f2f3f5; color: #333; font-size: 11.5px; padding: 8px 12px; text-align: center; }
.phone-body { padding: 16px 16px 26px; max-height: 62vh; overflow-y: auto; }
.phone-body :deep(h1), .phone-body :deep(h2), .phone-body :deep(h3), .phone-body :deep(p), .phone-body :deep(li), .phone-body :deep(td), .phone-body :deep(th), .phone-body :deep(strong) { color: #1a1a1a; }
.phone-body :deep(a) { color: #576b95; }
.phone-body :deep(h2) { border-left-color: #07c160; }
.phone-body :deep(table), .phone-body :deep(th), .phone-body :deep(td) { border-color: #e5e5e5; }
.phone-body :deep(th) { background: #f7f7f7; }
.cards { display: flex; gap: 12px; padding: 18px; overflow-x: auto; }
.xcard { flex: none; width: 268px; aspect-ratio: 3 / 4; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.xcard-top { display: flex; align-items: baseline; gap: 8px; }
.xcard-top strong { font-size: 13.5px; line-height: 1.4; }
.xt { color: var(--accent); font-size: 11px; }
.xcard-body { flex: 1; margin: 0; font-family: var(--sans); font-size: 12.5px; line-height: 1.75; color: var(--text-2); white-space: pre-wrap; overflow: hidden; }
.xcard-foot { color: var(--muted-2); font-size: 10px; }
.foot { display: flex; align-items: center; gap: 6px; padding: 7px 12px; border-top: 1px solid var(--line-soft); color: var(--muted-2); font-size: 11px; }
</style>
