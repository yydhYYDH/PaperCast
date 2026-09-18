<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { EXAMPLE_PAPER } from '../../data/example'

const props = defineProps<{ busy?: boolean; uploading?: boolean }>()
const emit = defineEmits<{ send: [{ text: string; file?: File | null }] }>()

const text = ref('')
const box = ref<HTMLTextAreaElement | null>(null)

function grow() {
  const el = box.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 168) + 'px'
}

function send() {
  const t = text.value.trim()
  if (!t || props.busy) return
  emit('send', { text: t })
  text.value = ''
  nextTick(grow)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

function pick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) emit('send', { text: '', file: f })
  ;(e.target as HTMLInputElement).value = ''
}

/** 剪贴板里直接是文件（截图/复制的 PDF）也能接 */
function onPaste(e: ClipboardEvent) {
  const f = Array.from(e.clipboardData?.files ?? [])[0]
  if (f) {
    e.preventDefault()
    emit('send', { text: '', file: f })
  }
}

function useExample() {
  text.value = EXAMPLE_PAPER.url
  nextTick(() => send())
}
</script>

<template>
  <div class="composer">
    <div class="box" :class="{ busy }">
      <textarea
        ref="box"
        v-model="text"
        rows="1"
        placeholder="把论文丢进来 —— 粘贴链接、拖一份 PDF，或者直接问我这次的结果"
        @input="grow"
        @keydown="onKey"
        @paste="onPaste"
      />
      <div class="row">
        <label class="btn sm ghost pick">
          选 PDF
          <input type="file" accept="application/pdf,.pdf" @change="pick" />
        </label>
        <button class="btn sm ghost" :disabled="busy" @click="useExample">用示例论文试试</button>
        <span class="grow" />
        <button class="btn primary" :disabled="busy || !text.trim()" @click="send">
          {{ uploading ? '上传中…' : busy ? '开始中…' : '开始' }}
        </button>
      </div>
    </div>
    <p class="hint">默认：一篇中文长文 + 一张海报 + 一段讲解视频 · 三个平台先排稿、发布要你点头 · 想改去「设置」</p>
  </div>
</template>

<style scoped>
.composer { padding: 8px 26px 16px; }
.box {
  width: min(760px, 100%);
  margin: 0 auto;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 14px 10px;
  display: flex; flex-direction: column; gap: 8px;
  transition: border-color 0.15s;
}
.box:focus-within { border-color: #d8d6d0; }
textarea {
  border: none; outline: none; resize: none; background: none;
  font: inherit; font-size: 15px; line-height: 1.7; color: var(--text);
  max-height: 168px;
}
textarea::placeholder { color: var(--muted-2); }
.pick { position: relative; overflow: hidden; }
.pick input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.hint {
  width: min(760px, 100%);
  margin: 8px auto 0;
  font-size: 12px; color: var(--muted-2); text-align: center;
}
</style>
