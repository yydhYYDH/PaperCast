import type { PaperRun } from './types'

/**
 * Agent 审核（前端流程里的第七步）。
 *
 * 为什么放在前端：**能用真数据核的就别问模型**。
 * 后端每个阶段都落了自己那一段的 `checks`（label / state / detail），这里把它们汇总，
 * 再补两条只有前端才知道的交叉检查（事实源在不在、走完的环节有没有产物），
 * 于是「Agent 审核」是一句**可复核**的话，而不是一个装饰性的打勾。
 *
 * state 的来源与含义（后端 stage.checks 的约定）：
 *   pass 通过了 · fail 没过（人工闸门上方要说出来）· run 说明类（例如「只落盘，不会真的发出去」）
 */

export type ReviewItemState = 'pass' | 'fail' | 'run' | 'warn' | 'skip' | string

export interface ReviewItem {
  label: string
  state: ReviewItemState
  detail: string
  /** 哪一步的检查（阶段 label，或「审核」= 前端补的交叉检查） */
  from: string
}

export interface Review {
  items: ReviewItem[]
  passed: number
  /** 说明类（不需要动手），例如「没有可投递渠道，素材包已就绪」 */
  notes: ReviewItem[]
  failed: ReviewItem[]
  verdict: 'pass' | 'blocked'
  /** 人工闸门上方那句话（用户点名要的） */
  line: string
  /** 一句话交代核了多少项 */
  detail: string
  /** 还在跑的时候不要说「已经通过」——那是假话 */
  settled: boolean
}

const EMPTY: Review = {
  items: [],
  passed: 0,
  notes: [],
  failed: [],
  verdict: 'pass',
  line: 'Agent 审核：还没有可审的东西',
  detail: '',
  settled: false,
}

export function reviewRun(run: PaperRun | undefined): Review {
  if (!run) return EMPTY

  const items: ReviewItem[] = []
  for (const stage of run.stages) {
    for (const c of stage.checks ?? []) {
      items.push({ label: c.label, state: c.state, detail: c.detail, from: stage.label || stage.id })
    }
  }

  // 交叉检查一：事实源（后端 checks 里看不到「digest 到底在不在」）
  const understand = run.stages.find((s) => s.id === 'understand')
  const hasDigest = !!run.digest || !!understand?.artifacts.some((a) => a.path.endsWith('digest.json'))
  if (understand && understand.status !== 'pending') {
    items.push({
      label: '事实源：论文理解层',
      state: hasDigest ? 'pass' : 'fail',
      detail: hasDigest
        ? '摘要 / 贡献 / 方法 / 局限都在，下面所有文案只允许引用它'
        : '没有找到 digest.json —— 后面的内容没有可核对的事实源',
      from: '审核',
    })
  }

  // 交叉检查二：走完的环节有没有留下产物
  const finished = run.stages.filter((s) => ['done', 'waiting', 'failed'].includes(s.status))
  const silent = finished.filter((s) => s.artifacts.length === 0)
  if (finished.length) {
    items.push({
      label: '产物齐备',
      state: silent.length ? 'fail' : 'pass',
      detail: silent.length
        ? `这 ${silent.length} 个环节走完了却没留下产物：${silent.map((s) => s.label).join('、')}`
        : `${finished.length} 个走完的环节都留下了产物`,
      from: '审核',
    })
  }

  const failed = items.filter((i) => i.state === 'fail')
  const notes = items.filter((i) => i.state === 'run' || i.state === 'warn')
  const passed = items.filter((i) => i.state === 'pass').length
  const settled = run.stages.every((s) => !['pending', 'running', 'queued'].includes(s.status))
  const verdict: Review['verdict'] = failed.length ? 'blocked' : 'pass'

  let line: string
  if (!items.length) line = 'Agent 审核：还没有可审的东西'
  else if (failed.length) line = `Agent 审核没通过：${failed.length} 项要你决定（${failed.map((f) => f.label).join('、')}）`
  else if (!settled) line = 'Agent 审核：已出来的这部分核过了，还在跑'
  else line = 'Agent 审核已经通过'

  const detail = items.length
    ? `核了 ${items.length} 项：${passed} 项通过` +
      (notes.length ? `，${notes.length} 项是说明` : '') +
      (failed.length ? `，${failed.length} 项没过` : '，没有发现要改的')
    : ''

  return { items, passed, notes, failed, verdict, line, detail, settled }
}
