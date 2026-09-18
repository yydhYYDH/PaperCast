<script setup lang="ts">
import { computed } from 'vue'
import { useRunsStore } from '../../stores/runs'
import { useChatStore } from '../../stores/chat'
import RunHistory from '../RunHistory.vue'

const chat = useChatStore()
const runs = useRunsStore()

const emit = defineEmits<{ focus: [string] }>()
const run = computed(() => runs.active)
const roster = computed(() => chat.roster)

const RUN_STATUS: Record<string, string> = {
  queued: '排队中', running: '正在跑', waiting: '等你确认', done: '已完成', failed: '没成功',
}
</script>

<template>
  <aside class="rail-side">
    <div class="head">
      <h2 class="who-title">谁在干活</h2>
      <span v-if="run" class="chip tiny" :class="run.status === 'done' ? 'ok' : run.status === 'failed' ? 'err' : run.status === 'waiting' ? 'warn' : 'accent'">
        <i class="dot" />{{ RUN_STATUS[run.status] ?? run.status }}
      </span>
    </div>

    <p v-if="run" class="paper ellipsis" :title="run.source.title || run.title">{{ run.source.title || run.title }}</p>
    <p v-else class="paper muted-2">还没有开始</p>

    <ol v-if="roster.length" class="roster">
      <li v-for="r in roster" :key="r.id" :class="r.state" @click="emit('focus', r.id)">
        <i class="dot" />
        <div class="grow">
          <div class="n">{{ r.who }}</div>
          <div class="a ellipsis" :title="r.activity">{{ r.activity }}</div>
        </div>
      </li>
    </ol>
    <p v-else class="muted-2 tiny-note">提交一篇论文后，这里会显示六个环节各自在干什么。</p>

    <div class="divider" />
    <RunHistory />
  </aside>
</template>

<style scoped>
.rail-side {
  border-left: 1px solid var(--line);
  background: var(--surface);
  padding: 22px 18px;
  overflow-y: auto;
  min-height: 0;
  display: flex; flex-direction: column; gap: 10px;
}
.head { display: flex; align-items: center; gap: 8px; }
.who-title { font-family: var(--serif); font-size: 16px; font-weight: 500; }
.paper { font-size: 13px; color: var(--text-2); }
.roster { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.roster li {
  display: flex; align-items: center; gap: 9px;
  padding: 7px 8px; border-radius: 9px; cursor: pointer;
  transition: background 0.15s;
}
.roster li:hover { background: var(--surface-2); }
.roster .dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: #ddd9d2; }
.roster li.running .dot { background: var(--tone-green-fg); animation: pulse 1.4s infinite; }
.roster li.waiting .dot { background: var(--tone-amber-fg); }
.roster li.done .dot { background: #8fb79b; }
.roster li.failed .dot { background: var(--tone-red-fg); }
.roster .n { font-size: 13px; color: var(--text); }
.roster .a { font-size: 11.5px; color: var(--muted-2); }
.roster li.pending .n, .roster li.pending .a { color: var(--muted-2); }
.tiny-note { font-size: 12px; }
@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.35 } }
</style>
