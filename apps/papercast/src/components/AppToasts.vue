<script setup lang="ts">
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
</script>

<template>
  <div class="toast-wrap">
    <div
      v-for="t in ui.toasts"
      :key="t.id"
      class="toast"
      :class="t.tone === 'info' ? '' : t.tone"
      @click="ui.dismissToast(t.id)"
    >
      {{ t.text }}
    </div>
  </div>
</template>
