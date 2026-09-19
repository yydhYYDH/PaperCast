<script setup lang="ts">
/**
 * 发布这件作品：**一件作品 → 一个渠道 → 一次人工确认**。
 *
 * 从「作品库」的作品详情里打开（后端 GET /api/runs/:id/drafts 拿逐渠道待发草稿）。
 * 这一条路径不需要运行停在发布闸门上 —— 运行跑完、后端重启过，作品照样能发。
 *
 * 界面上只做三件事，其余交给后端：
 *   1. 说清**现在会投哪一份文案**（后端按渠道拣好的，前端不挑变体）；
 *   2. 允许改标题 / 正文 / 标签（改完后端会再按平台规则判一次）；
 *   3. 给动作：**仅存草稿**（无副作用）、**确认发布**（按渠道默认形态，不可逆，走 ui.askConfirm），
 *      以及**发布视频**（run 里另有成片时才出现）。
 *
 * 形态（图文 / 视频）由后端口径决定：默认那个是渠道说了算（`defaultMedia`，小红书图文、
 * B 站成片），本组件只负责**把这次发哪个形态写在按钮上方**，不自己判断能发什么。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl } from '../api'
import { usePlatformsStore } from '../stores/platforms'
import { usePublishStore } from '../stores/publish'
import { useUiStore } from '../stores/ui'
import { PLATFORM_STATE } from '../utils'

const pub = usePublishStore()
const platforms = usePlatformsStore()
const ui = useUiStore()

/** 变体平台 → 人话。只在界面里用，不去动 data/library.ts（那边的轴是「作品归属平台」）。 */
const VAR_PLATFORM: Record<string, string> = {
  xhs: '小红书', zhihu: '知乎', bilibili: 'B 站', en: '英文传播',
}

const draft = computed(() => pub.draft)
const text = computed(() => pub.text)

/** 这一份文案是不是这个渠道自己的（不是借的）—— 借来的必须说出来 */
const sourceNote = computed(() => {
  const d = draft.value
  if (!d) return ''
  const own = d.variantPlatform || ''
  const mine = d.variantPlatform === d.channelId || (d.channelId === 'xiaohongshu' && own === 'xhs')
  const from = own ? VAR_PLATFORM[own] ?? own : ''
  if (!d.variant) return ''
  if (mine) return `用的是这次运行里${VAR_PLATFORM[d.channelId] ?? d.name}自己那份稿子`
  if (from) return `借用了${from}那份稿子（${d.name}还没有自己的版本），发布前最好改一版`
  return `文案来自 ${d.variant}`
})

/** 登录态：用「平台账号」页那份真实探测结果（这里只负责把它变成下一步动作） */
const loginKind = computed(() => platforms.channel(draft.value?.channelId ?? '')?.login ?? 'none')

async function doLogin() {
  const d = draft.value
  if (!d) return
  if (loginKind.value === 'browser') await platforms.browserLogin(d.channelId)
  else if (loginKind.value === 'qrcode') await platforms.openLogin(d.channelId)
  else ui.toast(`${d.name}需要在本机配置凭证，去「平台账号」页看说明`, 'warn')
  await pub.load()
}

/** 只显示前 6 张配图：发布面板不是图库，真实张数写在旁边 */
const shots = computed(() => (draft.value?.images ?? []).slice(0, 6))
const shotTotal = computed(() => draft.value?.images?.length ?? 0)

/** 主按钮发的形态：渠道说了算（小红书图文、B 站成片），界面不自己猜 */
const defaultIsVideo = computed(() => draft.value?.defaultMedia === 'video')
const formWord = computed(() => (defaultIsVideo.value ? '成片' : '图文'))
/** 成片可发：素材里有，而且这个渠道本来就能发视频（X 那种只出素材包的不给这个动作） */
const canPostVideo = computed(() => {
  const d = draft.value
  return Boolean(d?.video) && (d?.capabilities ?? []).includes('video') && !defaultIsVideo.value
})

const statusChip = computed(() => {
  const d = draft.value
  if (!d) return { label: '', cls: '' }
  if (!d.hasDraft) return { label: '没有可发的稿子', cls: 'err' }
  if (!d.suitable) return { label: '素材不合适', cls: 'warn' }
  if (!d.ready) return PLATFORM_STATE[d.state] ?? { label: '未就绪', cls: 'warn' }
  return { label: '可以发布', cls: 'ok' }
})

/** 回执卡：把后端结果原样摆出来（成功给链接、失败给原因、草稿给文件数） */
const result = computed(() => pub.result)
const resultTitle = computed(() => {
  const r = result.value
  if (!r) return ''
  return r.status === 'published' ? '已发布'
    : r.status === 'draft' ? '只存了草稿（没有投递）'
    : r.status === 'blocked' ? '没有投出去'
    : '投递失败'
})

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && pub.open && !pub.busy) pub.close()
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  if (!platforms.channels.length) void platforms.refresh(false)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

/** 打开时把焦点放进来，键盘用户不用先 Tab 一圈 */
const titleEl = ref<HTMLInputElement | null>(null)
watch(() => [pub.open, pub.channelId], () => {
  if (pub.open) window.setTimeout(() => titleEl.value?.focus(), 60)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="pub.open" class="mask" @click.self="!pub.busy && pub.close()">
      <div class="pub" role="dialog" aria-modal="true" aria-label="发布这件作品">
        <header class="pub-head">
          <div class="grow">
            <h2 class="pub-title">发布这件作品</h2>
            <p class="pub-sub">
              来自《{{ pub.runTitle }}》 · 每个渠道各投自己那份文案，发出之前都要你点头
            </p>
          </div>
          <span v-if="statusChip.label" class="chip" :class="statusChip.cls"><i class="dot" />{{ statusChip.label }}</span>
          <button class="btn ghost sm" :disabled="pub.busy === 'publish'" @click="pub.close">关闭 · Esc</button>
        </header>

        <div class="pub-body">
          <!-- 读不到就说读不到，并给出下一步 -->
          <!-- 这一步要真去问渠道能不能收（后端顺手探一次登录态）：知乎那边会新起一个浏览器，实测 6~9 秒，
               渠道状态本身有 20 秒缓存；说清在等什么，别让人以为界面卡死了 -->
          <div v-if="pub.loading" class="pub-note">
            正在看这次运行产出了什么、各平台现在能不能收…（要真去问一次渠道状态：知乎那边得新起一个浏览器，
            实测 6~9 秒；这状态缓存 20 秒，紧接着再点会快很多）
          </div>

          <div v-else-if="pub.error" class="pub-note err">
            <p>读不到待发内容：{{ pub.error }}</p>
            <div class="row">
              <button class="btn sm" @click="pub.load">重试</button>
              <button class="btn sm" @click="ui.setView('platforms'); pub.close()">去「平台账号」看看</button>
            </div>
          </div>

          <template v-else-if="draft">
            <!-- 左：渠道 -->
            <nav class="pub-rail">
              <p class="label">发到哪儿</p>
              <button
                v-for="c in pub.data?.channels ?? []"
                :key="c.channelId"
                class="ch"
                :class="{ on: pub.channelId === c.channelId }"
                @click="pub.select(c.channelId)"
              >
                <span class="ch-name">{{ c.name }}</span>
                <span class="ch-state" :class="{ ok: c.ready && c.suitable, warn: !c.suitable || !c.ready }">
                  {{ !c.hasDraft ? '没有稿子' : !c.suitable ? '素材不合适' : c.ready ? (c.account ? '已登录 ' + c.account : '已登录') : '未登录' }}
                </span>
              </button>

              <button class="btn ghost sm reload" :disabled="pub.loading" @click="pub.load">重新检查</button>
            </nav>

            <!-- 右：这一份稿子 -->
            <section class="pub-main">
              <div class="row wrap gap head-row">
                <span class="chip tiny"><i class="dot" />{{ draft.name }}</span>
                <span v-if="draft.account" class="chip tiny accent">账号 {{ draft.account }}</span>
                <span v-if="sourceNote" class="panel-sub">{{ sourceNote }}</span>
              </div>

              <p v-if="pub.data?.previous" class="prev-line">
                这条运行已经投过一次：{{ pub.data.previous.bvid || pub.data.previous.url || '未知稿件' }}。
                再发一次会重复投递，平台侧不会自动去重。
              </p>
              <p v-for="w in pub.data?.warnings ?? []" :key="w" class="prev-line">{{ w }}</p>

              <label class="lbl" for="pub-title">标题</label>
              <input
                id="pub-title"
                ref="titleEl"
                class="field"
                :value="text.title"
                :disabled="!draft.hasDraft || pub.busy !== ''"
                @input="pub.edit('title', ($event.target as HTMLInputElement).value)"
              />

              <label class="lbl" for="pub-body">正文</label>
              <textarea
                id="pub-body"
                class="field body"
                :value="text.content"
                :disabled="!draft.hasDraft || pub.busy !== ''"
                @input="pub.edit('content', ($event.target as HTMLTextAreaElement).value)"
              />
              <p class="panel-sub">{{ text.content.length }} 字 · {{ draft.name === 'B 站' ? '投稿简介用这段' : '发布时用这段' }}</p>

              <label class="lbl" for="pub-tags">标签</label>
              <input
                id="pub-tags"
                class="field"
                :value="text.tags"
                :disabled="!draft.hasDraft || pub.busy !== ''"
                @input="pub.edit('tags', ($event.target as HTMLInputElement).value)"
              />

              <div v-if="shots.length" class="media">
                <div class="row spread">
                  <span class="lbl">配图</span>
                  <span class="panel-sub">
                    {{ shotTotal }} 张{{ defaultIsVideo ? '，发成片时用不上' : '，随图文一起投' }}
                  </span>
                </div>
                <div class="shots">
                  <a v-for="m in shots" :key="m.path" :href="assetUrl(m.url)" target="_blank" rel="noreferrer" :title="'看原图 ' + m.name">
                    <img :src="assetUrl(m.url)" :alt="m.name" loading="lazy" />
                  </a>
                </div>
              </div>
              <div v-if="draft.video" class="media">
                <span class="lbl">成片</span>
                <span class="panel-sub">
                  {{ draft.video.name }}{{ defaultIsVideo ? ' 会投上去' : '，点下面「发布视频」才发它' }}
                </span>
              </div>

              <!-- 闸门：能投就给动作，不能投就说清为什么与下一步 -->
              <div class="gate" :class="pub.canPublish ? 'ok' : 'blocked'">
                <template v-if="pub.canPublish">
                  <p class="gate-line">
                    <!-- 形态必须说在按钮正上方：小红书里图文笔记和视频笔记是两种笔记，发错撤不回来 -->
                    这次发的是<strong>{{ formWord }}</strong>。发出后不可撤销：{{ draft.name }}上会立刻公开可见。
                    <template v-if="draft.reason">素材检查：{{ draft.reason }}。</template>
                  </p>
                  <div class="row wrap gap">
                    <button class="btn primary" :disabled="pub.busy !== ''" @click="pub.deliver()">
                      {{ pub.busy === 'publish' ? '正在投递…' : '确认发布' }}
                    </button>
                    <button v-if="canPostVideo" class="btn" :disabled="pub.busy !== ''" @click="pub.deliver('video')">
                      {{ pub.busy === 'video' ? '正在投递…' : '发布视频' }}
                    </button>
                    <button class="btn" :disabled="pub.busy !== ''" @click="pub.saveDraft">
                      {{ pub.busy === 'draft' ? '正在存…' : '仅存草稿' }}
                    </button>
                    <button class="btn ghost" :disabled="pub.busy !== '' || !Object.keys(pub.edits[draft.channelId] ?? {}).length" @click="pub.resetEdit">
                      撤销改动
                    </button>
                  </div>

                  <!-- 投递要等一阵子（渠道那边在开浏览器、填稿、逐张传图），这里如实报「已经等了多久」，
                       并说清在等什么、别重复点 —— 只数秒，不编造进度条（进度条会骗人）。 -->
                  <div v-if="pub.busy === 'publish' || pub.busy === 'video'" class="waiting">
                    <p class="wait-line">
                      <span class="wait-dot" aria-hidden="true" />
                      正在{{ pub.busy === 'video' ? '投递成片' : '投递' }}…已等
                      <b class="mono">{{ pub.elapsed }}</b> 秒
                    </p>
                    <p class="wait-hint">
                      那边现在在做：打开浏览器 → 填标题正文 → 逐张传图 → 点发布 → 回来核验这一篇是不是真的发出去了。
                      图文一般要一分钟上下（本机实测知乎一篇：光填稿+传 8 张图就 61 秒）。别重复点 ——
                      关掉这个窗口不会取消，只是你看不到结果。
                    </p>
                  </div>
                </template>
                <template v-else>
                  <p class="gate-line">
                    <strong>{{ draft.name }}这一轮投不出去：</strong>{{ pub.blockedReason }}
                  </p>
                  <div class="row wrap gap">
                    <button v-if="!draft.ready && draft.hasDraft" class="btn sm" @click="doLogin">
                      {{ loginKind === 'browser' ? '打开浏览器登录' : '扫码登录' }}
                    </button>
                    <button class="btn sm" :disabled="pub.busy !== ''" @click="pub.saveDraft">仅存草稿</button>
                    <button class="btn ghost sm" @click="pub.close">换个渠道</button>
                  </div>
                </template>
              </div>

              <!-- 回执：成功给链接、失败给原因、草稿给文件数 -->
              <div v-if="result" class="receipt" :class="result.status">
                <div class="row spread">
                  <strong class="r-title">{{ resultTitle }}</strong>
                  <a v-if="result.receiptUrl" class="link" :href="assetUrl(result.receiptUrl)" target="_blank" rel="noreferrer">看回执文件</a>
                </div>
                <p v-if="result.url" class="panel-sub">
                  链接：<a class="link" :href="result.url" target="_blank" rel="noreferrer">{{ result.url }}</a>
                </p>
                <p v-else-if="result.remoteId" class="panel-sub">平台侧编号：{{ result.remoteId }}</p>
                <p v-if="result.error?.message" class="panel-sub">{{ result.error.message }}</p>
                <!-- 「存成草稿」很容易被读成「发出去了」：后端那句 note 必须原样带出来 -->
                <p v-if="result.note" class="panel-sub">{{ result.note }}</p>
                <p v-if="result.files?.length" class="panel-sub">
                  素材包 {{ result.files.length }} 个文件已落在本机：{{ result.exportDir }}
                </p>
                <p v-if="result.exportError" class="panel-sub">素材包有个别文件没落成：{{ result.exportError }}</p>
              </div>
            </section>
          </template>

          <div v-else class="pub-note">这次运行还没有可以发布的稿子：先把「写作」阶段跑完。</div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.pub {
  width: min(960px, 94vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.pub-head {
  display: flex; align-items: center; gap: 12px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--hairline);
}
.pub-head .grow { flex: 1; min-width: 0; }
.pub-title { font-family: var(--serif); font-size: 19px; letter-spacing: -0.01em; }
.pub-sub { font-size: 12.5px; color: var(--ink-3); margin-top: 3px; }

.pub-body {
  flex: 1; min-height: 0;
  display: grid; grid-template-columns: 190px 1fr;
}
.pub-note { padding: 34px 24px; color: var(--ink-3); font-size: 13.5px; line-height: 1.8; grid-column: 1 / -1; display: flex; flex-direction: column; gap: 10px; }
.pub-note.err { color: var(--tone-red-fg); }

.pub-rail {
  border-right: 1px solid var(--hairline);
  padding: 16px 12px;
  display: flex; flex-direction: column; gap: 8px;
  background: var(--surface-2);
  overflow-y: auto;
}
.pub-rail .label { padding: 0 4px 4px; }
.ch {
  text-align: left;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  display: flex; flex-direction: column; gap: 3px;
  color: var(--ink-2);
  transition: 0.15s;
}
.ch:hover { background: var(--surface); border-color: var(--hairline); }
.ch.on { background: var(--surface); border-color: var(--ink-4); }
.ch-name { font-size: 13.5px; font-weight: 500; }
.ch-state { font-size: 11.5px; color: var(--ink-3); }
.ch-state.ok { color: var(--tone-green-fg); }
.ch-state.warn { color: var(--tone-amber-fg); }
.reload { margin-top: auto; }

.pub-main { padding: 18px 22px 22px; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; }
.head-row { gap: 8px; }
.lbl { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-4); font-weight: 600; margin-top: 6px; }
.field.body { min-height: 170px; resize: vertical; line-height: 1.75; font-family: inherit; }
.prev-line {
  font-size: 12.5px; line-height: 1.7; color: var(--tone-amber-fg);
  background: var(--tone-amber-bg); border-radius: var(--radius-sm); padding: 8px 11px;
}

.media { display: flex; flex-direction: column; gap: 7px; margin-top: 8px; }
.shots { display: flex; gap: 8px; flex-wrap: wrap; }
.shots a { display: block; border: 1px solid var(--hairline); border-radius: var(--radius-sm); overflow: hidden; background: var(--surface-2); }
.shots img { display: block; width: 64px; height: 84px; object-fit: cover; }

.gate {
  margin-top: 14px; padding: 13px 15px;
  border: 1px solid var(--hairline); border-radius: var(--radius);
  display: flex; flex-direction: column; gap: 10px;
  background: var(--surface-2);
}
.gate.ok { border-color: #dfe3dc; background: var(--tone-green-bg); }
.gate.blocked { border-color: #efe2c4; background: var(--tone-amber-bg); }
.gate-line { font-size: 13px; line-height: 1.75; color: var(--ink-2); }

/* 投递等待：只报「已等多久」与在做哪几步，不做进度条（进度条只能靠猜） */
.waiting {
  margin-top: 2px; padding-top: 10px; border-top: 1px dashed var(--hairline);
  display: flex; flex-direction: column; gap: 5px;
}
.wait-line { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink); }
.wait-dot {
  width: 7px; height: 7px; border-radius: 50%; background: var(--tone-green-ink, #346538);
  animation: wait-pulse 1.4s ease-in-out infinite;
}
@keyframes wait-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }
.wait-hint { font-size: 12.5px; line-height: 1.7; color: var(--small-ink, #6b6963); }
@media (prefers-reduced-motion: reduce) { .wait-dot { animation: none; } }
@media (max-width: 720px) { .waiting { gap: 6px; } .wait-hint { font-size: 13px; } }

.receipt {
  margin-top: 12px; padding: 13px 15px;
  border: 1px solid var(--hairline); border-radius: var(--radius);
  display: flex; flex-direction: column; gap: 5px;
  background: var(--surface);
}
.receipt.published { border-color: #dfe3dc; }
.receipt.failed, .receipt.blocked { border-color: #f0d7d8; }
.r-title { font-size: 13px; }
.link { color: var(--accent); text-decoration: underline; font-size: 12.5px; word-break: break-all; }

@media (max-width: 900px) {
  .pub-body { grid-template-columns: 1fr; }
  .pub-rail { border-right: 0; border-bottom: 1px solid var(--hairline); flex-direction: row; flex-wrap: wrap; align-items: center; }
  .pub-rail .label { width: 100%; }
  .reload { margin-top: 0; }
}
</style>
