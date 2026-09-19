<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import ChatMessage from './ChatMessage.vue'
import { useChatStore } from '../../stores/chat'
import { useRunsStore } from '../../stores/runs'
import type { StageId } from '../../types'

const emit = defineEmits<{
  gate: [stage: StageId, option: string]
  action: [id: string, go: boolean]
}>()
const chat = useChatStore()
const runs = useRunsStore()
const box = ref<HTMLElement | null>(null)

const messages = computed(() => chat.messages)
const run = computed(() => runs.active)

/** 新消息来了才贴底；用户自己往上翻的时候不打扰 */
function stick(force = false) {
  const el = box.value
  if (!el) return
  const near = el.scrollHeight - el.scrollTop - el.clientHeight < 180
  if (force || near) el.scrollTop = el.scrollHeight
}
watch(() => messages.value.length, () => nextTick(() => stick()))
watch(() => messages.value[messages.value.length - 1]?.text, () => nextTick(() => stick()))

/** 右侧名单点一下 → 滚到那个人说过的话 */
async function focusStage(stageId: string) {
  await nextTick()
  const el = box.value?.querySelector(`#m-${stageId}`) as HTMLElement | null
  if (!el) return
  box.value!.scrollTo({ top: el.offsetTop - box.value!.offsetTop - 12, behavior: 'smooth' })
}
defineExpose({ focusStage })

/** 闸门放行由父级统一处理（见 WorkbenchView 的 @gate） */
</script>

<template>
  <div ref="box" class="thread">
    <div class="inner">
      <div v-for="m in messages" :id="'m-' + (m.stageId ?? m.id)" :key="m.id">
        <ChatMessage
          :msg="m"
          :run="run"
          @gate="(o: string) => m.stageId && emit('gate', m.stageId, o)"
          @action="(id: string, go: boolean) => emit('action', id, go)"
        />
      </div>
      <p v-if="chat.asking" class="thinking">助手正在读这次运行的记录…</p>
      <div class="tail" />
    </div>
  </div>
</template>

<style scoped>
.thread { flex: 1; overflow-y: auto; min-height: 0; }
.inner {
  width: min(760px, 100%);
  margin: 0 auto;
  padding: 26px 26px 10px;
  display: flex; flex-direction: column; gap: 24px;
}
.thinking { text-align: center; font-size: 12.5px; color: var(--muted-2); }
.tail { height: 4px; }
</style>
