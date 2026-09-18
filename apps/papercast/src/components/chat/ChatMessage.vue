<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import type { ChatMessage } from '../../stores/chat'
import type { Artifact, PaperRun } from '../../types'

const props = defineProps<{ msg: ChatMessage; run?: PaperRun }>()
const emit = defineEmits<{ gate: [string] }>()

const VIEWERS = {
  digest: defineAsyncComponent(() => import('../viewers/DigestViewer.vue')),
  article: defineAsyncComponent(() => import('../viewers/ArticleViewer.vue')),
  poster: defineAsyncComponent(() => import('../viewers/PosterViewer.vue')),
  video: defineAsyncComponent(() => import('../viewers/VideoViewer.vue')),
  publish: defineAsyncComponent(() => import('../viewers/PublishViewer.vue')),
}

const open = ref(false)
const viewer = computed(() => (props.msg.viewer && props.run ? VIEWERS[props.msg.viewer] : null))
/** 有产物就能展开；展开后按阶段渲染对应查看器（懒加载，不展开不下载） */
const canOpen = computed(() => !!viewer.value && !!props.msg.artifacts?.length)

const KIND_ICON: Record<string, string> = { markdown: '文', html: '版', image: '图', video: '影', json: '数', text: '字', pptx: '讲' }
function icon(a: Artifact) {
  return KIND_ICON[a.kind] ?? '件'
}
function size(a: Artifact) {
  if (!a.bytes) return ''
  return a.bytes > 1024 * 1024 ? `${(a.bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(a.bytes / 1024)} KB`
}
function name(a: Artifact) {
  return a.label || a.path.split('/').pop() || a.path
}
</script>

<template>
  <!-- 用户：右对齐 -->
  <div v-if="msg.role === 'user'" class="msg msg-user">
    <div class="bubble">
      <p class="u-text">{{ msg.text }}</p>
      <p v-if="msg.bullets?.length" class="u-meta">{{ msg.bullets.join(' · ') }}</p>
    </div>
  </div>

  <!-- Agent：名字 + 一段人话 + 可选产物 -->
  <div v-else class="msg msg-agent">
    <span class="badge" :class="{ live: msg.pending }">{{ msg.who.slice(0, 1) }}</span>
    <div class="body">
      <div class="who">
        {{ msg.who }}
        <span v-if="msg.pending" class="dots"><i /><i /><i /></span>
      </div>
      <p class="text">{{ msg.text }}</p>
      <ul v-if="msg.bullets?.length" class="bullets">
        <li v-for="(b, i) in msg.bullets" :key="i">{{ b }}</li>
      </ul>

      <!-- 产物：先给一行文件名，想看细节再展开查看器 -->
      <div v-if="msg.artifacts?.length" class="arts">
        <span v-for="a in msg.artifacts" :key="a.id" class="art" :title="a.path">
          <i class="ic">{{ icon(a) }}</i>{{ name(a) }}
          <em v-if="size(a)">{{ size(a) }}</em>
        </span>
        <button v-if="canOpen" class="btn sm ghost toggle" @click="open = !open">
          {{ open ? '收起' : '展开看' }}
        </button>
      </div>
      <div v-if="open && viewer && run" class="stage-view">
        <component :is="viewer" :run="run" />
      </div>

      <!-- 等你点头：只在真需要人决定的地方出现，默认动作排第一 -->
      <div v-if="msg.gate" class="gate">
        <p class="gate-q">{{ msg.gate.label }}</p>
        <p v-if="msg.gate.detail" class="gate-d">{{ msg.gate.detail }}</p>
        <div class="row wrap">
          <button
            v-for="(o, i) in msg.gate.options"
            :key="o.id"
            class="btn sm"
            :class="i === 0 ? 'primary' : 'ghost'"
            @click="emit('gate', o.id)"
          >
            {{ o.label }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg { display: flex; gap: 12px; }
.msg-user { justify-content: flex-end; }
.bubble {
  max-width: 86%;
  background: #f1f0ec;
  border-radius: 14px 14px 4px 14px;
  padding: 10px 15px;
}
.u-text { font-size: 15px; color: var(--text); line-height: 1.7; }
.u-meta { font-size: 12.5px; color: var(--muted); margin-top: 4px; }

.msg-agent { align-items: flex-start; }
.badge {
  flex: none;
  width: 26px; height: 26px; margin-top: 2px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--surface);
  display: grid; place-items: center;
  font-family: var(--serif); font-size: 13px; color: var(--ink);
}
.badge.live { border-color: #cfe3d6; color: var(--tone-green-fg, #346538); }
.body { min-width: 0; flex: 1; }
.who { font-family: var(--serif); font-size: 14px; color: var(--text); display: flex; align-items: center; gap: 6px; }
.text { font-size: 15.5px; line-height: 1.85; color: var(--text-2); margin-top: 2px; }
.bullets { margin: 8px 0 0; padding-left: 18px; color: var(--muted); font-size: 13.5px; }
.bullets li { margin: 2px 0; }

.arts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; align-items: center; }
.art {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--line); border-radius: 999px;
  padding: 3px 11px 3px 5px;
  font-size: 12.5px; color: var(--text-2); background: var(--surface);
}
.art .ic {
  font-style: normal; font-size: 11px; color: var(--muted);
  width: 17px; height: 17px; border-radius: 50%; background: var(--panel-3);
  display: grid; place-items: center;
}
.art em { font-style: normal; color: var(--muted-2); font-size: 11.5px; }
.toggle { margin-left: 2px; }
.stage-view { margin-top: 14px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }

.gate { margin-top: 12px; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: var(--surface-2); }
.gate-q { font-family: var(--serif); font-size: 15px; color: var(--text); }
.gate-d { font-size: 13px; color: var(--muted); margin: 4px 0 10px; }
.dots { display: inline-flex; gap: 3px; }
.dots i { width: 3px; height: 3px; border-radius: 50%; background: var(--muted-2); animation: b 1.2s infinite; }
.dots i:nth-child(2) { animation-delay: 0.15s; }
.dots i:nth-child(3) { animation-delay: 0.3s; }
@keyframes b { 0%, 60%, 100% { opacity: 0.25 } 30% { opacity: 1 } }
</style>
