<script setup lang="ts">
import type { ViewId } from '../types'

defineProps<{ view: ViewId; live: boolean }>()
defineEmits<{ (e: 'navigate', v: ViewId): void }>()

const items: { id: ViewId; label: string; icon: string }[] = [
  { id: 'workbench', label: '工作台', icon: 'M4 13h6V4H4v9Zm10 7h6v-9h-6v9ZM4 20h6v-4H4v4Zm10-11h6V4h-6v5Z' },
  { id: 'runs', label: '运行记录', icon: 'M12 8v5l4 2M12 3a9 9 0 1 0 9 9' },
  { id: 'library', label: '作品库', icon: 'M4 5h16v4H4zM4 15h16v4H4zM4 11h16' },
  { id: 'platforms', label: '平台账号', icon: 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 11.7-5.2M16.5 15.5l2 2 3.5-3.5' },
  { id: 'ops', label: '运营维护', icon: 'M4 19h16M6 16V9m4 7V4m4 12v-6m4 6v-9' },
  { id: 'settings', label: '设置', icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-3a8 8 0 0 0-.1-1.3l2-1.5-2-3.4-2.3 1a8 8 0 0 0-2.2-1.3L15 3H9l-.4 2.5a8 8 0 0 0-2.2 1.3l-2.3-1-2 3.4 2 1.5A8 8 0 0 0 4 12c0 .4 0 .9.1 1.3l-2 1.5 2 3.4 2.3-1a8 8 0 0 0 2.2 1.3L9 21h6l.4-2.5a8 8 0 0 0 2.2-1.3l2.3 1 2-3.4-2-1.5c.1-.4.1-.9.1-1.3Z' },
]
</script>

<template>
  <nav class="rail">
    <div class="brand" title="Easy-Reach · 把论文变成大家看得懂的内容">
      <span>E</span>
    </div>
    <button
      v-for="it in items"
      :key="it.id"
      class="item"
      :class="{ on: view === it.id }"
      :title="it.label"
      @click="$emit('navigate', it.id)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
        <path :d="it.icon" />
      </svg>
      <span class="txt">{{ it.label }}</span>
    </button>
    <div class="grow" />
    <div class="live" :class="{ on: live }" :title="live ? '有任务在跑' : '空闲'">
      <i />
    </div>
  </nav>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 14px 0 16px;
  border-right: 1px solid var(--line-soft);
  background: var(--bg-2);
}
.brand {
  width: 34px; height: 34px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text);
  font-family: var(--serif); font-weight: 500; font-size: 16px; letter-spacing: 0;
  margin-bottom: 12px;
}
.item {
  width: 46px; height: 44px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
  border-radius: 10px;
  color: var(--muted-2);
  transition: 0.15s;
}
.item svg { width: 18px; height: 18px; }
.item .txt { font-size: 9.5px; letter-spacing: 0.02em; }
.item:hover { color: var(--text); background: var(--panel-3); }
.item.on { color: var(--accent); background: var(--accent-soft); }
.grow { flex: 1; }
.live { width: 30px; height: 30px; display: grid; place-items: center; }
.live i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted-2); }
.live.on i { background: var(--ok); box-shadow: 0 0 10px rgba(53, 211, 154, 0.8); animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.35; } }
</style>
