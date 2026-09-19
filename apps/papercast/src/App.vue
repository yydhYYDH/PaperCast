<script setup lang="ts">
import { onMounted } from 'vue'
import { useRunsStore } from './stores/runs'
import { useUiStore } from './stores/ui'
import NavRail from './components/NavRail.vue'
import TopBar from './components/TopBar.vue'
import PlatformLoginDialog from './components/PlatformLoginDialog.vue'
import PublishSheet from './components/PublishSheet.vue'
import AppDialog from './components/AppDialog.vue'
import AppToasts from './components/AppToasts.vue'
import WorkbenchView from './views/WorkbenchView.vue'
import RunsView from './views/RunsView.vue'
import LibraryView from './views/LibraryView.vue'
import PlatformsView from './views/PlatformsView.vue'
import OpsView from './views/OpsView.vue'
import SettingsView from './views/SettingsView.vue'

const store = useRunsStore()
const ui = useUiStore()
void store
onMounted(() => void store.bootstrap())
</script>

<template>
  <div class="shell">
    <NavRail :view="ui.view" :live="!!store.liveRun" @navigate="ui.setView($event)" />

    <div class="main">
      <TopBar />

      <!-- 工作台：一个对话入口（左侧对话，右侧谁在干活） -->
      <WorkbenchView v-if="ui.view === 'workbench'" />

      <RunsView v-else-if="ui.view === 'runs'" />
      <LibraryView v-else-if="ui.view === 'library'" />
      <PlatformsView v-else-if="ui.view === 'platforms'" />
      <OpsView v-else-if="ui.view === 'ops'" />
      <SettingsView v-else />
    </div>

    <!-- 扫码登录弹层：任何视图里都能打开（发布页也会调它） -->
    <PlatformLoginDialog />
    <!-- 发布这件作品（作品库详情里点开）：一件作品 → 一个渠道 → 一次人工确认 -->
    <PublishSheet />
    <!-- 统一的应用内确认框与回执气泡（替代 window.confirm / 静默失败） -->
    <AppDialog />
    <AppToasts />
  </div>
</template>


