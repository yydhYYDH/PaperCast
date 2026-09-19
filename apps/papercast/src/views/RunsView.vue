<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'
import { RUN_STATUS, STAGE_STATUS, fmtAgo, fmtDuration } from '../utils'

const store = useRunsStore()
const ui = useUiStore()
const filter = ref<'all' | 'done' | 'failed' | 'live'>('all')

const rows = computed(() => {
  const all = store.runs
  if (filter.value === 'all') return all
  if (filter.value === 'live') return all.filter((r) => r.status === 'running' || r.status === 'waiting' || r.status === 'queued')
  return all.filter((r) => r.status === filter.value)
})

function open(id: string) {
  store.select(id)
  ui.setView('workbench')
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">运行记录</h1>
        <p class="page-lead">每一次「论文 → 内容」的完整过程都留在这里，点一行就能回头看它产出了什么。</p>
      </div>
    </header>

    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">全部记录</span>
        <div class="grow" />
        <div class="seg sm">
          <button v-for="f in (['all', 'live', 'done', 'failed'] as const)" :key="f" :class="{ on: filter === f }" @click="filter = f">
            {{ { all: '全部', live: '进行中', done: '已完成', failed: '失败' }[f] }}
          </button>
        </div>
      </header>

      <table class="tbl">
        <thead>
          <tr>
            <th style="width: 34%">论文 / 输入</th>
            <th>状态</th>
            <th>阶段</th>
            <th>产物</th>
            <th>耗时</th>
            <th>提交时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id" :class="{ on: r.id === store.activeId }">
            <td>
              <div class="tt ellipsis">{{ r.title }}</div>
              <div class="mono sub">{{ r.source.kind }}: {{ r.source.value }}</div>
            </td>
            <td><span class="chip" :class="RUN_STATUS[r.status].cls"><i class="dot" />{{ RUN_STATUS[r.status].label }}</span></td>
            <td>
              <div class="stages">
                <span
                  v-for="s in r.stages"
                  :key="s.id"
                  class="pill"
                  :class="STAGE_STATUS[s.status].cls"
                  :title="`${s.label} · ${STAGE_STATUS[s.status].label}`"
                />
              </div>
            </td>
            <td class="mono">{{ r.stages.reduce((n, s) => n + s.artifacts.length, 0) }}</td>
            <td class="mono muted">{{ r.status === 'done' ? fmtDuration(r.createdAt ? 1000 * 60 * 26 : 0) : '—' }}</td>
            <td class="mono muted">{{ fmtAgo(r.createdAt) }}</td>
            <td><button class="btn sm" @click="open(r.id)">查看</button></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="empty">没有符合条件的运行</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="store.active" class="panel">
      <header class="panel-head">
        <span class="panel-title">{{ store.active.title }}</span>
        <div class="grow" />
        <button class="btn sm primary" @click="ui.setView('workbench')">回到工作台</button>
      </header>
      <div class="panel-body detail">
        <div v-for="s in store.active.stages" :key="s.id" class="row-item">
          <span class="pill" :class="STAGE_STATUS[s.status].cls" />
          <strong class="grow">{{ s.label }}</strong>
          <span class="mono muted-2">{{ Math.round(s.progress) }}%</span>
          <span class="mono muted-2">{{ s.artifacts.length }} 产物</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th { text-align: left; padding: 9px 12px; color: var(--muted); font-weight: 600; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; border-bottom: 1px solid var(--line-soft); }
.tbl td { padding: 10px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; }
.tbl tr.on { background: var(--accent-soft); }
.tbl tr:hover { background: var(--panel-2); }
.tt { color: var(--text); margin-bottom: 3px; }
.sub { color: var(--muted-2); font-size: 11px; }
.stages { display: flex; gap: 3px; }
.pill { width: 16px; height: 6px; border-radius: 3px; background: var(--line); display: inline-block; }
.pill.ok { background: var(--ok); }
.pill.err { background: var(--err); }
.pill.warn { background: var(--warn); }
.pill.accent { background: var(--accent); }
.detail { display: flex; flex-direction: column; gap: 6px; }
.row-item { display: flex; align-items: center; gap: 10px; font-size: 12.5px; padding: 7px 0; border-bottom: 1px solid var(--line-soft); }
.row-item:last-child { border-bottom: none; }
.seg.sm button { padding: 4px 9px; font-size: 11.5px; }

/* 手机：六列表格在 390px 上只能横着拖，改成一条一条的卡片 ——
   表头藏掉，每个 td 变成卡片里的一格，格子前的小标签用 ::before 补上。 */
@media (max-width: 720px) {
  .tbl { font-size: 13.5px; }
  .tbl thead { display: none; }
  .tbl, .tbl tbody { display: block; }
  .tbl tr {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px 10px; padding: 12px 3px 13px;
  }
  .tbl td { display: block; padding: 0; border: 0; }
  .tbl td:nth-child(1) { grid-area: 1 / 1 / 2 / -1; }
  .tbl td:nth-child(2) { grid-area: 2 / 1 / 3 / 3; align-self: center; }
  .tbl td:nth-child(7) { grid-area: 2 / 3 / 3 / 4; justify-self: end; align-self: center; }
  .tbl td:nth-child(3) { grid-area: 3 / 1 / 4 / -1; }
  .tbl td:nth-child(4)::before { content: '产物 '; color: var(--muted-2); }
  .tbl td:nth-child(5)::before { content: '耗时 '; color: var(--muted-2); }
  .tbl td:nth-child(6)::before { content: '提交 '; color: var(--muted-2); }
  .tbl td:nth-child(4), .tbl td:nth-child(5), .tbl td:nth-child(6) { font-size: 12px; }
  .tbl td.empty { grid-column: 1 / -1; }
  .stages { gap: 4px; }
  .pill { flex: 1; height: 5px; }
}
</style>
