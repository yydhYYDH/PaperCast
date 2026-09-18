<script setup lang="ts">
import { computed } from 'vue'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const open = computed(() => !!ui.ask)
</script>

<template>
  <Teleport to="body">
    <div v-if="open && ui.ask" class="mask" @click.self="ui.answerAsk(false)">
      <div class="sheet" role="dialog" aria-modal="true">
        <div class="sheet-body">
          <h2 class="sheet-title">{{ ui.ask.title }}</h2>
          <p v-if="ui.ask.text" class="sheet-text">{{ ui.ask.text }}</p>
        </div>
        <div class="sheet-foot">
          <button class="btn" @click="ui.answerAsk(false)">{{ ui.ask.cancelLabel || '再想想' }}</button>
          <button class="btn" :class="ui.ask.tone === 'err' ? 'danger' : 'primary'" @click="ui.answerAsk(true)">
            {{ ui.ask.okLabel || '确认' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
