<script setup lang="ts">
import { computed } from 'vue'
import type { Stage } from '../types'
import { STAGE_STATUS, fmtClock, fmtDuration } from '../utils'
import { useUiStore } from '../stores/ui'

const props = defineProps<{ stage: Stage; index: number }>()
const emit = defineEmits<{ (e: 'confirm', optionId: string): void }>()

const ui = useUiStore()
const key = computed(() => props.stage.id)
const st = computed(() => STAGE_STATUS[props.stage.status])
const open = computed(() => ui.isOpen(key.value, props.stage.status !== 'pending'))
const duration = computed(() =>
  props.stage.startedAt ? fmtDuration((props.stage.endedAt ?? Date.now()) - props.stage.startedAt) : '—',
)

const KIND_ICON: Record<string, string> = {
  markdown: 'M4 5h16v14H4zM7 9h2l1.5 3L12 9h2v6M16 9v6',
  html: 'M4 5h16v14H4zM8 10l-2 2 2 2M16 10l2 2-2 2',
  image: 'M4 5h16v14H4zm2 10 3.5-4 3 3.5L15 12l3 3',
  video: 'M4 6h11v12H4zm11 4 5-3v10l-5-3',
  json: 'M9 5c-2 0-2 3-2 3s0 2 2 2M15 5c2 0 2 3 2 3s0 2-2 2',
  pptx: 'M5 4h10l4 4v12H5zM9 12h3a2 2 0 1 0 0-4H9v8',
  text: 'M5 4h14v16H5zM8 9h8M8 13h8M8 17h5',
}
</script>

<template>
  <article class="card" :class="stage.status">
    <header class="card-head" @click="ui.toggle(key, stage.status !== 'pending')">
      <span class="idx mono">{{ String(index + 1).padStart(2, '0') }}</span>
      <div class="grow">
        <div class="row wrap gap">
          <strong class="c-title">{{ stage.label }}</strong>
          <span class="chip" :class="st.cls"><i class="dot" />{{ st.label }}</span>
          <span v-if="stage.startedAt" class="muted mono ts">{{ duration }}</span>
        </div>
      </div>
      <svg class="caret" :class="{ open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg>
    </header>

    <div v-if="stage.status !== 'pending'" class="bar thin"><i :style="{ width: stage.progress + '%' }" /></div>

    <div v-if="open" class="card-body">
      <!-- 人工闸门 -->
      <div v-if="stage.gate && stage.status === 'waiting'" class="gate">
        <div class="row spread">
          <strong class="gate-title">⏸ {{ stage.gate.label }}</strong>
          <span class="chip warn"><i class="dot" />等待人工确认</span>
        </div>
        <p class="gate-detail">{{ stage.gate.detail }}</p>
        <div class="row wrap">
          <button
            v-for="o in stage.gate.options"
            :key="o.id"
            class="btn"
            :class="{ primary: o.id === 'continue' }"
            :title="o.hint"
            @click="emit('confirm', o.id)"
          >
            {{ o.label }}
          </button>
        </div>
      </div>
      <div v-else-if="stage.gate?.resolved" class="gate-done mono">
        闸门已放行：{{ stage.gate.options.find((o) => o.id === stage.gate!.resolved)?.label ?? stage.gate.resolved }}
      </div>

      <!-- 校验条目 -->
      <div v-if="stage.checks?.length" class="checks">
        <div v-for="c in stage.checks" :key="c.label" class="check" :class="c.state">
          <span class="ck-dot" />
          <strong>{{ c.label }}</strong>
          <span class="muted">{{ c.detail }}</span>
        </div>
      </div>

      <!-- 产物 -->
      <div v-if="stage.artifacts.length" class="arts">
        <div class="label">产物 · {{ stage.artifacts.length }}</div>
        <button
          v-for="a in stage.artifacts"
          :key="a.id"
          class="art"
          :class="{ pending: a.meta?.pending }"
          @click="!a.meta?.pending && ui.openArtifact(stage.id, a.id)"
        >
          <svg class="ai" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path :d="KIND_ICON[a.kind] ?? KIND_ICON.text!" />
          </svg>
          <span class="grow ellipsis">{{ a.label }}</span>
          <span class="mono muted-2">{{ a.meta?.pending ? '待渲染' : a.url ? '预览' : '本地' }}</span>
        </button>
      </div>

      <!-- 日志 -->
      <div v-if="stage.logs.length" class="logs">
        <div v-for="(l, i) in stage.logs" :key="i" class="log" :class="l.level">
          <span class="lt mono">{{ fmtClock(l.ts) }}</span>
          <span class="ltx">{{ l.text }}</span>
        </div>
      </div>
      <div v-else class="panel-sub">尚未开始</div>
    </div>
  </article>
</template>

<style scoped>
.card { border: 1px solid var(--line-soft); border-radius: 11px; overflow: hidden; background: var(--panel); transition: 0.2s; }
.card.running { border-color: rgba(79, 70, 229, 0.4); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.08); }
.card.waiting { border-color: rgba(255, 180, 58, 0.45); }
.card.failed { border-color: rgba(255, 95, 126, 0.4); }
.card-head { display: flex; align-items: flex-start; gap: 10px; padding: 11px 13px; cursor: pointer; }
.card-head:hover { background: var(--panel-2); }
.idx { color: var(--muted-2); font-size: 11px; padding-top: 3px; }
.c-title { font-size: 13.5px; }
.gap { gap: 6px; }
.reuse { color: var(--muted-2); font-size: 11px; margin-top: 5px; }
.ts { font-size: 11px; }
.caret { width: 16px; height: 16px; color: var(--muted-2); transition: 0.2s; margin-top: 3px; }
.caret.open { transform: rotate(180deg); }
.bar.thin { height: 2px; }
.card-body { padding: 12px 13px 14px; display: flex; flex-direction: column; gap: 12px; border-top: 1px solid var(--line-soft); }
.gate { background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.28); border-radius: 11px; padding: 11px 12px; display: flex; flex-direction: column; gap: 8px; }
.gate-title { font-size: 13px; color: #b45309; font-weight: 600; }
.gate-detail { font-size: 12.5px; color: var(--text-2); }
.gate-done { font-size: 11.5px; color: var(--ok); }
.checks { display: flex; flex-direction: column; gap: 5px; }
.check { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.check strong { font-weight: 600; color: var(--text-2); }
.ck-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted-2); }
.check.pass .ck-dot { background: var(--ok); }
.check.fail .ck-dot { background: var(--err); }
.check.run .ck-dot { background: var(--accent); animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.3; } }
.arts { display: flex; flex-direction: column; gap: 5px; }
.art { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 6px 9px; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 8px; font-size: 12.5px; color: var(--text-2); transition: 0.15s; }
.art:hover { border-color: var(--accent); color: var(--text); }
.art.pending { opacity: 0.5; cursor: default; }
.ai { width: 15px; height: 15px; color: var(--muted); flex: none; }
.logs { display: flex; flex-direction: column; gap: 2px; max-height: 190px; overflow-y: auto; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 8px; padding: 8px 9px; }
.log { display: flex; gap: 9px; font-size: 11.5px; line-height: 1.6; }
.lt { color: var(--muted-2); flex: none; }
.ltx { color: var(--text-2); }
.log.ok .ltx { color: var(--ok); }
.log.warn .ltx { color: var(--warn); }
.log.err .ltx { color: var(--err); }
</style>
