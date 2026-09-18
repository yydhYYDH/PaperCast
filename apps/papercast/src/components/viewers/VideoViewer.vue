<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { PaperRun } from '../../types'
import { sampleAsset } from '../../data/example'
import { assetUrl } from '../../api'

interface Slide { index: number; title: string; bullets: string[]; narration: string; durationSec: number }
interface Script { title: string; totalSec: number; slides: Slide[] }

const props = defineProps<{ run: PaperRun }>()

const stage = computed(() => props.run.stages.find((s) => s.id === 'video'))
const video = computed(() => stage.value?.artifacts.find((a) => a.kind === 'video'))
const script = ref<Script | null>(null)
const el = ref<HTMLVideoElement | null>(null)
const active = ref(0)

/** 这次运行真出的旁白脚本：有真产物就不用示例，避免「看着像真的」 */
const narration = computed(() => stage.value?.artifacts.find((a) => a.path.endsWith('narration.json')))

onMounted(async () => {
  for (const src of [assetUrl(narration.value?.url), sampleAsset('video', 'narration.json')]) {
    if (!src) continue
    try {
      const res = await fetch(src)
      if (!res.ok) continue
      script.value = (await res.json()) as Script
      return
    } catch { /* 试下一个 */ }
  }
})

/** 旁白时长映射到片段真实时长：示例视频与脚本不是同一条片子，按比例对齐 */
const scale = ref(1)

/** 每条旁白在真实片段里的起点：脚本总时长按片长等比缩放 */
const offsets = computed(() => {
  const slides = script.value?.slides ?? []
  const total = script.value?.totalSec || slides.reduce((n, s) => n + s.durationSec, 0) || 1
  const real = total * scale.value
  let acc = 0
  return slides.map((s) => {
    const at = (acc / total) * real
    acc += s.durationSec
    return at
  })
})

function onLoaded() {
  const d = el.value?.duration
  const total = script.value?.totalSec
  scale.value = d && total ? d / total : 1
}

function seek(i: number) {
  active.value = i
  const t = offsets.value[i] ?? 0
  if (el.value) {
    el.value.currentTime = Math.min(t, (el.value.duration || t) - 1)
    void el.value.play().catch(() => {})
  }
}

function onTime() {
  const t = el.value?.currentTime ?? 0
  let i = 0
  offsets.value.forEach((o, idx) => { if (t >= o) i = idx })
  active.value = i
}

function fmt(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}
</script>

<template>
  <div class="video">
    <div v-if="!video" class="empty">视频阶段尚未产出</div>
    <template v-else>
      <div class="player-wrap">
        <video ref="el" :src="video.url" controls playsinline @timeupdate="onTime" @loadedmetadata="onLoaded" />
        <div class="meta row wrap">
          <span class="chip accent mono">1920×1080 · 16:9</span>
          <span class="chip mono">{{ props.run.config.video.voice }}</span>
          <span class="chip mono">7 页幻灯片</span>
          <span class="chip mono">示例片长 {{ Math.round(el?.duration ?? 0) }}s / 旁白 300s（等比对齐）</span>
          <span class="muted mono">{{ video.path }}</span>
          <div class="grow" />
          <span class="chip">{{ props.run.config.video.aspect === '9:16' ? '已导出竖版 9:16' : '竖版 9:16 可另导出' }}</span>
        </div>
        <p class="panel-sub credit">
          示例视频来自 showlab/Paper2Video 的公开产物，仅用于演示播放器与时间轴联动。
        </p>
      </div>

      <div class="script">
        <div class="label">旁白脚本 · narration.json（{{ fmt(script?.totalSec ?? 0) }}）</div>
        <button
          v-for="(s, i) in script?.slides ?? []"
          :key="s.index"
          class="slide"
          :class="{ on: active === i }"
          @click="seek(i)"
        >
          <div class="row spread">
            <strong class="s-title">{{ s.index }}. {{ s.title }}</strong>
            <span class="mono muted-2">{{ fmt(s.durationSec) }}</span>
          </div>
          <p class="s-narration">{{ s.narration }}</p>
          <div class="row wrap gap">
            <span v-for="b in s.bullets" :key="b" class="chip tiny">{{ b }}</span>
          </div>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.video { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.player-wrap { padding: 14px; display: flex; flex-direction: column; gap: 9px; border-bottom: 1px solid var(--line-soft); }
video { width: 100%; max-height: 320px; background: #000; border-radius: 10px; border: 1px solid var(--line-soft); }
.meta { gap: 7px; }
.grow { flex: 1; }
.credit { font-size: 11.5px; }
.script { flex: 1; overflow-y: auto; padding: 13px; display: flex; flex-direction: column; gap: 7px; }
.slide { text-align: left; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 9px; padding: 9px 11px; display: flex; flex-direction: column; gap: 6px; transition: 0.16s; }
.slide:hover { border-color: #cbd5e1; }
.slide.on { border-color: var(--accent); background: var(--accent-soft); }
.s-title { font-size: 12.5px; color: var(--text); }
.s-narration { font-size: 12.5px; color: var(--text-2); line-height: 1.75; }
.chip.tiny { font-size: 10.5px; padding: 1px 6px; }
.gap { gap: 5px; }
</style>
