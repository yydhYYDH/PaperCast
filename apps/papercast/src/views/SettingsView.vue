<script setup lang="ts">
import { onMounted } from 'vue'
import { useEnvStore } from '../stores/env'
import ModelApiPanel from '../components/ModelApiPanel.vue'

const env = useEnvStore()
onMounted(() => void env.load(true))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="grow">
        <h1 class="page-title">设置</h1>
        <p class="page-lead">模型与密钥，以及这台机器现在能做什么。日常使用不需要动这里。</p>
      </div>
    </header>

    <ModelApiPanel />

    <section class="panel">
      <header class="panel-head">
        <span class="panel-title">本机状态</span>
        <div class="grow" />
        <span class="panel-sub">{{ env.ready ? '都在就绪' : '还有 ' + env.pending.length + ' 项要处理' }}</span>
      </header>
      <div class="panel-body list">
        <div v-for="r in env.rows" :key="r.id" class="dep">
          <span class="chip" :class="r.state === 'ok' ? 'ok' : 'warn'"><i class="dot" />{{ r.state === 'ok' ? '就绪' : '待处理' }}</span>
          <strong>{{ r.label }}</strong>
          <span class="panel-sub grow">{{ r.detail }}</span>
        </div>
        <p v-if="!env.rows.length" class="panel-sub">{{ env.loading ? '正在检查…' : '暂时读不到本机状态' }}</p>
      </div>
    </section>

    <section class="panel">
      <header class="panel-head"><span class="panel-title">关于</span></header>
      <div class="panel-body stack">
        <p class="panel-sub">
          把一篇论文变成大家看得懂的内容：先读懂论文，再按平台写成文章、做成图文卡片与视频，
          最后在你确认之后才发布。每一步都能停下来看产物、确认了再往下走。
        </p>
        <p class="panel-sub">
          这里的示例数据取自一篇公开论文（arXiv:2510.05096）及其公开项目页，没有引入论文未公开的数值。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.list { display: flex; flex-direction: column; gap: 9px; }
.dep { display: flex; align-items: center; gap: 9px; font-size: 12.5px; }
.stack { display: flex; flex-direction: column; gap: 10px; }
</style>
