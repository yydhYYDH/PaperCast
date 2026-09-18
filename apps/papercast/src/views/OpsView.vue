<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useOpsStore } from '../stores/ops'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'
import { fmtAgo } from '../utils'

/**
 * 运营维护：**先说结论，再给细节**。
 *
 * 用户明确要「去仪表盘化、尽量简洁、只留结论」，所以这一页的结构是：
 *   一句人话结论 + 最多三个关键数字 + 数据来源  →  每个平台一行  →  服务和日志（默认折叠）
 * 数字全部来自平台真实接口；读不到就写成一句原因，不用 0 顶替，也不藏起来。
 */

const ops = useOpsStore()
const runs = useRunsStore()
const ui = useUiStore()

/** 折叠状态：默认全部收起，页面上先只有结论 */
const expanded = ref<Record<string, boolean>>({})
const showServices = ref(false)
const showLog = ref(false)
function toggle(key: string) {
  expanded.value[key] = !expanded.value[key]
}

onMounted(() => {
  void ops.refreshServices()
  void ops.loadMetrics()
  void ops.loadLog('backend')
  ops.startLogPolling()
})
onUnmounted(() => ops.stopLogPolling())

const stamp = computed(() => (ops.metrics?.fetchedAt ? fmtAgo(ops.metrics.fetchedAt) + '更新' : '尚未拉取'))
const logLineCount = computed(() => ops.log?.lines.length ?? 0)

const LOG_LEVEL: Record<string, string> = { error: 'lv-err', warn: 'lv-warn', warning: 'lv-warn' }

/** 互动指标的界面名（后端返回的 stat key 是各平台的原生字段名） */
const STAT_LABEL: Record<string, string> = {
  view: '播放', like: '点赞', coin: '投币', favorite: '收藏',
  reply: '评论', danmaku: '弹幕', share: '分享', comment: '评论',
}
const statLabel = (k: string) => STAT_LABEL[k] ?? k
/** 取一个平台最该被看见的那个数：先看播放，再看点赞……都没有就不显示数字 */
const PRIMARY = ['view', 'like', 'reply', 'comment', 'coin', 'favorite', 'share', 'danmaku']

function lineClass(line: string) {
  const l = line.toLowerCase()
  if (l.includes('error') || l.includes('traceback') || l.includes('failed')) return LOG_LEVEL.error
  if (l.includes('warn')) return LOG_LEVEL.warn
  if (l.includes(' 200 ') || l.includes('ok')) return LOG_LEVEL.ok
  return ''
}

function fmtSize(bytes: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function fmtNum(v: number | null | undefined) {
  return typeof v === 'number' ? v.toLocaleString('zh-CN') : '—'
}

function fmtTime(ms?: number) {
  return ms ? new Date(ms).toLocaleString('zh-CN', { hour12: false }) : '—'
}

const ACTION_LABEL: Record<string, string> = { start: '启动', stop: '停止', restart: '重启' }

/** 拉一次数据并给个回执（否则用户点了不知道有没有反应） */
async function refreshMetrics() {
  await ops.loadMetrics(true)
  if (ops.error) ui.toast('更新失败：' + ops.error, 'err')
  else ui.toast('数据已更新', 'info', 3000)
}

async function confirmAction(name: string, label: string, action: 'start' | 'stop' | 'restart') {
  if (action !== 'start') {
    const ok = await ui.askConfirm({
      title: `${ACTION_LABEL[action]}「${label}」？`,
      text: action === 'stop'
        ? '停掉之后，这个渠道暂时不能登录也不能发布；想恢复点「启动」就行。'
        : '重启需要几秒钟，这期间这个渠道不可用。',
      okLabel: ACTION_LABEL[action],
      tone: action === 'stop' ? 'err' : 'info',
    })
    if (!ok) return
  }
  const res = await ops.act(name, action)
  if (res) {
    ui.toast(`${label} 已${ACTION_LABEL[action]}`, 'info')
    void ops.loadLog(name, { silent: true })
  } else if (ops.error) {
    ui.toast(`${ACTION_LABEL[action]}失败：` + ops.error, 'err')
  }
}

/* ───────── 把原始数据压成「一句结论 + 最多三个数」 ───────── */

interface ChannelLine {
  id: string
  name: string
  line: string
  num: string
  items: { id: string; title: string; url: string; author?: string; publishedAt?: number; stats: Record<string, number | null> }[]
  reason: string
  source: string
  kind: string
  account?: string
}

const channels = computed<ChannelLine[]>(() =>
  (ops.metrics?.channels ?? []).map((ch) => {
    const items = ch.items ?? []
    const reason = (ch.errors ?? [])[0] || (items.length ? '' : ch.gap || '这台机器上还没有这个平台的发布记录。')
    const key = items.length ? PRIMARY.find((k) => k in (items[0].stats ?? {})) ?? '' : ''
    const total = key ? items.reduce((n, it) => n + (Number(it.stats?.[key]) || 0), 0) : 0
    return {
      id: ch.id,
      name: ch.name,
      kind: ch.kind,
      account: ch.account?.name,
      source: ch.source,
      items,
      reason,
      line: items.length
        ? `${items.length} 条内容${items[0].publishedAt ? '，最近一条 ' + new Date(items[0].publishedAt).toLocaleDateString('zh-CN') : ''}`
        : '还没发过内容',
      num: key ? `${statLabel(key)} ${fmtNum(total)}` : '',
    }
  }),
)

/** 一句结论：能把真实数字加起来就加，加不出来就如实说读不到 */
const verdict = computed(() => {
  const rows = channels.value
  const withData = rows.filter((r) => r.items.length)
  const totals = new Map<string, number>()
  for (const r of withData) {
    for (const it of r.items) {
      for (const [k, v] of Object.entries(it.stats ?? {})) {
        if (typeof v === 'number') totals.set(k, (totals.get(k) ?? 0) + v)
      }
    }
  }
  const keys = PRIMARY.filter((k) => totals.has(k))
    .slice(0, 3)
    .map((k) => ({ k: statLabel(k), v: fmtNum(totals.get(k) ?? 0) }))

  const itemCount = rows.reduce((n, r) => n + r.items.length, 0)
  const sources = [...new Set(rows.filter((r) => r.items.length).map((r) => r.source).filter(Boolean))]

  let lead: string
  if (!itemCount && !keys.length) {
    const why = rows.map((r) => r.reason).filter(Boolean)[0]
    lead = why ? `现在还读不到任何数字 —— ${why}` : '现在还读不到任何数字，点右上角「更新数据」再试一次。'
  } else {
    lead = `已发出 ${itemCount} 条内容` + (keys.length ? `，合计 ${keys.map((x) => `${x.v} 个${x.k}`).join('、')}。` : '。')
  }

  const caveat = rows
    .filter((r) => !r.items.length && r.reason)
    .map((r) => `${r.name}：${r.reason}`)
    .slice(0, 2)
    .join(' ')

  return { lead, keys, caveat, source: sources.length ? sources.join(' · ') : '各平台接口（详见每个平台的展开项）' }
})

/** 服务：一句话总结 + 谁掉队了 */
const svcLine = computed(() => {
  const all = ops.services
  if (!all.length) return '还没检查过服务。'
  const down = all.filter((s) => !s.up)
  return down.length
    ? `${all.length} 个服务里有 ${down.length} 个没在跑：${down.map((s) => s.label).join('、')}。`
    : `这台机器上的 ${all.length} 个服务都在跑。`
})

/** 运行概况：一句话而不是五张卡 */
const runLine = computed(() => {
  const s = runStats.value
  if (!s.total) return '还没有跑过。'
  const parts = [`一共跑过 ${s.total} 次`]
  if (s.done) parts.push(`${s.done} 次完成`)
  if (s.running) parts.push(`${s.running} 次正在跑`)
  if (s.waiting) parts.push(`${s.waiting} 次等你确认`)
  if (s.failed) parts.push(`${s.failed} 次没成功`)
  return parts.join('，') + '。想看每一次的细节去「运行记录」。'
})

const runStats = computed(() => {
  const all = runs.runs || []
  return {
    total: all.length,
    running: all.filter((r) => r.status === 'running').length,
    waiting: all.filter((r) => r.status === 'waiting').length,
    done: all.filter((r) => r.status === 'done').length,
    failed: all.filter((r) => r.status === 'failed').length,
  }
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">运营维护</h1>
        <p class="page-lead">发出去的内容现在有多少人看、有多少赞；这台机器上的服务还正常吗。</p>
      </div>
      <span class="meta-line">{{ stamp }}</span>
      <button class="btn" :disabled="ops.loading" @click="ops.refreshServices()">
        {{ ops.loading ? '检查中…' : '检查服务' }}
      </button>
      <button class="btn" :disabled="ops.metricsLoading" @click="refreshMetrics()">
        {{ ops.metricsLoading ? '更新中…' : '更新数据' }}
      </button>
    </header>

    <p v-if="ops.error" class="err-line">操作失败：{{ ops.error }}</p>

    <!-- ── 一句结论 ── -->
    <section class="panel">
      <div class="panel-body verdict">
        <p class="lead-line">{{ verdict.lead }}</p>
        <div v-if="verdict.keys.length" class="keys">
          <div v-for="k in verdict.keys" :key="k.k" class="key">
            <b>{{ k.v }}</b><span>{{ k.k }}</span>
          </div>
        </div>
        <p v-if="verdict.caveat" class="caveat">{{ verdict.caveat }}</p>
        <p class="src">数字来源：{{ verdict.source }} · {{ stamp }}</p>
      </div>
    </section>

    <!-- ── 各个平台：一行一个，细节收起来 ── -->
    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">各个平台</span>
        <div class="grow" />
        <span class="panel-sub">读不到的会写明原因，不会用 0 顶替</span>
      </header>
      <div class="panel-body">
        <div v-if="!channels.length" class="empty">还没有数据，点右上角「更新数据」看看。</div>
        <template v-else>
          <ul class="lines">
            <li v-for="ch in channels" :key="ch.id" :class="{ off: !ch.items.length }">
              <span class="dot" />
              <span class="pname">{{ ch.name }}</span>
              <span class="pline grow ellipsis" :title="ch.reason || ch.line">{{ ch.reason || ch.line }}</span>
              <span v-if="ch.num" class="pnum">{{ ch.num }}</span>
              <button v-if="ch.items.length" class="btn sm ghost" @click="toggle(ch.id)">
                {{ expanded[ch.id] ? '收起明细' : '看明细' }}
              </button>
            </li>
          </ul>

          <!-- 展开项用 template+v-if 包起来（v-for 与 v-if 不能同层）：没内容时整段不渲染，
               否则模板会去读 items[0].stats（空数组 → 组件渲染报错、onMounted 也不再执行） -->
          <template v-for="ch in channels" :key="ch.id + '-d'">
          <div v-if="expanded[ch.id] && ch.items.length" class="detail">
            <div class="row wrap meta-line" style="margin-bottom: 8px">
              <span v-if="ch.account">账号 {{ ch.account }}</span>
              <span class="grow" />
              <span class="ellipsis" :title="ch.source">{{ ch.source }}</span>
            </div>
            <table class="tbl">
              <thead>
                <tr>
                  <th>内容</th>
                  <th>发布时间</th>
                  <th v-for="key in Object.keys(ch.items[0].stats)" :key="key">{{ statLabel(key) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="it in ch.items" :key="it.id">
                  <td>
                    <a :href="it.url" target="_blank" rel="noreferrer">{{ it.title || it.id }}</a>
                  </td>
                  <td class="meta-line">{{ fmtTime(it.publishedAt) }}</td>
                  <td v-for="(v, key) in it.stats" :key="key">{{ fmtNum(Number(v)) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          </template>
        </template>
      </div>
    </section>

    <!-- ── 服务与日志：默认收起 ── -->
    <section class="panel">
      <button class="fold" @click="showServices = !showServices">
        <span class="grow">{{ svcLine }}</span>
        <span class="fold-cue">{{ showServices ? '收起' : '展开' }}</span>
      </button>

      <div v-show="showServices" class="panel-body stack">
        <ul class="lines">
          <li v-for="s in ops.services" :key="s.name" :class="{ off: !s.up }">
            <span class="dot" />
            <span class="pname">{{ s.label }}</span>
            <span class="pline grow ellipsis" :title="s.health.detail">
              {{ s.up ? '在跑' : '没在跑' }}<template v-if="s.up"> · {{ fmtAgo(s.log.updatedAt) }}有日志</template>
              <template v-else> · {{ s.health.detail || '点「启动」就能拉起来' }}</template>
            </span>
            <button class="btn sm" :disabled="!!ops.acting || s.up" @click="confirmAction(s.name, s.label, 'start')">启动</button>
            <button class="btn sm" :disabled="!!ops.acting || !s.up" @click="confirmAction(s.name, s.label, 'restart')">重启</button>
            <button class="btn sm danger" :disabled="!!ops.acting || !s.up" @click="confirmAction(s.name, s.label, 'stop')">停止</button>
            <button class="btn sm ghost" @click="showLog = true; ops.loadLog(s.name)">看日志</button>
          </li>
        </ul>

        <div class="row wrap">
          <button class="btn sm ghost" @click="showLog = !showLog">
            {{ showLog ? '收起日志' : `看日志（${ops.logName}）` }}
          </button>
          <span class="grow" />
          <span class="meta-line mono ellipsis" :title="ops.log?.path">{{ ops.log ? ops.log.path : '—' }}</span>
        </div>

        <template v-if="showLog">
          <div class="row wrap">
            <button
              v-for="s in ops.services"
              :key="s.name"
              class="pill"
              :class="{ on: ops.logName === s.name }"
              @click="ops.loadLog(s.name)"
            >
              {{ s.label }}
            </button>
            <div class="grow" />
            <label class="panel-sub" style="display: flex; align-items: center; gap: 5px">
              <input v-model="ops.autoLog" type="checkbox" /> 自动刷新 4s
            </label>
            <input v-model="ops.grep" class="field" style="width: 140px" placeholder="关键字过滤" @keyup.enter="ops.loadLog()" />
            <button class="btn sm" @click="ops.loadLog()">读取</button>
          </div>
          <pre v-if="ops.log && logLineCount" class="logbox"><span
            v-for="(l, i) in ops.log.lines"
            :key="i"
            :class="lineClass(l)"
          >{{ l }}
</span></pre>
          <div v-else class="empty">没有可显示的日志行（服务可能还没启动过，或过滤条件没有命中）。</div>
          <p v-if="ops.log?.truncated" class="panel-sub">
            只显示最后 {{ logLineCount }} 行（匹配 {{ ops.log.matched }} 行），完整日志见上面的路径。
          </p>
        </template>
      </div>
    </section>

    <!-- ── 运行概况：一句话 ── -->
    <section class="panel">
      <div class="panel-body">
        <p class="lead-line small">{{ runLine }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 10px; }
.err-line { color: var(--err); font-size: 12.5px; }

/* 结论区：一句话 + 三个数 + 来源 */
.verdict { display: flex; flex-direction: column; gap: 12px; }
.lead-line { font-family: var(--serif); font-size: 21px; line-height: 1.5; color: var(--text); }
.lead-line.small { font-size: 16px; color: var(--text-2); }
.keys { display: flex; gap: 34px; flex-wrap: wrap; }
.key { display: flex; align-items: baseline; gap: 7px; }
.key b {
  font-family: var(--serif); font-size: 30px; font-weight: 500;
  letter-spacing: -0.02em; color: var(--text); font-variant-numeric: tabular-nums;
}
.key span { font-size: 12.5px; color: var(--muted); }
.caveat { font-size: 13px; color: var(--tone-amber-fg, #956400); }
.src { font-size: 12px; color: var(--muted-2); }

/* 平台 / 服务：一行一条，不是卡片墙 */
.lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.lines li {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 2px; border-bottom: 1px solid var(--line-soft);
}
.lines li:last-child { border-bottom: none; }
.lines .dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: #8fb79b; }
.lines li.off .dot { background: #ddd9d2; }
.pname { font-size: 13.5px; color: var(--text); min-width: 72px; }
.pline { font-size: 13px; color: var(--muted); }
.pnum { font-size: 13px; color: var(--text-2); font-variant-numeric: tabular-nums; white-space: nowrap; }

/* 折叠条 */
.fold {
  display: flex; align-items: center; gap: 12px; width: 100%;
  padding: 16px 20px; text-align: left;
  font-family: var(--serif); font-size: 15.5px; color: var(--text-2);
}
.fold:hover { background: var(--surface-2); }
.fold-cue { font-family: var(--sans); font-size: 12.5px; color: var(--muted-2); }

.detail { padding: 12px 2px 4px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th {
  text-align: left; padding: 7px 10px; color: var(--muted); font-weight: 600; font-size: 11px;
  letter-spacing: 0.05em; text-transform: uppercase; border-bottom: 1px solid var(--line-soft);
}
.tbl td { padding: 8px 10px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; font-variant-numeric: tabular-nums; }
.tbl a { color: var(--text); text-decoration: none; }
.tbl a:hover { color: var(--accent); text-decoration: underline; }
:deep(.pill) { cursor: pointer; }
:deep(.pill.on) { background: var(--ink, #111); border-color: var(--ink, #111); color: #fff; }
</style>
