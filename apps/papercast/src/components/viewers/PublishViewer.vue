<script setup lang="ts">
import { computed, onMounted } from 'vue'
import type { PaperRun } from '../../types'
import { useRunsStore } from '../../stores/runs'
import { normalizeChannelId, usePlatformsStore } from '../../stores/platforms'
import { PLATFORM_STATE } from '../../utils'

const props = defineProps<{ run: PaperRun }>()
const store = useRunsStore()
const platforms = usePlatformsStore()

const stage = computed(() => props.run.stages.find((s) => s.id === 'publish'))

/** 渠道的静态说明（投递要求）；登录态一律取平台 store 的真实探测结果 */
const CHANNELS = [
  {
    id: 'xhs',
    name: '小红书',
    needs: ['6 张卡片图', '标题 ≤ 20 字', '正文 + 话题标签'],
    note: '发布前仍有一道人工确认',
  },
  {
    id: 'zhihu',
    name: '知乎',
    needs: ['标题 + 纯文本正文', '话题 / 标签'],
    note: '需要在本机弹出的窗口里人工登录；发布仍需人工确认',
  },
  {
    id: 'bilibili',
    name: 'B 站',
    needs: ['横版 16:9 视频', '竖版封面', '分区 / 简介 / 标签'],
    note: '需要先扫码登录；元数据校验已通过',
  },
  {
    id: 'x',
    name: 'X（推特）',
    needs: ['英文传播：6-10 条英文 thread'],
    note: '只把英文 thread 落成本地素材包，不接投递通道 —— 这一轮不会真的发到 X',
  },
]

const targets = computed(() => props.run.config.publish.targets)
const gate = computed(() => stage.value?.gate)

function stateOf(id: string) {
  return platforms.channel(normalizeChannelId(id))?.state
}
function infoOf(id: string) {
  return platforms.channel(normalizeChannelId(id))
}
function stateLabel(id: string) {
  const s = stateOf(id)
  return s ? PLATFORM_STATE[s].label : '未探测'
}
function stateCls(id: string) {
  const s = stateOf(id)
  return s ? PLATFORM_STATE[s].cls : ''
}
function noteOf(id: string, fallback: string) {
  return infoOf(id)?.detail || fallback
}

/** 只出素材包的渠道（X）：判定在 store 里（不算就绪、也不算未就绪），这里只管说一句话 */
const materialOnly = computed(() => platforms.materialOnlyTargets(targets.value))
/** 勾选了但登录态没就绪的渠道：这些渠道本轮投不出去（原始写法，'xiaohongshu' 与 'xhs' 等价） */
const blocked = computed(() => platforms.targetsBlocked(targets.value))
/** 中文名，用于文案展示 */
const blockedNames = computed(() => blocked.value.map((id) => infoOf(id)?.name ?? id))
/** 只有「一个能投的渠道都没有」时才拦住确认发布；否则投出去的照投，未就绪的跳过 */
const canConfirm = computed(() =>
  targets.value.length === 0 ? true : platforms.anyTargetReady(targets.value),
)

onMounted(() => {
  if (!platforms.channels.length) void platforms.refresh(false)
})
</script>

<template>
  <div class="publish">
    <div v-if="!stage" class="empty">发布阶段尚未开始</div>
    <template v-else>
      <div class="row wrap gap head">
        <span class="chip" :class="stage.status === 'waiting' ? 'warn' : stage.status === 'done' ? 'ok' : ''">
          <i class="dot" />{{ stage.status === 'waiting' ? '待人工放行' : stage.status === 'done' ? '已提交' : '准备中' }}
        </span>
        <span class="muted">本轮勾选：{{ targets.length ? targets.join(' · ') : '未选择渠道' }}</span>
        <span v-if="blocked.length" class="chip warn"><i class="dot" />{{ blocked.length }} 个渠道未就绪</span>
        <div class="grow" />
        <button class="btn sm" @click="platforms.refresh(true)">刷新渠道状态</button>
        <button
          v-if="gate && stage.status === 'waiting'"
          class="btn primary sm"
          :disabled="!canConfirm"
          :title="canConfirm ? '发布前请确认产物无误' : '勾选的渠道全都没就绪：先完成扫码登录 / 配置凭证'"
          @click="store.confirm('publish', 'continue')"
        >
          确认发布
        </button>
      </div>

      <p v-if="materialOnly.length" class="muted">
        {{ materialOnly.map((id) => infoOf(id)?.name ?? id).join('、') }}：只出素材包，不真发 —— 稿子会落在本地，可手动贴上去。
      </p>

      <p v-if="blocked.length" class="warn-line">
        未就绪的渠道：{{ blockedNames.join('、') }}，本轮不会投递它们。
        <template v-if="!canConfirm">所有勾选渠道都没就绪，只能走「仅存草稿」或「本轮不发布」。</template>
        <button v-if="stateOf('xhs') !== 'ready'" class="link" @click="platforms.openLogin('xhs')">扫码登录小红书 →</button>
      </p>

      <div class="cards">
        <article v-for="c in CHANNELS" :key="c.id" class="ch" :class="[stateOf(c.id) ?? 'unknown', { picked: targets.includes(c.id) }]">
          <div class="row spread">
            <strong class="ch-name">{{ c.name }}</strong>
            <span class="chip" :class="stateCls(c.id)"><i class="dot" />{{ stateLabel(c.id) }}</span>
            <span v-if="infoOf(c.id)?.account" class="chip accent">账号 {{ infoOf(c.id)?.account }}</span>
            <div class="grow" />
            <button v-if="c.id === 'xhs'" class="btn sm" @click="platforms.openLogin('xhs')">
              {{ stateOf('xhs') === 'ready' ? '切换账号' : '扫码登录' }}
            </button>
          </div>

          <div class="row wrap gap">
            <span v-for="n in c.needs" :key="n" class="chip tiny">{{ n }}</span>
          </div>
          <p class="panel-sub ch-note">{{ noteOf(c.id, c.note) }}</p>
        </article>
      </div>

      <div class="gate-card">
        <div class="row spread">
          <strong class="g-title">人工闸门：发布不可全自动</strong>
          <span class="chip warn" v-if="stage.status === 'waiting'"><i class="dot" />等待中</span>
        </div>
        <p class="panel-sub">
          上游三份产物（长文 / 海报 / 视频）会先落入本地产物目录，只有闸门放行后才向平台投递；
          投递前会二次确认账号与素材，登录态只在闸门放行后被动用，未登录时按钮不可点。
        </p>
        <div class="row wrap">
          <button class="btn" @click="store.confirm('publish', 'draft')">仅存草稿</button>
          <button class="btn" @click="store.confirm('publish', 'skip')">本轮不发布</button>
        </div>
      </div>

      <div class="receipts">
        <div class="label">回执与产物</div>
        <div v-for="a in stage.artifacts" :key="a.id" class="receipt">
          <span class="grow">{{ a.label }}</span>
          <span class="mono muted-2">{{ a.path }}</span>
        </div>
        <div v-if="!stage.artifacts.length" class="panel-sub">阶段完成后生成发布回执</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.publish { padding: 14px; display: flex; flex-direction: column; gap: 13px; overflow-y: auto; }
.head { gap: 8px; }
.gap { gap: 6px; }
.warn-line { font-size: 12px; color: #b45309; background: rgba(245, 158, 11, 0.09); border: 1px solid rgba(245, 158, 11, 0.26); border-radius: 10px; padding: 8px 10px; line-height: 1.7; }
.link { color: var(--accent); text-decoration: underline; font-size: 12px; }
.cards { display: flex; flex-direction: column; gap: 9px; }
.ch { border: 1px solid var(--line-soft); border-radius: 11px; padding: 11px 12px; background: var(--bg-2); display: flex; flex-direction: column; gap: 7px; }
.ch.picked { border-color: rgba(79, 70, 229, 0.35); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.07); }
.ch.ready { border-color: rgba(16, 185, 129, 0.32); }
.ch.offline { border-color: rgba(239, 68, 68, 0.28); }
.ch.login_required, .ch.blocked { border-color: rgba(245, 158, 11, 0.32); }
.ch-name { font-size: 13.5px; }
.ch-engine { color: var(--muted-2); font-size: 11px; }
.ch-note { line-height: 1.65; font-size: 11.5px; }
.chip.tiny { font-size: 10.5px; padding: 1px 6px; }
.gate-card { border: 1px solid rgba(245, 158, 11, 0.25); background: rgba(245, 158, 11, 0.07); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 9px; }
.g-title { font-size: 13px; color: #b45309; font-weight: 600; }
.receipts { display: flex; flex-direction: column; gap: 6px; }
.receipt { display: flex; gap: 10px; align-items: center; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; color: var(--text-2); }
</style>