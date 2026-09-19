<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { SkillDetail, SkillInfo, StyleOption } from '../api/types'
import { useStyleStore } from '../stores/style'
import { useUiStore } from '../stores/ui'

/**
 * 风格 · 个性化层。
 *
 * 这一页回答两个问题，顺序就是用户的疑问顺序：
 *   1. 这一轮文章写成什么样？—— 平台 × 口吻（「小红书 · 专业科普」「知乎 · 专业解读」…），
 *      选项与硬约束来自后端 app/styles.py，勾中的就是这次运行的 config.article.variants；
 *   2. 界面/文档按哪套规矩？—— 仓库自带的风格技能（原文直接读 SKILL.md，界面里不抄二手版本）。
 *
 * 本机 ~/.agents/skills 装的第三方技能不在这里展示（用户 2026-09-19 要求），只留仓库自带的。
 */

const style = useStyleStore()
const ui = useUiStore()

const opened = ref('')
const detail = ref<SkillDetail | null>(null)
const loading = ref(false)

onMounted(() => void style.load())

const groups = computed(() => [
  { key: 'style', title: '界面与文档规范', note: '决定界面怎么长、助手怎么跟你说话', rows: style.styleSkills },
  { key: 'other', title: '其它技能', note: '和界面风格无关，但同样跟着仓库走', rows: style.otherSkills },
].filter((g) => g.rows.length))

/** 一条风格勾上 / 取消；超上限时如实说原因 */
function toggleStyle(variant: string) {
  const r = style.toggle(variant)
  if (!r.ok) ui.toast(r.reason, 'err', 4000)
}

function isPicked(variant: string) {
  return style.picked.includes(variant)
}

/** 平台的硬约束一句话（长度 / 公式 / 标签 / 卡片 / 标题）—— 人格改不了这些 */
function constraint(s: StyleOption): string {
  const len = s.unit === 'words'
    ? s.bodyMin + '-' + s.bodyMax + ' 词'
    : (s.bodyMin ? s.bodyMin + '-' + s.bodyMax + ' 字' : '≤' + s.bodyMax + ' 字')
  const title = s.titleWeightMax
    ? '标题计重 ≤' + s.titleWeightMax
    : (s.titleCharsMax ? '标题 ≤' + s.titleCharsMax + (s.unit === 'words' ? ' 字符' : ' 字') : '')
  return [
    len,
    s.allowFormula ? '允许公式' : '无公式',
    s.tagsMin ? '标签 ' + s.tagsMin + '-' + s.tagsMax : '',
    title,
    s.cards ? '出 3:4 卡片' : '',
  ].filter(Boolean).join(' · ')
}

async function toggle(name: string) {
  if (opened.value === name) {
    opened.value = ''
    return
  }
  opened.value = name
  detail.value = null
  loading.value = true
  try {
    detail.value = await api.skill(name)
  } catch (e) {
    ui.toast('读不到这个技能的规矩：' + (e as Error).message, 'err')
    opened.value = ''
  } finally {
    loading.value = false
  }
}

function pick(s: SkillInfo) {
  style.use(s.name)
  ui.toast('界面与文档规范换成「' + s.name + '」了，下一轮开始时生效', 'info', 4000)
}

/** SKILL.md 原文按纯文本展示（不引 markdown 渲染库）：等宽、可滚动、可复制 */
const bodyLines = computed(() => (detail.value?.body ?? '').split('\n'))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">风格</h1>
        <p class="page-lead">同样的论文，写成什么样由这里定：先挑平台，再挑口吻。</p>
      </div>
      <span class="meta-line">{{ style.loading ? '读取中…' : '' }}</span>
      <button class="btn" :disabled="style.loading" @click="style.load(true)">重新读一遍</button>
    </header>

    <!-- 一句话结论：这次到底会生成什么 -->
    <section class="panel">
      <div class="panel-body verdict">
        <p class="lead-line">
          这一轮会生成：{{ style.effectiveLabel }}<template v-if="style.effectiveIsDefault">（没选，用工作台默认）</template>
        </p>
        <p class="src">
          也可以在对话里直接说 —— 「做成小红书+知乎，用机器之心的口吻」，说到的平台与口吻会覆盖这里的选择；
          发布仍然要你点头，风格管不到闸门。
        </p>
      </div>
    </section>

    <p v-if="style.menuError" class="err-line">
      读不到风格清单：{{ style.menuError }} —— 它来自后端只读端点 <code>GET /api/styles</code>。
    </p>

    <!-- 平台 × 口吻 -->
    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">文章风格</span>
        <div class="grow" />
        <span class="panel-sub">平台决定体裁与硬约束，口吻只决定语气 · 最多 {{ style.maxVariants }} 个</span>
      </header>
      <div class="panel-body">
        <div v-for="g in style.platformGroups" :key="g.id" class="pgroup">
          <div class="pg-head">
            <span class="pg-name">{{ g.label }}</span>
            <span class="pg-note">{{ constraint(g.rows[0]) }}</span>
          </div>
          <ul class="lines">
            <li v-for="r in g.rows" :key="r.variant" :class="{ off: !isPicked(r.variant) }">
              <span class="dot" />
              <span class="pname">{{ r.short }}</span>
              <span class="pline grow ellipsis" :title="r.hint">{{ r.hint }}</span>
              <span v-if="r.sampled === '1'" class="pnum">有语料支撑</span>
              <button class="btn sm" :class="{ ghost: !isPicked(r.variant) }" @click="toggleStyle(r.variant)">
                {{ isPicked(r.variant) ? '取消' : '用这个' }}
              </button>
            </li>
          </ul>
        </div>
        <p v-if="!style.platformGroups.length && !style.menuError" class="src">还没读到风格清单。</p>
        <p v-if="style.picked.length" class="foot-note">
          已选 {{ style.picked.length }} / {{ style.maxVariants }} 个：{{ style.effectiveLabel }}
          <button class="say" @click="style.clearPicked()">清空，用默认</button>
        </p>
      </div>
    </section>

    <!-- 界面与文档规范（仓库自带的技能） -->
    <section v-for="g in groups" :key="g.key" class="panel">
      <header class="panel-head">
        <span class="panel-title">{{ g.title }}</span>
        <div class="grow" />
        <span class="panel-sub">{{ g.note }}</span>
      </header>
      <div class="panel-body">
        <ul class="lines">
          <li v-for="s in g.rows" :key="s.name" :class="{ off: style.current !== s.name }">
            <span class="dot" />
            <span class="pname">{{ s.name }}</span>
            <span class="pline grow ellipsis" :title="s.description">{{ s.description }}</span>
            <span v-if="s.references.length" class="pnum">含 {{ s.references.length }} 份分册</span>
            <span v-if="style.current === s.name" class="chip ok"><i class="dot" />在用</span>
            <button class="btn sm ghost" @click="toggle(s.name)">{{ opened === s.name ? '收起规矩' : '看它的规矩' }}</button>
            <button v-if="style.current !== s.name" class="btn sm" @click="pick(s)">用这个</button>
          </li>
        </ul>

        <div v-if="opened" class="detail">
          <p v-if="loading" class="panel-sub">正在读 {{ opened }}/SKILL.md…</p>
          <template v-else-if="detail">
            <div class="src-line">{{ detail.dir }}/SKILL.md<template v-if="detail.truncated">（太长，只显示前 6 万字）</template></div>
            <pre class="skill-body"><span v-for="(l, i) in bodyLines" :key="i">{{ l }}
</span></pre>
          </template>
        </div>
      </div>
    </section>

    <p v-if="style.error" class="err-line">
      读不到技能目录：{{ style.error }} —— 技能由后端从本机只读目录里列出来（<code>GET /api/skills</code>）。
    </p>

    <p class="foot-note">
      这里只列仓库自带的规范（跟着代码提交）<template v-if="style.hiddenSkillCount">，
      本机另有 {{ style.hiddenSkillCount }} 个用户级技能（~/.agents/skills）按你的要求不展示</template>。
      文章风格写进这次运行的生成配置，随时能在运行记录里看到当时用的是哪几条。
    </p>
  </div>
</template>

<style scoped>
.verdict { display: flex; flex-direction: column; gap: 8px; }
.lead-line { font-family: var(--serif); font-size: 20px; line-height: 1.5; color: var(--text); }
.src { font-size: 12px; color: var(--muted-2); line-height: 1.6; }
.err-line { color: var(--err); font-size: 12.5px; }

.pgroup { border-bottom: 1px solid var(--line-soft); padding: 4px 0 8px; }
.pgroup:last-child { border-bottom: none; }
.pg-head { display: flex; align-items: baseline; gap: 10px; padding: 10px 2px 2px; flex-wrap: wrap; }
.pg-name { font-family: var(--serif); font-size: 15px; color: var(--text); }
.pg-note { font-size: 11.5px; color: var(--muted-2); }

.lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.lines li { display: flex; align-items: center; gap: 10px; padding: 9px 2px; border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }
.lines li:last-child { border-bottom: none; }
.lines .dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: #8fb79b; }
.lines li.off .dot { background: #ddd9d2; }
.pname { font-size: 13px; color: var(--text); min-width: 88px; }
.pline { font-size: 13px; color: var(--muted); }
.pnum { font-size: 12px; color: var(--muted-2); white-space: nowrap; }
.say { font: inherit; color: var(--muted-2); background: none; border: none; padding: 0 0 0 6px; cursor: pointer; text-decoration: underline; }
.detail { margin-top: 12px; }
.src-line { font-family: var(--mono); font-size: 11.5px; color: var(--muted-2); margin-bottom: 6px; }
.skill-body {
  background: var(--surface-2); border: 1px solid var(--hairline); border-radius: 10px;
  padding: 14px 16px; max-height: 420px; overflow: auto;
  font-family: var(--mono); font-size: 12px; line-height: 1.7; color: var(--ink-2);
  white-space: pre-wrap; word-break: break-word;
}
.foot-note { font-size: 12px; color: var(--muted-2); padding: 0 2px 8px; line-height: 1.7; }
.foot-note code { font-family: var(--mono); font-size: 11.5px; background: #f1f0ec; padding: 1px 5px; border-radius: 5px; }

/* 手机：名字一行、说明一行、按钮一行 —— 别让「含 N 份分册」把整行顶出屏幕 */
@media (max-width: 720px) {
  .lines li { gap: 8px; }
  .pname { min-width: 0; }
  .pline { flex: 1 1 100%; order: 3; }
  .pnum { order: 4; }
  .lines li .btn { order: 5; }
  .lead-line { font-size: 16.5px; line-height: 1.6; }
  .src { font-size: 11.5px; }
  .skill-body { max-height: 320px; padding: 12px; font-size: 11.5px; }
}
</style>
