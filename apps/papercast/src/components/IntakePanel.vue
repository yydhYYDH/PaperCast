<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRunsStore } from '../stores/runs'
import type { RunConfig, SourceInput, SourceKind } from '../types'

const store = useRunsStore()

const kind = ref<SourceKind>('arxiv')
const arxiv = ref('https://arxiv.org/abs/2510.05096')
const latexPath = ref('')
const dragging = ref(false)
const file = ref<{ name: string; size: number } | null>(null)
const showConfig = ref(true)

const kinds: { id: SourceKind; label: string; hint: string }[] = [
  { id: 'arxiv', label: 'arXiv 链接', hint: '粘贴 abs / pdf 链接或裸 ID，自动下载 LaTeX 源码' },
  { id: 'pdf', label: 'PDF 文件', hint: '拖入本地 PDF，走 MinerU 解析' },
  { id: 'latex', label: 'LaTeX 源码', hint: '本地目录 / .tar.gz / main.tex' },
]

const arxivId = computed(() => {
  const m = arxiv.value.match(/(\d{4}\.\d{4,5})(v\d+)?/)
  return m ? m[1]! : ''
})

const parsed = computed(() => {
  if (kind.value === 'arxiv') {
    if (arxivId.value === '2510.05096') {
      return {
        title: 'Paper2Video: Automatic Video Generation from Scientific Papers',
        authors: ['Zayn Zhu', 'Show Lab'],
        venue: 'NeurIPS 2025 SEA Workshop',
        pages: 17,
      }
    }
    return arxivId.value
      ? { title: `arXiv:${arxivId.value}`, authors: [], venue: 'arXiv preprint', pages: 0 }
      : null
  }
  if (kind.value === 'pdf') return file.value ? { title: file.value.name.replace(/\.pdf$/i, ''), authors: [], venue: '本地文件', pages: 0 } : null
  return latexPath.value ? { title: latexPath.value.split('/').filter(Boolean).pop() ?? 'latex', authors: [], venue: '本地源码', pages: 0 } : null
})

function onDrop(e: DragEvent) {
  dragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) {
    file.value = { name: f.name, size: f.size }
    kind.value = 'pdf'
  }
}
function onPick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) {
    file.value = { name: f.name, size: f.size }
    kind.value = 'pdf'
  }
}

const config = reactive<RunConfig>({
  article: { variants: ['wechat-academic', 'wechat-media', 'xhs-academic', 'xhs-media'] },
  poster: { size: '36×48 in', venue: 'NeurIPS 2025', theme: 'default', lang: 'en' },
  video: { durationSec: 300, voice: 'zh-CN-XiaoxiaoNeural', aspect: '16:9', narration: '中文' },
  publish: { targets: ['xhs', 'wechat'], autoPublish: false },
})

const VARIANTS = [
  { id: 'wechat-academic', label: '微信 × 学术' },
  { id: 'wechat-media', label: '微信 × 媒体' },
  { id: 'xhs-academic', label: '小红书 × 学术' },
  { id: 'xhs-media', label: '小红书 × 媒体' },
]
const TARGETS = [
  { id: 'xhs', label: '小红书' },
  { id: 'wechat', label: '公众号草稿箱' },
  { id: 'bilibili', label: 'B 站' },
]

function toggle(list: string[], id: string) {
  const i = list.indexOf(id)
  if (i >= 0) list.splice(i, 1)
  else list.push(id)
}

const canSubmit = computed(() =>
  kind.value === 'arxiv' ? !!arxivId.value : kind.value === 'pdf' ? !!file.value : !!latexPath.value,
)

function submit() {
  if (!canSubmit.value) return
  const source: SourceInput =
    kind.value === 'arxiv'
      ? { kind: 'arxiv', value: arxivId.value, ...(parsed.value ?? {}) }
      : kind.value === 'pdf'
        ? { kind: 'pdf', value: file.value!.name, bytes: file.value!.size, ...(parsed.value ?? {}) }
        : { kind: 'latex', value: latexPath.value, ...(parsed.value ?? {}) }
  void store.submit(source, JSON.parse(JSON.stringify(config)) as RunConfig)
}
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">新建运行</span>
      <span class="panel-sub grow">论文 → 文章 / Poster / 视频</span>
      <span class="chip accent">6 阶段</span>
    </header>

    <div class="panel-body body">
      <div class="seg">
        <button v-for="k in kinds" :key="k.id" :class="{ on: kind === k.id }" @click="kind = k.id">{{ k.label }}</button>
      </div>
      <p class="panel-sub hint">{{ kinds.find((k) => k.id === kind)?.hint }}</p>

      <div v-if="kind === 'arxiv'" class="stack">
        <input v-model="arxiv" class="field mono" placeholder="https://arxiv.org/abs/2510.05096" />
        <div class="row wrap">
          <span class="chip" :class="arxivId ? 'ok' : 'err'"><i class="dot" />{{ arxivId ? `arXiv:${arxivId}` : '未识别到 ID' }}</span>
          <button class="btn sm ghost" @click="arxiv = 'https://arxiv.org/abs/2510.05096'">用示例论文</button>
        </div>
      </div>

      <div v-else-if="kind === 'pdf'" class="stack">
        <label
          class="drop"
          :class="{ over: dragging }"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="onDrop"
        >
          <input type="file" accept="application/pdf" hidden @change="onPick" />
          <strong>{{ file ? file.name : '拖入 PDF 或点击选择' }}</strong>
          <span class="panel-sub">{{ file ? `${(file.size / 1048576).toFixed(2)} MB · 走 MinerU 解析` : '仅本地解析，文件不上传到第三方（MinerU 云端模式除外）' }}</span>
        </label>
      </div>

      <div v-else class="stack">
        <input v-model="latexPath" class="field mono" placeholder="/path/to/paper/main.tex 或 arXiv-xxxx.tar.gz" />
        <p class="panel-sub">支持完整工程目录、单篇 .tex 或压缩包；有 main.tex 时以其为入口。</p>
      </div>

      <div v-if="parsed" class="preview">
        <div class="label">输入预览</div>
        <div class="pv-title">{{ parsed.title }}</div>
        <div class="row wrap panel-sub">
          <span v-if="parsed.authors.length">{{ parsed.authors.join(' · ') }}</span>
          <span>· {{ parsed.venue }}</span>
          <span v-if="parsed.pages">· {{ parsed.pages }} 页</span>
        </div>
      </div>

      <div class="divider" />

      <button class="row spread cfg-toggle" @click="showConfig = !showConfig">
        <span class="label">生成配置</span>
        <span class="muted">{{ showConfig ? '收起' : '展开' }}</span>
      </button>

      <div v-show="showConfig" class="stack cfg">
        <div class="cfg-block">
          <div class="label">文章风格</div>
          <div class="row wrap">
            <button
              v-for="v in VARIANTS"
              :key="v.id"
              class="chip toggle"
              :class="{ on: config.article.variants.includes(v.id) }"
              @click="toggle(config.article.variants, v.id)"
            >
              {{ v.label }}
            </button>
          </div>
        </div>

        <div class="grid2">
          <label class="cfg-block">
            <span class="label">Poster 尺寸</span>
            <select v-model="config.poster.size" class="field">
              <option>36×48 in</option><option>48×36 in</option><option>A0</option><option>24×36 in</option>
            </select>
          </label>
          <label class="cfg-block">
            <span class="label">会场</span>
            <select v-model="config.poster.venue" class="field">
              <option>NeurIPS 2025</option><option>ICLR 2026</option><option>ACL 2026</option><option>自定义</option>
            </select>
          </label>
          <label class="cfg-block">
            <span class="label">视频比例</span>
            <select v-model="config.video.aspect" class="field">
              <option>16:9</option><option>9:16</option>
            </select>
          </label>
          <label class="cfg-block">
            <span class="label">配音音色</span>
            <select v-model="config.video.voice" class="field">
              <option>zh-CN-XiaoxiaoNeural</option><option>zh-CN-YunxiNeural</option><option>en-US-AriaNeural</option>
            </select>
          </label>
        </div>

        <label class="cfg-block">
          <span class="label">视频时长上限 · {{ config.video.durationSec }}s</span>
          <input v-model.number="config.video.durationSec" type="range" min="60" max="600" step="30" class="range" />
        </label>

        <div class="cfg-block">
          <div class="label">发布目标（均有闸门确认）</div>
          <div class="row wrap">
            <button
              v-for="t in TARGETS"
              :key="t.id"
              class="chip toggle"
              :class="{ on: config.publish.targets.includes(t.id) }"
              @click="toggle(config.publish.targets, t.id)"
            >
              {{ t.label }}
            </button>
          </div>
        </div>

        <label class="switch-row">
          <input v-model="store.autoConfirm" type="checkbox" />
          <span>演示模式：自动放行人工闸门</span>
        </label>
      </div>

      <button class="btn primary wide" :disabled="!canSubmit || store.busy" @click="submit">
        {{ store.busy ? '提交中…' : '▶ 开始生成' }}
      </button>
      <p class="panel-sub center">真实流水线约 20–40 分钟；演示模式下约 35 秒跑完全链路。</p>
      <p v-if="store.error" class="err-line">{{ store.error }}</p>
    </div>
  </section>
</template>

<style scoped>
.body { display: flex; flex-direction: column; gap: 12px; }
.stack { display: flex; flex-direction: column; gap: 8px; }
.hint { margin-top: -4px; }
.preview { background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 5px; }
.pv-title { font-size: 13.5px; color: var(--text); line-height: 1.45; }
.drop {
  display: flex; flex-direction: column; gap: 4px; align-items: center; justify-content: center;
  padding: 22px 14px; text-align: center;
  border: 1px dashed var(--line); border-radius: 10px; background: var(--bg-2);
  cursor: pointer; transition: 0.15s;
}
.drop:hover, .drop.over { border-color: var(--accent); background: var(--accent-soft); }
.cfg-toggle { width: 100%; padding: 2px 0; }
.cfg { gap: 12px; }
.cfg-block { display: flex; flex-direction: column; gap: 6px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.chip.toggle { cursor: pointer; padding: 4px 10px; }
.chip.toggle.on { background: var(--accent-soft); border-color: rgba(90, 162, 255, 0.45); color: #d6e7ff; }
.range { width: 100%; accent-color: var(--accent); }
.switch-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
.switch-row input { accent-color: var(--accent); }
.wide { width: 100%; justify-content: center; padding: 9px; }
.center { text-align: center; }
.err-line { color: var(--err); font-size: 12px; }
select.field { appearance: none; background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%); background-position: calc(100% - 14px) 50%, calc(100% - 9px) 50%; background-size: 5px 5px; background-repeat: no-repeat; }
</style>
