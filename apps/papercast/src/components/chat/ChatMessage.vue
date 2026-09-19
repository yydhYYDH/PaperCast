<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import type { ChatMessage } from '../../stores/chat'
import type { Artifact, PaperRun } from '../../types'
import { reviewRun } from '../../review'

const props = defineProps<{ msg: ChatMessage; run?: PaperRun }>()
/** action 的第二个参数：true = 照这张卡办，false = 先不做 */
const emit = defineEmits<{ gate: [string]; action: [id: string, go: boolean] }>()

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

/**
 * Agent 审核：**前端自己算**的那份汇总（数据来自后端每个阶段的真实 checks），
 * 用在两处 —— 闸门上方那一句「Agent 审核已经通过」，以及这条审核消息下面的检查项。
 */
const review = computed(() => reviewRun(props.run))

/** 先亮要处理的，没有要处理的再亮几条通过的（让"通过"也有证据，而不是一句空话） */
const reviewItemsShown = computed(() => {
  const items = props.msg.reviewItems ?? []
  const bad = items.filter((i) => i.state !== 'pass')
  return (bad.length ? bad : items.filter((i) => i.state === 'pass')).slice(0, 5)
})

const KIND_ICON: Record<string, string> = { markdown: '文', html: '版', image: '图', video: '影', json: '数', text: '字', pptx: '讲' }
function icon(a: Artifact) {
  return KIND_ICON[a.kind] ?? '件'
}
/** 检查项的标题常常是「英文传播（X / LinkedIn） × 技术解读 · 指令遵从度 · 侧重」这种长串：
 *  胶囊里只留最前面那段（完整内容在 title 里），否则一行被它一个人占满。 */
function short(label: string) {
  const head = label.split(' · ')[0]
  return head.length > 22 ? head.slice(0, 22) + '…' : head
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

      <!-- 一句话就能派活：后端给的动作卡。点了才真的执行 —— 对话不会绕过人工闸门 -->
      <div
        v-if="msg.action && msg.action.needsConfirm"
        class="act"
        :class="{ done: msg.act === 'done', failed: msg.act === 'failed' }"
      >
        <p class="act-t">{{ msg.action.title }}</p>
        <p v-if="msg.action.detail" class="act-d">{{ msg.action.detail }}</p>
        <p v-if="msg.action.risk === 'public'" class="act-risk">这一步会真的发到平台上，发出去撤不回来。</p>
        <div v-if="msg.act === 'idle' || msg.act === 'running'" class="row wrap">
          <button
            class="btn sm"
            :class="msg.action.risk === 'public' ? 'danger' : 'primary'"
            :disabled="msg.act === 'running'"
            @click="emit('action', msg.id, true)"
          >
            {{ msg.act === 'running' ? '正在做…' : msg.action.confirmLabel }}
          </button>
          <button class="btn sm ghost" :disabled="msg.act === 'running'" @click="emit('action', msg.id, false)">
            先不做
          </button>
        </div>
        <p v-else-if="msg.act === 'done'" class="act-note">{{ msg.actNote || '已经照这个办了。' }}</p>
        <p v-else class="act-err">没做成：{{ msg.actNote }}</p>
      </div>
      <!--
        只读动作（看数据、读一遍评论这类）不等用户点：
        - 正在做：写清**在做什么**（读一遍平台要真开一次浏览器，几十秒，不能只写「正在照做…」）；
        - 没做成：留一行持久的原因 —— 只有一条会自己消失的 toast 等于没回执（2026-09-19 踩到）；
        - 做完了：这里不写字，结果由紧随其后的那条回执消息说。
      -->
      <p
        v-if="msg.action && !msg.action.needsConfirm && msg.act === 'running'"
        class="act-wait"
      >正在照做：{{ msg.action.title }}…</p>
      <p v-else-if="msg.action && !msg.action.needsConfirm && msg.act === 'failed'" class="act-err">
        没做成：{{ msg.actNote }}
      </p>

      <!-- 审核的检查项：只亮要处理的（没有就亮几条通过的），别把几十项全铺出来 -->
      <div v-if="msg.reviewItems?.length" class="checks">
        <span
          v-for="i in reviewItemsShown"
          :key="i.label"
          class="chk"
          :class="i.state"
          :title="i.label + ' —— ' + i.detail + '（' + i.from + '）'"
        >
          {{ short(i.label) }}
        </span>
        <span class="chk more">共 {{ msg.reviewItems.length }} 项检查</span>
      </div>

      <!-- 等你点头：只在真需要人决定的地方出现，默认动作排第一 -->
      <div v-if="msg.gate" class="gate">
        <!-- 人工审核时先说清：机器已经替你核过一遍了（通过了才这么说，没通过就如实写） -->
        <p class="gate-review" :class="{ bad: review.verdict === 'blocked' }">
          <span class="tick">{{ review.verdict === 'blocked' ? '!' : '✓' }}</span>
          <span>{{ review.line }}</span>
          <span v-if="review.detail" class="gate-review-d"> · {{ review.detail }}</span>
        </p>
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
/* 手机：字号收一号，气泡更宽，产物胶囊一定是换行而不是顶破右边界 */
@media (max-width: 720px) {
  .msg { gap: 9px; }
  .bubble { max-width: 94%; padding: 9px 13px; }
  .u-text { font-size: 15px; }
  .badge { width: 24px; height: 24px; font-size: 12px; }
  .who { font-size: 13.5px; }
  .text { font-size: 15px; line-height: 1.8; }
  .bullets { font-size: 13px; padding-left: 16px; }
  .art { max-width: 100%; }
  .art em { flex: none; }
}
.checks { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 4px; }
.chk {
  font-size: 11.5px; padding: 2px 8px; border-radius: 999px;
  background: var(--surface-2); border: 1px solid var(--line-soft); color: var(--ink-3);
}
.chk.pass { background: var(--tone-green-bg); border-color: transparent; color: var(--tone-green-fg); }
.chk.run, .chk.warn { background: var(--tone-amber-bg); border-color: transparent; color: var(--tone-amber-fg); }
.chk.fail { background: var(--tone-red-bg); border-color: transparent; color: var(--tone-red-fg); }
.chk.more { color: var(--muted-2); background: none; border-color: var(--line); }
.gate-review {
  display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap;
  font-size: 12.5px; color: var(--tone-green-fg); margin-bottom: 2px;
}
.gate-review.bad { color: var(--tone-red-fg); }
.gate-review .tick { font-weight: 700; }
.gate-review-d { color: var(--muted); }
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

.act { margin-top: 12px; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: var(--surface); }
.act.done { background: var(--surface-2); border-color: transparent; }
.act.failed { border-color: var(--tone-red-bg); }
.act-t { font-family: var(--serif); font-size: 15px; color: var(--text); }
.act-d {
  font-size: 13px; line-height: 1.7; color: var(--muted);
  margin: 4px 0 10px; white-space: pre-wrap;
  max-height: 168px; overflow: auto;
}
.act-risk {
  display: inline-block; margin: 0 0 10px; padding: 5px 9px; border-radius: 8px;
  background: var(--tone-amber-bg); color: var(--tone-amber-fg); font-size: 12.5px;
}
.act-note { font-size: 12.5px; color: var(--muted); }
.act-err { font-size: 12.5px; color: var(--tone-red-fg); }
.act-wait { font-size: 12.5px; color: var(--muted-2); margin-top: 8px; }

.gate { margin-top: 12px; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: var(--surface-2); }
.gate-q { font-family: var(--serif); font-size: 15px; color: var(--text); }
.gate-d { font-size: 13px; color: var(--muted); margin: 4px 0 10px; }
.dots { display: inline-flex; gap: 3px; }
.dots i { width: 3px; height: 3px; border-radius: 50%; background: var(--muted-2); animation: b 1.2s infinite; }
.dots i:nth-child(2) { animation-delay: 0.15s; }
.dots i:nth-child(3) { animation-delay: 0.3s; }
@keyframes b { 0%, 60%, 100% { opacity: 0.25 } 30% { opacity: 1 } }
</style>
