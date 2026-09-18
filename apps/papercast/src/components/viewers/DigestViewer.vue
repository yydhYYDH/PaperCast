<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { PaperDigest } from '../../types'

const digest = ref<PaperDigest | null>(null)
const failed = ref(false)

onMounted(async () => {
  try {
    const res = await fetch('/samples/digest.json')
    if (!res.ok) throw new Error(String(res.status))
    digest.value = (await res.json()) as PaperDigest
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <div v-if="digest" class="digest">
    <div class="banner">
      <div class="label">论文理解层 · 唯一事实源</div>
      <h3 class="d-title">{{ digest.title }}</h3>
      <div class="row wrap gap panel-sub">
        <span class="mono">{{ digest.arxivId }}</span>
        <span>· {{ digest.venue }} · {{ digest.year }}</span>
        <span v-if="digest.authors.length">· {{ digest.authors.join(', ') }}</span>
      </div>
      <p class="abs">{{ digest.abstractCn }}</p>
      <div class="row wrap gap">
        <span v-for="k in digest.keywords" :key="k" class="chip">{{ k }}</span>
      </div>
    </div>

    <section class="sec">
      <div class="label">核心贡献</div>
      <ol class="contrib">
        <li v-for="(c, i) in digest.contributions" :key="i">{{ c }}</li>
      </ol>
    </section>

    <section class="sec">
      <div class="label">方法主线</div>
      <p class="method">{{ digest.method }}</p>
    </section>

    <section class="sec">
      <div class="label">证据与结果</div>
      <table class="tbl">
        <thead><tr><th>指标 / 对比</th><th>结论</th><th>出处</th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in digest.results" :key="i">
            <td>{{ r.label }}</td>
            <td class="v">{{ r.value }}</td>
            <td class="note">{{ r.note }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="sec">
      <div class="label">图表素材池 · {{ digest.figures.length }}</div>
      <div class="figs">
        <div v-for="f in digest.figures" :key="f.id" class="fig">
          <div class="fig-top mono">{{ f.id }}</div>
          <div class="fig-body">{{ f.caption }}</div>
          <div class="fig-src mono">{{ f.source }}</div>
        </div>
      </div>
    </section>

    <section class="sec">
      <div class="label">局限</div>
      <ul class="lim">
        <li v-for="(l, i) in digest.limitations" :key="i">{{ l }}</li>
      </ul>
    </section>

    <p class="panel-sub note-bottom">{{ digest.stagesNote }}</p>
  </div>
  <div v-else class="empty">{{ failed ? '示例数据未找到（public/samples/digest.json）' : '加载中…' }}</div>
</template>

<style scoped>
.digest { display: flex; flex-direction: column; gap: 16px; padding: 14px; overflow-y: auto; }
.banner { background: linear-gradient(180deg, #151d2c, #10151f); border: 1px solid var(--line-soft); border-radius: 11px; padding: 13px; display: flex; flex-direction: column; gap: 8px; }
.d-title { font-size: 15px; line-height: 1.45; }
.gap { gap: 6px; }
.abs { font-size: 13px; color: var(--text-2); line-height: 1.75; }
.sec { display: flex; flex-direction: column; gap: 7px; }
.contrib { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 5px; font-size: 13px; color: var(--text-2); }
.contrib li::marker { color: var(--accent); font-weight: 700; }
.method { font-size: 13px; color: var(--text-2); line-height: 1.85; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th, .tbl td { border: 1px solid var(--line-soft); padding: 7px 9px; text-align: left; vertical-align: top; }
.tbl th { background: var(--panel-2); color: var(--text); font-weight: 600; }
.tbl td { color: var(--text-2); }
.tbl .v { color: var(--text); }
.tbl .note { color: var(--muted); font-size: 11.5px; }
.figs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.fig { background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 9px; overflow: hidden; }
.fig-top { padding: 5px 9px; background: var(--panel-2); color: var(--accent); font-size: 10.5px; border-bottom: 1px solid var(--line-soft); }
.fig-body { padding: 9px; font-size: 12px; color: var(--text-2); line-height: 1.6; }
.fig-src { padding: 0 9px 8px; color: var(--muted-2); font-size: 10.5px; }
.lim { margin: 0; padding-left: 18px; font-size: 12.5px; color: var(--text-2); display: flex; flex-direction: column; gap: 4px; }
.note-bottom { border-top: 1px dashed var(--line-soft); padding-top: 10px; }
</style>
