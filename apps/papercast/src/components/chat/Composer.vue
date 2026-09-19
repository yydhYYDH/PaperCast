<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { EXAMPLE_PAPER } from '../../data/example'
import { useStyleStore } from '../../stores/style'

const props = defineProps<{ busy?: boolean; uploading?: boolean }>()
const emit = defineEmits<{
  send: [{ text: string; file?: File | null }]
  newThread: []
  /** 点「风格」跳到风格页（个性化层就露在输入框这一行，不藏在设置里） */
  style: []
}>()

/** 当前风格：决定这一轮内容写成什么样（接口见 stores/style.ts） */
const style = useStyleStore()

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

/**
 * 「可以这样说」：点一下就当成用户自己说的一句话发出去。
 * 这三句各自能派一个活（重跑 / 取数据 / 问论文），但它们**都不会直接产生对外动作** ——
 * 重跑与发布这类会先出一张确认卡，见 stores/chat.ts 的 runAction。
 */
function say(t: string) {
  if (props.busy) return
  emit('send', { text: t })
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
        <button class="btn sm ghost" :disabled="busy" @click="emit('newThread')">新开一个对话</button>
        <span class="grow" />
        <button class="btn primary" :disabled="busy || !text.trim()" @click="send">
          {{ uploading ? '上传中…' : busy ? '开始中…' : '开始' }}
        </button>
      </div>
    </div>
    <p class="hint">
      可以这样说：
      <button class="say" @click="say('重新跑一遍')">重新跑一遍</button>
      <span class="sep">·</span>
      <button class="say" @click="say('看下现在的数据')">看下现在的数据</button>
      <span class="sep">·</span>
      <button class="say" @click="say('看看评论')">看看评论</button>
      <span class="sep">·</span>
      <button class="say" @click="say('这篇论文的局限是什么')">这篇论文的局限是什么</button>
    </p>
    <p class="hint">
      风格：<button class="say" @click="emit('style')">{{ style.current }}</button>
      <span class="sep">·</span>它决定这一轮文章的语气、海报的排版，会写进本次运行的 brief
      <span class="sep">·</span>默认：一篇中文长文 + 一张海报 + 一段讲解视频，三个平台先排稿、发布要你点头
    </p>
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
.say {
  border: none; background: none; padding: 0 1px; cursor: pointer;
  font: inherit; font-size: 12px; color: var(--ink-3);
  border-bottom: 1px dotted var(--line);
}
.say:hover { color: var(--ink); border-bottom-color: var(--ink-3); }
.sep { margin: 0 3px; color: var(--muted-2); }
</style>
