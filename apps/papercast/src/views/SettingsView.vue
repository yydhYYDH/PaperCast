<script setup lang="ts">
import { ENGINE_ROWS, ENV_DEPS } from '../data/env'
import { useRunsStore } from '../stores/runs'
import ModelApiPanel from '../components/ModelApiPanel.vue'

const store = useRunsStore()
</script>

<template>
  <div class="page">
    <ModelApiPanel />

    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">六段流水线与复用的实现</span>
        <div class="grow" />
        <span class="panel-sub">来自本次 GitHub 调研（11 个仓库已下到 repos/）</span>
      </header>
      <table class="tbl">
        <thead><tr><th style="width: 14%">阶段</th><th style="width: 20%">本项目的引擎</th><th style="width: 36%">复用的开源实现</th><th>设计取舍</th></tr></thead>
        <tbody>
          <tr v-for="r in ENGINE_ROWS" :key="r.stage">
            <td><strong>{{ r.stage }}</strong></td>
            <td class="mono">{{ r.engine }}</td>
            <td class="mono reuse">{{ r.reusedFrom }}</td>
            <td class="muted">{{ r.note }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div class="two">
      <section class="panel">
        <header class="panel-head"><span class="panel-title">环境依赖</span></header>
        <div class="panel-body list">
          <div v-for="d in ENV_DEPS" :key="d.id" class="dep">
            <span class="chip" :class="d.state === 'ok' ? 'ok' : d.state === 'warn' ? 'warn' : ''"><i class="dot" />{{ d.state === 'ok' ? '就绪' : d.state === 'warn' ? '降级' : '缺失' }}</span>
            <strong>{{ d.label }}</strong>
            <span class="panel-sub grow">{{ d.detail }}</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <header class="panel-head"><span class="panel-title">前后端契约</span></header>
        <div class="panel-body stack">
          <div class="row spread">
            <span class="label">当前适配器</span>
            <span class="chip mono">{{ store.apiLabel }}</span>
          </div>
          <p class="panel-sub">
            前端只依赖 <code>PipelineApi</code> 接口（<code>src/api/types.ts</code>）。默认走内置模拟器；
            启动后端后设置 <code>VITE_API_BASE=http://127.0.0.1:8000</code> 即自动切到 <code>HttpPipelineApi</code>，
            组件与状态管理无需改动。
          </p>
          <div class="code">
            <div>POST /api/runs                        <span class="muted-2"># 提交论文，返回 run</span></div>
            <div>GET  /api/runs/:id                    <span class="muted-2"># 轮询进度 / 日志 / 产物</span></div>
            <div>GET  /api/runs/:id/events             <span class="muted-2"># SSE，可选</span></div>
            <div>POST /api/runs/:id/stages/:sid/gate   <span class="muted-2"># 人工闸门放行</span></div>
            <div>POST /api/runs/:id/cancel             <span class="muted-2"># 中止</span></div>
          </div>
        </div>
      </section>
    </div>

    <section class="panel">
      <header class="panel-head"><span class="panel-title">演示数据来源</span></header>
      <div class="panel-body stack">
        <p class="panel-sub">
          默认示例运行的主题论文是 <span class="mono">arXiv:2510.05096（Paper2Video / PaperTalker）</span>，
          示例文章、旁白脚本、理解层 digest 均由本地 README、arXiv 摘要页与项目主页三处一致信息生成，未引入论文未公开的数值。
          示例视频来自 showlab/Paper2Video 的公开产物。
        </p>
        <p class="panel-sub">
          真实流水线里每个阶段都要跑分钟级的外部工具（MinerU、xelatex、TTS、浏览器渲染、平台发布），
          所以这个面板把「人工闸门」和「阶段产物」做成一等公民：任何一步都能停下来看、确认、再往下走。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th { text-align: left; padding: 9px 12px; color: var(--muted); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; border-bottom: 1px solid var(--line-soft); }
.tbl td { padding: 10px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: top; color: var(--text-2); }
.reuse { color: var(--muted); font-size: 11.5px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.list { display: flex; flex-direction: column; gap: 9px; }
.dep { display: flex; align-items: center; gap: 9px; font-size: 12.5px; }
.stack { display: flex; flex-direction: column; gap: 10px; }
.code { font-family: var(--mono); font-size: 11.5px; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: 9px; padding: 11px 12px; display: flex; flex-direction: column; gap: 5px; color: var(--text-2); }
code { font-family: var(--mono); font-size: 11.5px; background: var(--panel-3); padding: 1px 5px; border-radius: 5px; color: #cfe2ff; }
</style>
