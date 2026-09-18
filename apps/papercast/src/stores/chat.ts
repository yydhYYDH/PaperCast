import { defineStore } from 'pinia'
import { api } from '../api'
import { exampleRunConfig } from '../data/example'
import { useRunsStore } from './runs'
import { useUiStore } from './ui'
import type { Artifact, PaperRun, Stage, StageGate, StageId, StageStatus } from '../types'

/**
 * 对话式入口：把一次运行「翻译成一段聊天」。
 *
 * 设计取舍：
 * 1. **不新造一份状态** —— 消息由 runs store 里那条运行推导出来（源数据只有一个，
 *    不会出现「界面说完成、状态说还在跑」这种漂移）；
 * 2. 只有真正的用户/助手对话（自由提问、模型回答）才落到 `turns` 里；
 * 3. 每句话都只引用真实数据（阶段状态、产物清单、自检结果、最后一条日志），
 *    推不出来的数字就不写。
 */

export type ViewerId = 'digest' | 'article' | 'poster' | 'video' | 'publish'

export interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  /** 说话的人：你 / 取论文 / 读懂 / 写作 / 视觉 / 视频 / 运营 / 助手 */
  who: string
  text: string
  bullets?: string[]
  stageId?: StageId
  state?: StageStatus
  artifacts?: Artifact[]
  viewer?: ViewerId
  gate?: StageGate
  /** 正在干活（右侧名单里也会亮） */
  pending?: boolean
}

interface AgentSpec {
  id: StageId
  who: string
  /** 正在干的事（进行时，用在「谁在干活」里） */
  doing: string
  viewer?: ViewerId
}

export const AGENTS: AgentSpec[] = [
  { id: 'intake', who: '取论文', doing: '把论文取下来' },
  { id: 'understand', who: '读懂', doing: '读论文', viewer: 'digest' },
  { id: 'article', who: '写作', doing: '写中文长文', viewer: 'article' },
  { id: 'poster', who: '视觉', doing: '做海报', viewer: 'poster' },
  { id: 'video', who: '视频', doing: '剪讲解视频', viewer: 'video' },
  { id: 'publish', who: '运营', doing: '排各平台的投放', viewer: 'publish' },
]

const STAGE_STATE_LABEL: Record<StageStatus, string> = {
  pending: '还没轮到',
  running: '正在做',
  waiting: '等你点头',
  done: '做完了',
  failed: '没成功',
  skipped: '跳过',
}

const CHANNEL_NAME: Record<string, string> = {
  xhs: '小红书',
  xiaohongshu: '小红书',
  zhihu: '知乎',
  bilibili: 'B 站',
}

function artifactLabel(a: Artifact) {
  return a.label || a.path.split('/').pop() || a.path
}

/** 一个阶段 → 一句人话；只用真实数据，凑不出来就说得笼统一点 */
function sayStage(stage: Stage, run: PaperRun): { text: string; bullets?: string[] } {
  const names = stage.artifacts.map(artifactLabel)
  const failed = (stage.checks ?? []).filter((c) => c.state === 'fail')
  const bullets = failed.map((c) => `自检没过：${c.label}（${c.detail}）`)

  switch (stage.id) {
    case 'intake':
      return {
        text: [
          '论文到手了' + (run.source.pages ? `（${run.source.pages} 页）` : '') + '，正文和图我都拆开存好了。',
          names.length ? `先放在这里：${names.slice(0, 4).join('、')}。` : '',
        ].join(''),
      }
    case 'understand':
      return {
        text: '读完了。方法、结论、局限我分三块整理过，重点都在下面的「论文理解」里 —— 有读错的地方直接说，我改。',
        bullets,
      }
    case 'article':
      return {
        text: names.length
          ? `文章写好了，一共 ${names.length} 版：${names.join('、')}。`
          : '文章写好了。',
        bullets,
      }
    case 'poster':
      return {
        text: names.length ? `海报出好了：${names.join('、')}。` : '海报出好了。',
        bullets,
      }
    case 'video':
      return {
        text: run.config?.video?.durationSec
          ? `讲解视频备好了（约 ${Math.round(run.config.video.durationSec / 60)} 分钟），带中文字幕。`
          : '讲解视频备好了。',
        bullets,
      }
    case 'publish': {
      const targets = (run.config?.publish?.targets ?? []).map((t) => CHANNEL_NAME[t] ?? t)
      return {
        text: targets.length
          ? `${targets.join('、')} 的稿子都排好队了。真正的发布要你点头，我不会自己发。`
          : '投放的稿子排好队了。真正的发布要你点头，我不会自己发。',
        bullets,
      }
    }
    default:
      return { text: '这一步做完了。' }
  }
}

function lastLine(stage: Stage) {
  const l = stage.logs[stage.logs.length - 1]
  return l ? l.text.replace(/\s+/g, ' ').slice(0, 60) : ''
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    /** 只有自由对话（用户提问 + 模型回答）落这里；流水线的叙述是推导出来的 */
    turns: [] as ChatMessage[],
    asking: false,
    uploading: false,
    error: '',
    turnSeq: 0,
  }),

  getters: {
    run(): PaperRun | undefined {
      return useRunsStore().active
    },

    messages(state): ChatMessage[] {
      const out: ChatMessage[] = []
      const run = this.run

      if (!run) {
        out.push({
          id: 'greet',
          role: 'agent',
          who: '助手',
          text: '把论文丢进来就行 —— 链接、PDF 都可以。我会把它读一遍，写成一篇中文长文、一张海报和一段讲解视频；中间该你决定的地方我会停下来问你。',
        })
        return [...out, ...state.turns]
      }

      out.push({
        id: 'paper',
        role: 'user',
        who: '你',
        text: run.source.title || run.title || run.source.value,
        bullets: [
          run.source.authors?.length ? run.source.authors.join('、') : '',
          run.source.venue || '',
          run.source.pages ? `${run.source.pages} 页` : '',
        ].filter(Boolean),
      })

      for (const spec of AGENTS) {
        const stage = run.stages.find((s) => s.id === spec.id)
        if (!stage) continue
        const started = stage.status !== 'pending'
        if (!started) continue
        const { text, bullets } = sayStage(stage, run)
        out.push({
          id: `stage-${stage.id}`,
          role: 'agent',
          who: spec.who,
          stageId: stage.id,
          state: stage.status,
          text,
          bullets,
          artifacts: stage.artifacts,
          viewer: spec.viewer,
          gate: stage.status === 'waiting' && stage.gate && !stage.gate.resolved ? stage.gate : undefined,
        })
      }

      const running = run.stages.find((s) => s.status === 'running')
      if (running) {
        const spec = AGENTS.find((a) => a.id === running.id)
        out.push({
          id: 'now',
          role: 'agent',
          who: spec?.who ?? '它',
          stageId: running.id,
          state: 'running',
          pending: true,
          text: (spec ? `正在${spec.doing}` : '正在干活') + (lastLine(running) ? `：${lastLine(running)}` : '…'),
        })
      }

      return [...out, ...state.turns]
    },

    /** 右侧「谁在干活」：六个 Agent 的状态行 */
    roster(): { id: StageId; who: string; doing: string; state: StageStatus; activity: string; artifacts: number }[] {
      const run = this.run
      if (!run) return []
      return AGENTS.map((a) => {
        const stage = run.stages.find((s) => s.id === a.id)
        const state = stage?.status ?? 'pending'
        const activity =
          state === 'running'
            ? lastLine(stage!) || `正在${a.doing}`
            : state === 'waiting'
              ? '等你点头'
              : state === 'done'
                ? stage?.artifacts.length
                  ? `${stage.artifacts.length} 件产物`
                  : '做完了'
                : STAGE_STATE_LABEL[state]
        return { id: a.id, who: a.who, doing: a.doing, state, activity, artifacts: stage?.artifacts.length ?? 0 }
      })
    },
  },

  actions: {
    /** 自由提问 → 模型（带上当前运行的事实源） */
    async ask(text: string) {
      const t = text.trim()
      if (!t || this.asking) return
      const runs = useRunsStore()
      this.turns.push({ id: `u${++this.turnSeq}`, role: 'user', who: '你', text: t })
      this.asking = true
      this.error = ''
      try {
        const history = this.turns.slice(-8, -1).map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }))
        const res = await api.chat({ message: t, runId: runs.activeId, history })
        this.turns.push({ id: `a${++this.turnSeq}`, role: 'agent', who: '助手', text: res.reply })
      } catch (e) {
        this.error = (e as Error).message
        // 除了气泡，也在这里留一句：否则对话看上去像断了
        this.turns.push({
          id: `e${++this.turnSeq}`,
          role: 'agent',
          who: '助手',
          text:
            '这次没答上来：' +
            this.error +
            '。如果是刚改完后端，重启一次后端就好；如果是没配模型，去「设置 → 模型与 API」填上密钥。',
        })
        useUiStore().toast('问模型失败：' + this.error, 'err')
      } finally {
        this.asking = false
      }
    },

    /** 本地回一句（不花模型的钱，用于「我看不懂你这句话」这类即时反馈） */
    note(text: string) {
      this.turns.push({ id: `n${++this.turnSeq}`, role: 'agent', who: '助手', text })
    },

    /**
     * 统一入口：链接 / PDF / 一句话。
     * - 有文件 → 上传后按 pdf 提交；
     * - 文本里能认出论文（arXiv 链接或 id）→ 直接开跑；
     * - 其它文本 → 当成对模型的提问。
     */
    async send(text: string, file?: File | null) {
      const runs = useRunsStore()
      if (file) {
        if (file.name.toLowerCase().endsWith('.pdf') === false) {
          this.note('我目前只认 PDF 或 arXiv / LaTeX 的论文，这个文件我先放下不动。')
          return
        }
        this.uploading = true
        try {
          const up = await api.uploadPaper(file)
          if (up.uploadId) {
            await runs.submit(
              { kind: 'pdf', value: up.uploadId, title: up.filename.replace(/\.pdf$/i, ''), bytes: up.bytes },
              exampleRunConfig(),
            )
          }
        } catch (e) {
          this.error = (e as Error).message
          useUiStore().toast('上传失败：' + this.error, 'err')
        } finally {
          this.uploading = false
        }
        return
      }

      const paper = parsePaper(text)
      if (paper) {
        await runs.submit(paper, exampleRunConfig())
        return
      }
      if (/^https?:\/\//i.test(text.trim())) {
        this.note('这个链接我拿不到正文 —— 现在支持的是 arXiv 链接/编号，或者直接把 PDF 拖进来。')
        return
      }
      await this.ask(text)
    },
  },
})

/** 从一句话里认出论文：arXiv 链接、arXiv 编号、arxiv:xxxx */
export function parsePaper(text: string): { kind: 'arxiv'; value: string; url?: string } | null {
  const t = text.trim()
  const link = t.match(/arxiv\.org\/(?:abs|pdf)\/([0-9]{4}\.[0-9]{4,5}|[a-z-]+\/[0-9]{7})(v\d+)?/i)
  if (link) return { kind: 'arxiv', value: link[1] + (link[2] ?? ''), url: t }
  const bare = t.match(/\b(\d{4}\.\d{4,5})(v\d+)?\b/)
  if (bare) return { kind: 'arxiv', value: bare[1] + (bare[2] ?? '') }
  const old = t.match(/\barxiv:([a-z-]+\/[0-9]{7})\b/i)
  if (old) return { kind: 'arxiv', value: old[1] }
  return null
}
