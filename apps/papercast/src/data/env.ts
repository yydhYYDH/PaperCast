/** 环境依赖与引擎映射：既用于状态条，也用于「设置」页的架构说明 */

export interface EnvDep {
  id: string
  label: string
  detail: string
  state: 'ok' | 'warn' | 'off'
}

export const ENV_DEPS: EnvDep[] = [
  { id: 'mineru', label: 'MinerU', detail: 'PDF → Markdown（云端 API 或本地 GPU）', state: 'ok' },
  { id: 'tex', label: 'LaTeX', detail: 'Beamer 幻灯片编译（xelatex）', state: 'ok' },
  { id: 'tts', label: 'TTS', detail: 'zh-CN-XiaoxiaoNeural · edge-tts', state: 'ok' },
  { id: 'xhs', label: '小红书 MCP', detail: 'localhost:18060 · 已登录', state: 'ok' },
  { id: 'wechat', label: '公众号草稿箱', detail: 'AppID / IP 白名单未配置，降级为本地 HTML', state: 'warn' },
  { id: 'biliup', label: 'biliup', detail: 'B 站投稿 CLI · 未登录', state: 'off' },
  { id: 'ffmpeg', label: 'ffmpeg', detail: '视频合成与转码', state: 'warn' },
]

export interface EngineRow {
  stage: string
  engine: string
  reusedFrom: string
  note: string
}

/** 每个阶段复用的开源实现（来自本次 GitHub 调研） */
export const ENGINE_ROWS: EngineRow[] = [
  { stage: '输入归一化', engine: 'MinerU + arxiv source', reusedFrom: 'paper-share-skills/pdf-to-markdown · paper2anything/scripts/parse_pdf.py', note: 'PDF 与 LaTeX 两条入口统一到同一份 content.md' },
  { stage: '论文理解层', engine: 'paper2note', reusedFrom: 'pickxiguapi/paper2x', note: '单一事实源：下游 4 个产物共用 digest.json' },
  { stage: '文章生成', engine: '4 套风格操作系统', reusedFrom: 'kangw24/paper2content · QuZhan51496/paper2anything · flyanx/paper-to-wechat', note: '微信/小红书 × 学术/媒体' },
  { stage: 'Poster', engine: 'Parser→Planner→Painter', reusedFrom: 'paper2anything/paper2poster · Paper2Poster/Paper2Poster', note: '几何检查 + 盲读者内容测验作为验收门' },
  { stage: '视频', engine: 'Beamer → 旁白 → TTS → 合成', reusedFrom: 'yhbcode000/paper-share-skills · showlab/Paper2Video', note: '横竖双版本 + 封面，可断点续跑' },
  { stage: '发布', engine: 'xiaohongshu-mcp / 公众号草稿箱 / biliup', reusedFrom: 'xpzouying/xiaohongshu-mcp · wechat-article-skills · biliup', note: '三个渠道均有人工闸门，不自动群发' },
]
