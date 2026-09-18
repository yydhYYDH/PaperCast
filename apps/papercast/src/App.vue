<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRunsStore } from './stores/runs'
import { useUiStore } from './stores/ui'
import NavRail from './components/NavRail.vue'
import TopBar from './components/TopBar.vue'
import IntakePanel from './components/IntakePanel.vue'
import RunHistory from './components/RunHistory.vue'
import RunHeader from './components/RunHeader.vue'
import StageStepper from './components/StageStepper.vue'
import PipelineTimeline from './components/PipelineTimeline.vue'
import ArtifactPanel from './components/ArtifactPanel.vue'
import PlatformLoginDialog from './components/PlatformLoginDialog.vue'
import RunsView from './views/RunsView.vue'
import LibraryView from './views/LibraryView.vue'
import PlatformsView from './views/PlatformsView.vue'
import SettingsView from './views/SettingsView.vue'

const store = useRunsStore()
const ui = useUiStore()
const timeline = ref<InstanceType<typeof PipelineTimeline> | null>(null)

const run = computed(() => store.active)

onMounted(() => void store.bootstrap())

function jump(id: string) {
  timeline.value?.scrollTo(id)
}
</script>

<template>
  <div class="shell">
    <NavRail :view="ui.view" :live="!!store.liveRun" @navigate="ui.setView($event)" />

    <div class="main">
      <TopBar />

      <!-- 工作台 -->
      <div v-if="ui.view === 'workbench'" class="workspace">
        <div class="col scroll">
          <IntakePanel />
          <RunHistory />
        </div>

        <div class="col scroll">
          <RunHeader v-if="run" :run="run" @cancel="store.cancel()" />
          <StageStepper v-if="run" :run="run" @jump="jump" />
          <PipelineTimeline v-if="run" ref="timeline" :run="run" />
          <div v-else class="panel empty">还没有运行，先在左侧提交一篇论文。</div>
        </div>

        <div class="col">
          <ArtifactPanel v-if="run" :run="run" />
          <section v-else class="panel empty">选择一条运行以查看产物</section>
        </div>
      </div>

      <RunsView v-else-if="ui.view === 'runs'" />
      <LibraryView v-else-if="ui.view === 'library'" />
      <PlatformsView v-else-if="ui.view === 'platforms'" />
      <SettingsView v-else />
    </div>

    <!-- 扫码登录弹层：任何视图里都能打开（发布页也会调它） -->
    <PlatformLoginDialog />
  </div>
</template>
