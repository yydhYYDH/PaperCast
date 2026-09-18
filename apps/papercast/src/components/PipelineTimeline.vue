<script setup lang="ts">
import { ref } from 'vue'
import type { PaperRun } from '../types'
import StageCard from './StageCard.vue'
import { useRunsStore } from '../stores/runs'

const props = defineProps<{ run: PaperRun }>()
const store = useRunsStore()
const el = ref<HTMLElement | null>(null)

function confirm(stageId: string, optionId: string) {
  void store.confirm(stageId as never, optionId)
}

defineExpose({ scrollTo: (id: string) => {
  const node = el.value?.querySelector(`[data-stage="${id}"]`)
  node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
} })
</script>

<template>
  <div ref="el" class="timeline">
    <div v-for="(s, i) in props.run.stages" :key="s.id" :data-stage="s.id">
      <StageCard :stage="s" :index="i" @confirm="(o: string) => confirm(s.id, o)" />
    </div>
  </div>
</template>

<style scoped>
.timeline { display: flex; flex-direction: column; gap: 10px; }
</style>
