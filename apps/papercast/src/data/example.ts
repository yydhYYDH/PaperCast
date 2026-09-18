import type { RunConfig, SourceInput } from '../types'

/**
 * 默认示例：**只在这一个文件里定义**。
 *
 * 之前这份元数据在 IntakePanel（写死了 authors: ['Zayn Zhu', 'Show Lab']）与
 * mock 的种子运行（Zeyu Zhu / Kevin Qinghong Lin / Mike Zheng Shou）各存一份，
 * 两处不一致 —— 示例是用户看到的第一眼，错名字最扎眼。收敛到这里。
 */
export const EXAMPLE_PAPER = {
  arxivId: '2510.05096',
  url: 'https://arxiv.org/abs/2510.05096',
  title: 'Paper2Video: Automatic Video Generation from Scientific Papers',
  authors: ['Zeyu Zhu', 'Kevin Qinghong Lin', 'Mike Zheng Shou'],
  venue: 'NeurIPS 2025 · SEA Workshop',
  pages: 17,
} as const

/** 示例来源。离线兜底用：不联网也能显示完整元数据 */
export function exampleSource(): SourceInput {
  return {
    kind: 'arxiv',
    value: EXAMPLE_PAPER.arxivId,
    title: EXAMPLE_PAPER.title,
    authors: [...EXAMPLE_PAPER.authors],
    venue: EXAMPLE_PAPER.venue,
    pages: EXAMPLE_PAPER.pages,
  }
}

/** 工作台默认配置：面板初值与「一键跑示例」共用，避免两处漂移 */
export const EXAMPLE_RUN_CONFIG: RunConfig = {
  article: { variants: ['xhs-author'] },
  poster: { size: '36×48 in', venue: 'NeurIPS 2025', theme: 'default', lang: 'en' },
  video: { durationSec: 300, voice: 'zh-CN-XiaoxiaoNeural', aspect: '16:9', narration: '中文' },
  publish: { targets: ['xhs', 'zhihu'], autoPublish: false },
}

/** 深拷贝一份：store.submit 会改这份配置，别把常量本身交出去 */
export function exampleRunConfig(): RunConfig {
  return JSON.parse(JSON.stringify(EXAMPLE_RUN_CONFIG)) as RunConfig
}

/** 示例产物的根目录：某阶段还没产出时，查看器回退到这里 */
export const SAMPLE_BASE = '/samples'

export function sampleAsset(...parts: string[]): string {
  return [SAMPLE_BASE, ...parts].join('/')
}
