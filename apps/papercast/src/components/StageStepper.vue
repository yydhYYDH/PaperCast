<script setup lang="ts">
import type { PaperRun } from '../types'
import { STAGE_STATUS } from '../utils'

defineProps<{ run: PaperRun }>()
const emit = defineEmits<{ (e: 'jump', id: string): void }>()
</script>

<template>
  <section class="panel">
    <div class="panel-body stepper">
      <template v-for="(s, i) in run.stages" :key="s.id">
        <button class="node" :class="STAGE_STATUS[s.status].cls" @click="emit('jump', s.id)">
          <span class="dot-wrap">
            <span class="dot">
              <svg v-if="s.status === 'done'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="m5 13 4 4L19 7" /></svg>
              <svg v-else-if="s.status === 'failed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M6 6l12 12M18 6 6 18" /></svg>
              <svg v-else-if="s.status === 'waiting'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 8v5M12 17h.01" /></svg>
              <svg v-else-if="s.status === 'running'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" class="spin"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
              <span v-else class="num">{{ i + 1 }}</span>
            </span>
          </span>
          <span class="lbl">{{ s.label }}</span>
          <span class="eng mono">{{ s.engine.split(' · ')[0] }}</span>
        </button>
        <span v-if="i < run.stages.length - 1" class="link" :class="{ filled: s.status === 'done' }" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.stepper { display: flex; align-items: center; gap: 0; padding: 12px 10px; overflow-x: auto; }
.node { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 78px; padding: 0 2px; }
.dot-wrap { width: 26px; height: 26px; display: grid; place-items: center; }
.dot {
  width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center;
  border: 1.5px solid var(--line);
  background: var(--panel-2);
  color: var(--muted-2);
  font-size: 10.5px; font-weight: 700;
  transition: 0.2s;
}
.dot svg { width: 12px; height: 12px; }
.node.done .dot { border-color: var(--ok); background: rgba(53, 211, 154, 0.14); color: var(--ok); }
.node.running .dot { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.node.waiting .dot { border-color: var(--warn); background: rgba(255, 180, 58, 0.14); color: var(--warn); }
.node.failed .dot { border-color: var(--err); background: rgba(255, 95, 126, 0.14); color: var(--err); }
.lbl { font-size: 11.5px; color: var(--text-2); white-space: nowrap; }
.node.done .lbl, .node.running .lbl, .node.waiting .lbl { color: var(--text); }
.eng { font-size: 9.5px; color: var(--muted-2); white-space: nowrap; }
.link { flex: 1; min-width: 16px; height: 1.5px; background: var(--line); margin-top: -22px; }
.link.filled { background: linear-gradient(90deg, var(--ok), rgba(53, 211, 154, 0.3)); }
.spin { animation: rot 1s linear infinite; }
@keyframes rot { to { transform: rotate(360deg); } }
</style>
