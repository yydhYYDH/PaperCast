/** 领域模型：一条「论文 → 多形态产物」的运行 */

export type ViewId = 'workbench' | 'runs' | 'library' | 'settings'

export type StageId = 'intake' | 'understand' | 'article' | 'poster' | 'video' | 'publish'

export type StageStatus = 'pending' | 'running' | 'waiting' | 'done' | 'failed' | 'skipped'

export type RunStatus = 'queued' | 'running' | 'waiting' | 'done' | 'failed'

export type SourceKind = 'arxiv' | 'pdf' | 'latex'

export type ArtifactKind =
  | 'markdown'
  | 'html'
  | 'image'
  | 'video'
  | 'json'
  | 'pptx'
  | 'text'

export interface SourceInput {
  kind: SourceKind
  /** arxiv id / 上传文件名 / latex 工程目录名 */
  value: string
  title?: string
  authors?: string[]
  venue?: string
  pages?: number
  bytes?: number
}

export interface Artifact {
  id: string
  stageId: StageId
  kind: ArtifactKind
  label: string
  /** 虚拟产物路径，如 .papercast/runs/<id>/article/wechat.md */
  path: string
  /** 前端预览地址（本地 samples 或后端静态目录） */
  url?: string
  bytes?: number
  meta?: Record<string, string | number | boolean>
}

export interface LogLine {
  ts: number
  level: 'info' | 'ok' | 'warn' | 'err'
  text: string
}

/** 人工确认闸门：真实 skill 链在关键决策点会停等用户确认 */
export interface StageGate {
  id: string
  label: string
  detail: string
  options: { id: string; label: string; hint?: string }[]
  resolved?: string
}

export interface Stage {
  id: StageId
  label: string
  /** 这一阶段复用的开源实现 */
  engine: string
  status: StageStatus
  progress: number
  startedAt?: number
  endedAt?: number
  logs: LogLine[]
  artifacts: Artifact[]
  gate?: StageGate
  /** 评分/校验条目，例如 poster 的几何检查与盲读测验 */
  checks?: { label: string; state: 'pass' | 'fail' | 'run'; detail: string }[]
}

export interface PaperDigest {
  arxivId: string
  title: string
  authors: string[]
  venue: string
  year: number
  abstractCn: string
  keywords: string[]
  contributions: string[]
  method: string
  results: { label: string; value: string; note: string }[]
  figures: { id: string; caption: string; source: string }[]
  limitations: string[]
  stagesNote: string
}

export interface ArticleVariant {
  id: string
  platform: 'wechat' | 'xhs'
  style: 'academic' | 'media'
  label: string
  url: string
  words?: number
}

export interface RunConfig {
  article: { variants: string[] }
  poster: { size: string; venue: string; theme: string; lang: string }
  video: { durationSec: number; voice: string; aspect: '16:9' | '9:16'; narration: string }
  publish: { targets: string[]; autoPublish: boolean }
}

export interface PaperRun {
  id: string
  createdAt: number
  title: string
  source: SourceInput
  status: RunStatus
  stages: Stage[]
  config: RunConfig
  digest?: PaperDigest
  articles?: ArticleVariant[]
}

export const STAGE_ORDER: StageId[] = ['intake', 'understand', 'article', 'poster', 'video', 'publish']

export const STAGE_META: Record<StageId, { label: string; engine: string; hint: string }> = {
  intake: { label: '输入归一化', engine: 'MinerU · arXiv source', hint: 'PDF / arXiv / LaTeX → 统一 paper 模型' },
  understand: { label: '论文理解层', engine: 'paper2note', hint: '唯一事实源：贡献 / 方法 / 证据 / 图表' },
  article: { label: '文章生成', engine: 'paper2content · paper2wechat', hint: '4 套风格操作系统，微信 + 小红书' },
  poster: { label: 'Poster 生成', engine: 'paper2poster · Paper2Poster', hint: 'Parser → Planner → Painter → 盲读校验' },
  video: { label: '视频合成', engine: 'paper-share-skills · Paper2Video', hint: 'Beamer → 旁白 → TTS → 合成 + 封面' },
  publish: { label: '发布与运营', engine: 'xiaohongshu-mcp · 公众号草稿箱', hint: '小红书 / 公众号 / B 站，人工确认后发出' },
}
