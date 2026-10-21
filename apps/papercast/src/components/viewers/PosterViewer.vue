<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PaperRun } from '../../types'
import { assetUrl } from '../../api'

const props = defineProps<{ run: PaperRun }>()

const stage = computed(() => props.run.stages.find((s) => s.id === 'poster'))
const html = computed(() => stage.value?.artifacts.find((a) => a.kind === 'html'))
// 按**路径后缀**找 PNG（artifact.id 是 poster-1 这种，以前用 id.endsWith('png') 永远匹配不到，
// 于是「打开 PNG」点了没反应 —— 2026-09-23 修）。
const png = computed(() => stage.value?.artifacts.find((a) => a.kind === 'image' && /\.png$/i.test(a.path)))
const spec = computed(() => props.run.config.poster)
const zoom = ref(1)
const mode = ref<'fit' | 'actual'>('fit')

const url = computed(() => assetUrl(html.value?.url))
const htmlName = computed(() => html.value?.path.split('/').pop() || 'poster.html')
const pngName = computed(() => png.value?.path.split('/').pop() || 'poster.png')

function openPng() {
  if (png.value?.url) window.open(assetUrl(png.value.url), '_blank')
}
</script>

<template>
  <div class="poster">
    <div v-if="!html" class="empty">Poster 阶段尚未产出</div>
    <template v-else>
      <div class="toolbar">
        <span class="chip accent mono">{{ htmlName }}</span>
        <span class="chip mono">{{ spec.size }}</span>
        <span class="chip">{{ spec.venue }}</span>
        <span class="chip mono">theme: {{ spec.theme }} · {{ spec.lang }}</span>
        <div class="grow" />
        <div class="seg sm">
          <button :class="{ on: mode === 'fit' }" @click="mode = 'fit'">适配</button>
          <button :class="{ on: mode === 'actual' }" @click="mode = 'actual'">原始尺寸</button>
        </div>
        <button class="btn sm" :disabled="!png?.url" @click="openPng">打开 PNG</button>
      </div>

      <div class="split">
        <div class="frame-wrap" :class="mode">
          <div class="frame" :style="{ transform: `scale(${mode === 'fit' ? zoom : 1})` }">
            <iframe :src="url" title="poster preview" />
          </div>
        </div>

        <aside class="side">
          <div class="label">验收门（Painter 回读）</div>
          <div v-for="c in stage?.checks ?? []" :key="c.label" class="check" :class="c.state">
            <span class="ck" />
            <div>
              <strong>{{ c.label }}</strong>
              <div class="panel-sub">{{ c.detail }}</div>
            </div>
          </div>
          <div class="divider" />
          <div class="label">产物</div>
          <div class="row wrap gap">
            <span class="chip mono">{{ htmlName }}</span>
            <span class="chip mono">{{ png ? pngName : 'PNG 待渲染' }}</span>
            <span class="chip mono">poster.spec.json</span>
          </div>
          <p class="panel-sub note">
            小红书帖子实际发出的是「组图」那一套（poster/cards/output/xhs-*.jpg），
            这里展示的是 poster 阶段渲染的渠道画布与它的 HTML 原文。
          </p>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.poster { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.toolbar { display: flex; align-items: center; gap: 7px; padding: 8px 12px; border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }
.seg.sm button { padding: 4px 9px; font-size: 11.5px; }
.split { flex: 1; display: grid; grid-template-columns: 1fr 232px; min-height: 0; }
.frame-wrap { overflow: auto; padding: 16px; display: flex; justify-content: center; align-items: flex-start; background: repeating-linear-gradient(45deg, #f1f5f9, #f1f5f9 10px, #e9eef5 10px, #e9eef5 20px); }
.frame { width: 100%; max-width: 460px; aspect-ratio: 3 / 4; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 18px 44px -20px rgba(16, 24, 40, 0.45); transform-origin: top center; }
.frame iframe { width: 100%; height: 100%; border: none; display: block; }
.frame-wrap.actual .frame { max-width: 900px; aspect-ratio: auto; height: 1800px; }
.side { border-left: 1px solid var(--line-soft); padding: 13px; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.check { display: flex; gap: 9px; font-size: 12.5px; }
.check strong { color: var(--text-2); font-weight: 600; font-size: 12.5px; }
.ck { width: 7px; height: 7px; border-radius: 50%; margin-top: 6px; flex: none; background: var(--muted-2); }
.check.pass .ck { background: var(--ok); }
.check.fail .ck { background: var(--err); }
.check.run .ck { background: var(--accent); animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.3; } }
.gap { gap: 6px; }
.note { line-height: 1.7; }
</style>
