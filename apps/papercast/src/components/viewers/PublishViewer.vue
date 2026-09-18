<script setup lang="ts">
import { computed } from 'vue'
import type { PaperRun } from '../../types'
import { useRunsStore } from '../../stores/runs'

const props = defineProps<{ run: PaperRun }>()
const store = useRunsStore()

const stage = computed(() => props.run.stages.find((s) => s.id === 'publish'))

const CHANNELS = [
  {
    id: 'xhs',
    name: '小红书',
    engine: 'xiaohongshu-mcp · http://localhost:18060',
    needs: ['6 张卡片图', '标题 ≤ 20 字', '正文 + 话题标签'],
    state: 'ready' as const,
    note: 'MCP 已登录，发布前仍有闸门确认',
  },
  {
    id: 'wechat',
    name: '微信公众号',
    engine: '微信草稿箱 API · md2wechat',
    needs: ['微信 HTML 排版', '封面图 900×383', '标题 / 摘要'],
    state: 'warn' as const,
    note: '未配置 AppID / IP 白名单，将降级为本地 HTML 供手动粘贴',
  },
  {
    id: 'bilibili',
    name: 'B 站',
    engine: 'biliup 投稿 CLI',
    needs: ['横版 16:9 视频', '竖版封面', '分区 / 简介 / 标签'],
    state: 'off' as const,
    note: 'biliup 未登录；元数据校验已通过',
  },
]

const targets = computed(() => props.run.config.publish.targets)
const gate = computed(() => stage.value?.gate)
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
        <div class="grow" />
        <button
          v-if="gate && stage.status === 'waiting'"
          class="btn primary sm"
          @click="store.confirm('publish', 'continue')"
        >
          确认发布
        </button>
      </div>

      <div class="cards">
        <article v-for="c in CHANNELS" :key="c.id" class="ch" :class="[c.state, { picked: targets.includes(c.id) }]">
          <div class="row spread">
            <strong class="ch-name">{{ c.name }}</strong>
            <span class="chip" :class="c.state === 'ready' ? 'ok' : c.state === 'warn' ? 'warn' : ''">
              <i class="dot" />{{ c.state === 'ready' ? '就绪' : c.state === 'warn' ? '降级' : '离线' }}
            </span>
          </div>
          <div class="mono ch-engine">{{ c.engine }}</div>
          <div class="row wrap gap">
            <span v-for="n in c.needs" :key="n" class="chip tiny">{{ n }}</span>
          </div>
          <p class="panel-sub ch-note">{{ c.note }}</p>
        </article>
      </div>

      <div class="gate-card">
        <div class="row spread">
          <strong class="g-title">人工闸门：发布不可全自动</strong>
          <span class="chip warn" v-if="stage.status === 'waiting'"><i class="dot" />等待中</span>
        </div>
        <p class="panel-sub">
          上游三份产物（长文 / 海报 / 视频）会先落入本地产物目录，只有闸门放行后才向平台投递；
          公众号走草稿箱而非直接群发，避免一次性推送事故。
        </p>
        <div class="row wrap">
          <button class="btn" @click="store.confirm('publish', 'draft')">仅存草稿</button>
          <button class="btn" @click="store.confirm('publish', 'skip')">本轮不发布</button>
        </div>
      </div>

      <div class="receipts">
        <div class="label">回执与产物</div>
        <div
          v-for="a in stage.artifacts"
          :key="a.id"
          class="receipt"
        >
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
.cards { display: flex; flex-direction: column; gap: 9px; }
.ch { border: 1px solid var(--line-soft); border-radius: 11px; padding: 11px 12px; background: var(--bg-2); display: flex; flex-direction: column; gap: 7px; }
.ch.picked { border-color: rgba(90, 162, 255, 0.35); }
.ch-name { font-size: 13.5px; }
.ch-engine { color: var(--muted-2); font-size: 11px; }
.ch-note { line-height: 1.65; font-size: 11.5px; }
.chip.tiny { font-size: 10.5px; padding: 1px 6px; }
.gate-card { border: 1px solid rgba(255, 180, 58, 0.25); background: rgba(255, 180, 58, 0.06); border-radius: 11px; padding: 12px; display: flex; flex-direction: column; gap: 9px; }
.g-title { font-size: 13px; color: #ffd79a; }
.receipts { display: flex; flex-direction: column; gap: 6px; }
.receipt { display: flex; gap: 10px; align-items: center; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; color: var(--text-2); }
</style>
