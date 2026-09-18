<script setup lang="ts">
import { ref } from 'vue'
import ChatThread from '../components/chat/ChatThread.vue'
import AgentRail from '../components/chat/AgentRail.vue'
import Composer from '../components/chat/Composer.vue'
import { useChatStore } from '../stores/chat'
import { useRunsStore } from '../stores/runs'
import type { StageId } from '../types'

const chat = useChatStore()
const runs = useRunsStore()
const thread = ref<InstanceType<typeof ChatThread> | null>(null)
const dragging = ref(false)
let depth = 0

/** 拖进来的东西只有在真的落到聊天区时才处理；进出子元素会触发 dragleave，所以要计数 */
function onEnter() { depth += 1; dragging.value = true }
function onLeave() { depth -= 1; if (depth <= 0) { depth = 0; dragging.value = false } }
function onDrop(e: DragEvent) {
  dragging.value = false
  depth = 0
  const file = e.dataTransfer?.files?.[0]
  if (file) void chat.send('', file)
}
</script>

<template>
  <div
    class="chat-page"
    @dragenter.prevent="onEnter"
    @dragover.prevent
    @dragleave.prevent="onLeave"
    @drop.prevent="onDrop"
  >
    <section class="chat-main">
      <ChatThread ref="thread" @gate="(s: StageId, o: string) => runs.confirm(s, o)" />
      <Composer :busy="runs.busy || chat.asking" :uploading="chat.uploading" @send="chat.send($event.text, $event.file)" />
      <div v-if="dragging" class="drop">
        <div class="drop-inner">松手就把这份 PDF 交给它</div>
      </div>
    </section>

    <AgentRail @focus="thread?.focusStage($event)" />
  </div>
</template>

<style scoped>
.chat-page { flex: 1; display: grid; grid-template-columns: minmax(0, 1fr) 300px; min-height: 0; }
.chat-main { display: flex; flex-direction: column; min-height: 0; position: relative; }
.drop {
  position: absolute; inset: 12px 18px;
  border: 1.5px dashed #cfccc4; border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  display: grid; place-items: center; pointer-events: none;
}
.drop-inner { font-family: var(--serif); font-size: 17px; color: var(--text-2); }
@media (max-width: 1180px) {
  .chat-page { grid-template-columns: minmax(0, 1fr); }
  .chat-page :deep(.rail-side) { display: none; }
}
</style>
