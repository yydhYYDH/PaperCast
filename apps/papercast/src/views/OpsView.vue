<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useOpsStore } from '../stores/ops'
import { useRunsStore } from '../stores/runs'
import { useUiStore } from '../stores/ui'
import { fmtAgo } from '../utils'

const ops = useOpsStore()
const runs = useRunsStore()
const ui = useUiStore()
const tab = ref<'data' | 'services'>('data')

onMounted(() => {
  void ops.refreshServices()
  void ops.loadMetrics()
  void ops.loadLog('backend')
  ops.startLogPolling()
})
onUnmounted(() => ops.stopLogPolling())

const stamp = computed(() => (ops.fetchedAt ? fmtAgo(ops.fetchedAt) + '拉取' : '尚未拉取'))
const logLineCount = computed(() => ops.log?.lines.length ?? 0)

const LOG_LEVEL: Record<string, string> = { error: 'lv-err', warn: 'lv-warn', warning: 'lv-warn' }

/** 互动指标的界面名（后端返回的 stat key 是各平台的原生字段名） */
const STAT_LABEL: Record<string, string> = {
  view: '播放', like: '点赞', coin: '投币', favorite: '收藏',
  reply: '评论', danmaku: '弹幕', share: '分享', comment: '评论',
}
const statLabel = (k: string) => STAT_LABEL[k] ?? k

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
        <p class="page-lead">发出去的内容现在有多少人看、有多少赞；以及这台机器上各个服务还正常吗。</p>
      </div>
      <span class="meta-line">{{ stamp }}</span>
      <button class="btn" :disabled="ops.metricsLoading" @click="refreshMetrics()">
        {{ ops.metricsLoading ? '更新中…' : '更新数据' }}
      </button>
      <button class="btn" :disabled="ops.loading" @click="ops.refreshServices()">
        {{ ops.loading ? '检查中…' : '检查服务' }}
      </button>
    </header>

    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">看什么</span>
        <div class="grow" />
        <span class="panel-sub">{{ stamp }}</span>
      </header>
      <div class="panel-body" style="display: flex; flex-direction: column; gap: 10px">
        <div class="seg" style="max-width: 360px">
          <button :class="{ on: tab === 'data' }" @click="tab = 'data'">看数据</button>
          <button :class="{ on: tab === 'services' }" @click="tab = 'services'">看服务状态</button>
        </div>
        <p v-if="ops.error" class="err-line">操作失败：{{ ops.error }}</p>
      </div>
    </section>

    <!-- ───────── 运营数据 ───────── -->
    <template v-if="tab === 'data'">
      <section class="panel">
        <header class="panel-head">
          <span class="panel-title">各平台表现</span>
          <span class="panel-sub">数字都是从平台真实读取的；读不到的会写明原因，不会用 0 顶替</span>
        </header>
        <div class="panel-body">
          <div v-if="!ops.summary.length" class="empty">还没有数据，点右上角「更新数据」看看。</div>
          <div v-else class="stat-grid">
            <div v-for="row in ops.summary" :key="row.id" class="stat-card">
              <span class="k">{{ row.name }}</span>
              <div class="row wrap" style="gap: 14px">
                <div v-for="m in row.metrics" :key="m.k">
                  <div class="v">{{ m.v }}</div>
                  <div class="s">{{ m.k }}</div>
                </div>
              </div>
              <span v-if="row.note" class="s" :title="row.note">说明：{{ row.note }}</span>
            </div>
          </div>
        </div>
      </section>

      <section v-for="ch in ops.metrics?.channels ?? []" :key="ch.id" class="panel">
        <header class="panel-head">
          <span class="panel-title">{{ ch.name }}</span>
          <span class="chip mono">{{ ch.kind }}</span>
          <span v-if="ch.account?.name" class="chip accent">账号 {{ ch.account.name }}</span>
          <div class="grow" />
          <span class="panel-sub ellipsis" style="max-width: 46%" title="数据来源">{{ ch.source }}</span>
        </header>
        <div class="panel-body stack">
          <div v-if="ch.errors.length" class="warn-line">
            这次没读到数据，原因：
            <span v-for="(e, i) in ch.errors" :key="i">{{ e }}</span>
          </div>
          <table v-if="ch.items.length" class="tbl">
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
                  <div class="sub mono">{{ it.id }}<span v-if="it.author"> · {{ it.author }}</span></div>
                </td>
                <td class="meta-line">{{ fmtTime(it.publishedAt) }}</td>
                <td v-for="(v, key) in it.stats" :key="key">{{ fmtNum(v) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">
            还没有发过内容
            <div class="panel-sub" style="margin-top: 6px">{{ ch.gap || '这台机器上还没有这个平台的发布记录。' }}</div>
          </div>
          <p v-if="ch.gap && ch.items.length" class="panel-sub">说明：{{ ch.gap }}</p>
        </div>
      </section>
    </template>

    <!-- ───────── 服务与日志 ───────── -->
    <template v-else>
      <section class="panel">
        <header class="panel-head">
          <span class="panel-title">这台机器上的服务</span>
          <span class="panel-sub">共 {{ ops.services.length }} 个，正在运行 {{ ops.upCount }} 个</span>
          <div class="grow" />
          <span class="panel-sub">启动 / 停止与在终端里执行命令是一回事</span>
        </header>
        <div class="panel-body">
          <div class="svc-grid">
            <div v-for="s in ops.services" :key="s.name" class="svc" :class="{ down: !s.up }">
              <div class="row">
                <span class="name">{{ s.label }}</span>
                <span class="chip" :class="s.up ? 'ok' : 'err'"><i class="dot" />{{ s.up ? '在线' : '离线' }}</span>
                <div class="grow" />
                <span class="mono meta-line">:{{ s.port }}</span>
              </div>
              <div class="meta-line">
                <span v-if="s.pid" class="mono">pid {{ s.pid }}</span>
                <span v-else class="mono">无 pid</span>
                <span v-if="s.health.probed"> · 健康 {{ s.health.ok ? '正常' : '异常' }} {{ s.health.elapsedMs ?? 0 }}ms</span>
                <span v-else> · {{ s.health.detail }}</span>
              </div>
              <div class="meta-line mono ellipsis" :title="s.log.path">
                {{ s.log.exists ? fmtSize(s.log.size) + ' · ' + fmtAgo(s.log.updatedAt) + '写入' : '无日志' }}
              </div>
              <div class="row wrap" style="gap: 6px">
                <button class="btn sm" :disabled="!!ops.acting || s.up" @click="confirmAction(s.name, s.label, 'start')">启动</button>
                <button class="btn sm" :disabled="!!ops.acting || !s.up" @click="confirmAction(s.name, s.label, 'restart')">重启</button>
                <button class="btn sm danger" :disabled="!!ops.acting || !s.up" @click="confirmAction(s.name, s.label, 'stop')">停止</button>
                <button class="btn sm ghost" @click="ops.loadLog(s.name)">看日志</button>
              </div>
              <div v-if="ops.acting === s.name + ':start' || ops.acting === s.name + ':stop' || ops.acting === s.name + ':restart'" class="panel-sub">
                正在执行…
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <header class="panel-head">
          <span class="panel-title">日志 · {{ ops.logName }}.log</span>
          <div class="grow" />
          <label class="panel-sub" style="display: flex; align-items: center; gap: 5px">
            <input v-model="ops.autoLog" type="checkbox" /> 自动刷新 4s
          </label>
          <input v-model="ops.grep" class="field" style="width: 150px" placeholder="关键字过滤" @keyup.enter="ops.loadLog()" />
          <select v-model.number="ops.logLines" class="field" style="width: 96px" @change="ops.loadLog()">
            <option :value="100">100 行</option>
            <option :value="200">200 行</option>
            <option :value="500">500 行</option>
            <option :value="1000">1000 行</option>
          </select>
          <button class="btn sm" @click="ops.loadLog()">读取</button>
        </header>
        <div class="panel-body stack">
          <div class="row wrap">
            <button
              v-for="s in ops.services"
              :key="s.name"
              class="pill"
              :class="{ on: ops.logName === s.name }"
              @click="ops.loadLog(s.name)"
            >
              {{ s.name }}
            </button>
            <div class="grow" />
            <span class="meta-line mono">{{ ops.log ? ops.log.path : '—' }}</span>
          </div>
          <pre v-if="ops.log && logLineCount" class="logbox"><span
            v-for="(l, i) in ops.log.lines"
            :key="i"
            :class="lineClass(l)"
          >{{ l }}
</span></pre>
          <div v-else class="empty">没有可显示的日志行（服务可能还没启动过，或过滤条件没有命中）。</div>
          <p v-if="ops.log?.truncated" class="panel-sub">
            只显示最后 {{ logLineCount }} 行（匹配 {{ ops.log.matched }} 行），完整日志见上方的路径。
          </p>
        </div>
      </section>

      <section class="panel">
        <header class="panel-head">
          <span class="panel-title">运行概况</span>
          <span class="panel-sub">想看每一次的细节，去「运行记录」页</span>
        </header>
        <div class="panel-body">
          <div class="stat-grid">
            <div class="stat-card"><span class="k">一共跑过</span><div class="v">{{ runStats.total }}</div><span class="s">次</span></div>
            <div class="stat-card"><span class="k">正在跑</span><div class="v">{{ runStats.running }}</div><span class="s">次</span></div>
            <div class="stat-card"><span class="k">等你确认</span><div class="v">{{ runStats.waiting }}</div><span class="s">次</span></div>
            <div class="stat-card"><span class="k">已完成</span><div class="v">{{ runStats.done }}</div><span class="s">次</span></div>
            <div class="stat-card"><span class="k">没成功</span><div class="v">{{ runStats.failed }}</div><span class="s">次</span></div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 10px; }
.err-line { color: var(--err); font-size: 12px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th { text-align: left; padding: 8px 10px; color: var(--muted); font-weight: 600; font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; border-bottom: 1px solid var(--line-soft); }
.tbl td { padding: 9px 10px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; font-variant-numeric: tabular-nums; }
.tbl tr:hover { background: var(--panel-2); }
.tbl a { color: var(--text); text-decoration: none; }
.tbl a:hover { color: var(--accent); text-decoration: underline; }
.sub { color: var(--muted-2); font-size: 11px; margin-top: 2px; }
.warn-line { font-size: 12px; color: #b45309; background: rgba(245, 158, 11, 0.09); border: 1px solid rgba(245, 158, 11, 0.26); border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; gap: 3px; }
.pill.on { background: var(--accent-soft); border: 1px solid rgba(79, 70, 229, 0.3); color: #4338ca; font-weight: 600; cursor: pointer; }
.pill { cursor: pointer; border: 1px solid transparent; }
.pill:hover { background: var(--panel-3); }
</style>
