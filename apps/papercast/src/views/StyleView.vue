<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { SkillDetail, SkillInfo } from '../api/types'
import { useStyleStore } from '../stores/style'
import { useUiStore } from '../stores/ui'

/**
 * 风格 · 个性化层。
 *
 * 这一页要回答三个问题，顺序就是用户的疑问顺序：
 *   1. 现在是什么风格？（一句结论，不是一堆开关）
 *   2. 还有哪些风格、它们各自管什么？（每个技能的 description，来自 SKILL.md 本身）
 *   3. 凭什么信？（「看它的规矩」直接读 SKILL.md 原文 —— 界面里不抄一份会过期的二手版本）
 *
 * 界面风格（这一页长什么样）由本仓库的 papercast-frontend 技能管；
 * 这里的选项管的是**这一轮内容**写成什么样（并进 brief，见 stores/chat.ts 的 runConfig）。
 */

const style = useStyleStore()
const ui = useUiStore()

const opened = ref('')
const detail = ref<SkillDetail | null>(null)
const loading = ref(false)

onMounted(() => void style.load())

const groups = computed(() => [
  { key: 'style', title: '风格技能', note: '决定文章的语气、海报的排版、以及助手怎么跟你说话', rows: style.styleSkills },
  { key: 'other', title: '其它技能', note: '和界面风格无关，但同样在这台机器上', rows: style.otherSkills },
].filter((g) => g.rows.length))

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
  ui.toast(`风格换成「${s.name}」了，下一轮开始时生效`, 'info', 4000)
}

/** SKILL.md 原文按纯文本展示（不引 markdown 渲染库）：等宽、可滚动、可复制 */
const bodyLines = computed(() => (detail.value?.body ?? '').split('\n'))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">风格</h1>
        <p class="page-lead">个性化层：选一套规矩，决定这一轮写成什么样 —— 界面本身怎么长，由仓库自己的前端规范管。</p>
      </div>
      <span class="meta-line">{{ style.skills.length ? `本机 ${style.skills.length} 个技能` : '' }}</span>
      <button class="btn" :disabled="style.loading" @click="style.load(true)">
        {{ style.loading ? '读取中…' : '重新读一遍' }}
      </button>
    </header>

    <p v-if="style.error" class="err-line">
      读不到技能目录：{{ style.error }} —— 技能由后端从本机只读目录里列出来（<code>GET /api/skills</code>）。
    </p>

    <!-- 一句结论 -->
    <section class="panel">
      <div class="panel-body verdict">
        <p class="lead-line">
          现在用的是「{{ style.current }}」<template v-if="style.currentSkill"> —— {{ style.currentSkill.description }}</template>
        </p>
        <p class="src">
          来自{{ style.currentSkill?.origin === 'repo' ? '本仓库 .dsh/skills（跟着代码提交）' : '用户目录 ~/.agents/skills（ops/install_skills.sh 装的）' }} ·
          它会写进下一轮的 brief，后端的 brief_checks 会核它有没有被遵守
        </p>
        <p v-if="style.missing" class="caveat">
          这台机器上找不到「{{ style.current }}」这个技能（换机器、或技能没装），下一轮会按仓库默认风格来。
        </p>
      </div>
    </section>

    <!-- 每个技能一行：名字 + 它管什么 + 看规矩 / 用它 -->
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

    <p class="foot-note">
      风格是给人看的一句话，不是暗开关：它写进这次运行的 <code>brief</code>，你随时能在运行记录里看到当时用的是哪一套。
      发布仍然要你点头 —— 风格管不到闸门。
    </p>
  </div>
</template>

<style scoped>
.verdict { display: flex; flex-direction: column; gap: 8px; }
.lead-line { font-family: var(--serif); font-size: 20px; line-height: 1.5; color: var(--text); }
.src { font-size: 12px; color: var(--muted-2); }
.caveat { font-size: 13px; color: #956400; }
.err-line { color: var(--err); font-size: 12.5px; }

.lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.lines li { display: flex; align-items: center; gap: 10px; padding: 10px 2px; border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }
.lines li:last-child { border-bottom: none; }
.lines .dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: #8fb79b; }
.lines li.off .dot { background: #ddd9d2; }
.pname { font-family: var(--mono); font-size: 12.5px; color: var(--text); min-width: 180px; }
.pline { font-size: 13px; color: var(--muted); }
.pnum { font-size: 12px; color: var(--muted-2); white-space: nowrap; }
.detail { margin-top: 12px; }
.src-line { font-family: var(--mono); font-size: 11.5px; color: var(--muted-2); margin-bottom: 6px; }
.skill-body {
  background: var(--surface-2); border: 1px solid var(--hairline); border-radius: 10px;
  padding: 14px 16px; max-height: 420px; overflow: auto;
  font-family: var(--mono); font-size: 12px; line-height: 1.7; color: var(--ink-2);
  white-space: pre-wrap; word-break: break-word;
}
.foot-note { font-size: 12px; color: var(--muted-2); padding: 0 2px 8px; }
.foot-note code { font-family: var(--mono); font-size: 11.5px; background: #f1f0ec; padding: 1px 5px; border-radius: 5px; }

/* 手机：名字一行、说明一行、按钮一行 —— 别让「含 N 份分册」把整行顶出屏幕 */
@media (max-width: 720px) {
  .lines li { gap: 8px; }
  .pname { min-width: 0; }
  .pline { flex: 1 1 100%; order: 3; }              /* 名字一行、说明一行、按钮一行 */
  .pnum { order: 4; }
  .lines li .btn { order: 5; }
  .lead-line { font-size: 16.5px; line-height: 1.6; }
  .src { font-size: 11.5px; }
  .skill-body { max-height: 320px; padding: 12px; font-size: 11.5px; }
}
</style>
