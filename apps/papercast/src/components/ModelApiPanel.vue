<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { AppConfig, ConfigItem, LlmTestResult } from '../api/types'

const cfg = ref<AppConfig | null>(null)
const loadError = ref('')
const loading = ref(true)
const saving = ref(false)
const saveError = ref('')
const savedKeys = ref<string[]>([])
const restartNeeded = ref<string[]>([])
const testing = ref(false)
const probe = ref<LlmTestResult | null>(null)
const probeError = ref('')
// 只存用户改过的字段，保存时也只提交这些
const draft = ref<Record<string, string>>({})

/** 默认只露「模型与 API」——用户要填的就是它；渠道地址/解析引擎这些部署配置收起来，需要时展开 */
const PRIMARY_GROUP = '模型与 API'
const showAdvanced = ref(false)

const editableGroups = computed(() => {
  const out: { name: string; items: ConfigItem[] }[] = []
  for (const it of cfg.value ? cfg.value.items : []) {
    if (!it.editable) continue
    let g = out.find((x) => x.name === it.group)
    if (!g) {
      g = { name: it.group, items: [] }
      out.push(g)
    }
    g.items.push(it)
  }
  return out
})


const advancedGroups = computed(() => editableGroups.value.filter((g) => g.name !== PRIMARY_GROUP))
const visibleGroups = computed(() =>
  showAdvanced.value ? editableGroups.value : editableGroups.value.filter((g) => g.name === PRIMARY_GROUP),
)

function shown(it: ConfigItem): string {
  const v = draft.value[it.key]
  if (v !== undefined) return v
  return it.kind === 'secret' ? '' : it.value
}

function onInput(it: ConfigItem, ev: Event) {
  const el = ev.target as HTMLInputElement | HTMLSelectElement
  draft.value = { ...draft.value, [it.key]: el.value }
}

/** 密钥留空 = 不修改；其余项与原值不同才算改动 */
function dirtyItems(): ConfigItem[] {
  const out: ConfigItem[] = []
  const all = cfg.value ? cfg.value.items : []
  for (const it of all) {
    if (!it.editable) continue
    const v = draft.value[it.key]
    if (v === undefined) continue
    if (it.kind === 'secret') {
      if (v.trim() !== '') out.push(it)
      continue
    }
    if (v !== it.value) out.push(it)
  }
  return out
}

const dirtyCount = computed(() => dirtyItems().length)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    cfg.value = await api.getConfig()
    draft.value = {}
    savedKeys.value = []
    restartNeeded.value = []
  } catch (e) {
    loadError.value = String(e)
    cfg.value = null
  } finally {
    loading.value = false
  }
}

async function save() {
  const dirty = dirtyItems()
  if (!dirty.length) return
  saving.value = true
  saveError.value = ''
  try {
    const values: Record<string, string> = {}
    for (const it of dirty) values[it.key] = draft.value[it.key] === undefined ? '' : draft.value[it.key]!
    const res = await api.patchConfig(values)
    const keys = res.changed
    const restart = res.restartNeeded ? res.restartNeeded : []
    await load()
    savedKeys.value = keys
    restartNeeded.value = restart
  } catch (e) {
    saveError.value = String(e)
  } finally {
    saving.value = false
  }
}

async function runProbe() {
  testing.value = true
  probe.value = null
  probeError.value = ''
  try {
    probe.value = await api.testLlm()
  } catch (e) {
    probeError.value = String(e)
  } finally {
    testing.value = false
  }
}

function sourceLabel(s: string): string {
  if (s === '.env') return '来自本机配置'
  if (s === 'environment') return '来自运行环境'
  if (s === 'dsh-credential') return '来自 DSH 凭证'
  if (s === 'unset') return '未配置'
  if (s === 'mock') return '示意值'
  return '默认值'
}

function sourceTone(s: string): string {
  if (s === 'environment' || s === '.env') return 'ok'
  if (s === 'unset') return 'warn'
  return ''
}

onMounted(load)
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">模型与 API</span>
      <span class="panel-sub">改完立即生效，只保存在这台机器上（密钥不回显明文）</span>
      <div class="grow" />
      <span v-if="dirtyCount" class="chip warn"><i class="dot" />{{ dirtyCount }} 项待保存</span>
      <button class="btn sm" :disabled="saving || !dirtyCount" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      <button class="btn sm" :disabled="testing" @click="runProbe">{{ testing ? '探测中…' : '测试连接' }}</button>
      <button class="btn sm" @click="load">重新载入</button>
    </header>

    <div class="panel-body stack">
      <p v-if="loading" class="panel-sub">正在读取配置…</p>
      <p v-else-if="loadError" class="err-line">
        读取失败：{{ loadError }} —— 演示模式下没有可改的配置，连上本机后端后即可修改。
      </p>

      <template v-else-if="cfg">
        <div class="row spread">
          <span class="label">保存位置</span>
          <span class="panel-sub" :title="cfg.envFile">{{ cfg.envFileExists ? '本机配置文件（仅本机可读）' : '还没建过；第一次保存时在本机生成' }}</span>
        </div>

        <div v-if="probe" class="probe" :class="probe.ok ? 'ok' : 'bad'">
          <template v-if="probe.ok">连接正常：{{ probe.model }} 回话「{{ probe.reply }}」，耗时 {{ probe.ms }} ms（{{ probe.baseUrl }}）</template>
          <template v-else>探测失败：{{ probe.message }}</template>
        </div>
        <p v-if="probeError" class="err-line">探针没发出去：{{ probeError }}</p>
        <p v-if="savedKeys.length" class="ok-line">
          已保存：{{ savedKeys.join('、') }}{{ restartNeeded.length ? '；其中 ' + restartNeeded.join('、') + ' 需重启后端才生效' : '（已立即生效）' }}
        </p>
        <p v-if="saveError" class="err-line">保存失败：{{ saveError }}</p>

        <div v-for="g in visibleGroups" :key="g.name" class="group">
          <div class="group-title">{{ g.name }}</div>
          <div v-for="it in g.items" :key="it.key" class="cfg-row">
            <div class="cfg-main">
              <div class="cfg-label">
                <span :title="'配置项：' + it.key">{{ it.label }}</span>
                <span class="chip" :class="sourceTone(it.source)"><i class="dot" />{{ sourceLabel(it.source) }}</span>
              </div>
              <div class="panel-sub">{{ it.desc }}</div>
            </div>
            <div class="cfg-input">
              <select v-if="it.kind === 'bool'" :value="shown(it)" @change="onInput(it, $event)">
                <option value="on">on</option>
                <option value="off">off</option>
              </select>
              <input
                v-else-if="it.kind === 'secret'"
                type="password"
                autocomplete="off"
                :value="shown(it)"
                :placeholder="it.value ? '留空 = 不修改（当前 ' + it.value + '）' : '填入密钥'"
                @input="onInput(it, $event)"
              />
              <input v-else-if="it.kind === 'int'" type="number" :value="shown(it)" @input="onInput(it, $event)" />
              <input v-else type="text" :value="shown(it)" @input="onInput(it, $event)" />
            </div>
          </div>
        </div>

        <button
          v-if="advancedGroups.length"
          class="btn sm ghost self-start"
          @click="showAdvanced = !showAdvanced"
        >
          {{ showAdvanced ? '收起部署配置' : '显示部署配置（渠道地址、解析引擎等）' }}
        </button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.group { display: flex; flex-direction: column; gap: 2px; }
.self-start { align-self: flex-start; }
.group-title {
  font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted); padding: 12px 0 6px; border-bottom: 1px solid var(--line-soft);
}
.cfg-row {
  display: grid; grid-template-columns: 1fr 260px; gap: 14px;
  align-items: center; padding: 10px 0; border-bottom: 1px solid var(--line-soft);
}
/* 手机：说明一行、输入框一行（固定 260px 的输入框在 390px 的屏上会顶出去） */
@media (max-width: 720px) {
  .cfg-row { grid-template-columns: minmax(0, 1fr); gap: 8px; align-items: stretch; }
  .cfg-input input, .cfg-input select { width: 100%; }
}
.cfg-label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-1); }
.key { color: var(--muted); font-size: 11px; }
.cfg-input input, .cfg-input select {
  width: 100%; padding: 7px 9px; border-radius: 6px;
  border: 1px solid var(--line); background: var(--bg-2); color: var(--text-1);
}
.cfg-input input:focus, .cfg-input select:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
.probe { padding: 9px 11px; border-radius: 6px; font-size: 12.5px; }
.probe.ok { background: var(--bg-2); border-left: 3px solid var(--ok, #3fb950); }
.probe.bad { background: var(--bg-2); border-left: 3px solid var(--warn, #d29922); }
.ok-line { color: var(--ok, #3fb950); font-size: 12.5px; }
.ro-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 20px; padding-top: 8px; }
.ro-item { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
</style>
