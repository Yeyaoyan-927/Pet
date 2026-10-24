<!--
  宠物实景（宠主）：可观看的在住宠物列表 + 播放器（浮水印 + 凭证倒计时）。
  **只做「打开摄像头看一眼」**：不抓拍、不留存相册，看完点「结束观看」即可释放名额。
  数据来源：GET /camera/live、POST /camera/sessions。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">宠物实景</h2>
        <p class="pp-page-desc">只看得到自己正在寄养的毛孩子：凭证 5 分钟有效、单订单最多 2 路、观看全程留痕。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="privacy"
      type="info"
      :closable="false"
      show-icon
      title="隐私说明"
      :description="privacy"
      class="pp-mb-4"
    />

    <PawLoading v-if="loading" variant="paw" text="正在检查可观看的毛孩子…" />
    <EmptyState
      v-else-if="!items.length"
      illustration="dog"
      title="暂时没有可观看的毛孩子"
      description="寄养入住后就能在这里看到它的实时画面；离店后自动失效。"
    >
      <el-button type="primary" @click="router.push('/user/boarding')">查看我的寄养</el-button>
    </EmptyState>

    <div v-else class="pp-grid">
      <div v-for="item in items" :key="item.order_id" class="live-card pp-card">
        <div class="live-card__head">
          <span class="live-card__name">{{ item.pet_name }}</span>
          <el-tag size="small" :type="item.can_watch ? 'success' : 'info'" effect="light">
            {{ item.can_watch ? '可观看' : '暂不可看' }}
          </el-tag>
        </div>
        <div class="live-card__meta">{{ item.order_no }} · 预计 {{ item.check_out_date }} 接回</div>
        <p v-if="!item.can_watch" class="live-card__reason">{{ item.reason }}</p>
        <el-button
          v-else
          type="primary"
          :icon="VideoCamera"
          class="live-card__btn"
          @click="watch(item)"
        >查看实时画面</el-button>
      </div>
    </div>

    <!-- 播放器 -->
    <el-dialog v-model="playerVisible" :title="playerTitle" width="720px" @closed="onDialogClosed">
      <!-- 失败态优先：申请凭证失败时 session 为空，不能只剩一句「正在申请观看凭证…」 -->
      <div v-if="playError" class="player__empty">
        <EmptyState
          illustration="dog"
          :title="playError"
          description="请确认已在门店端开启推流，或稍后重试。"
          :size="72"
        >
          <el-button type="primary" @click="retry">重新获取画面</el-button>
        </EmptyState>
      </div>
      <div v-else-if="session" class="player">
        <img
          v-if="frameUrl"
          :src="frameUrl"
          class="player__video"
          alt="实时画面"
        />
        <div v-else class="player__placeholder">
          <PawLoading variant="bubble" text="正在连接门店摄像头…" />
        </div>
        <div v-if="frameUrl && frameMode === 'live'" class="player__watermark">{{ session.watermark }}</div>
        <div class="player__bar">
          <span class="player__hint">
            <template v-if="frameMode === 'demo'">门店端暂未开启推流，下面是演示画面</template>
            <template v-else-if="frameMode === 'live'">实时画面 · 凭证剩余 {{ countdown }} 秒</template>
            <template v-else>正在等待门店端推流…（凭证剩余 {{ countdown }} 秒）</template>
            · {{ session.fps }} fps · {{ session.resolution }}
          </span>
          <div class="player__ops">
            <el-tag v-if="frameMode === 'demo'" size="small" type="warning" effect="light">演示画面</el-tag>
            <el-button size="small" type="danger" plain @click="closePlayer">结束观看</el-button>
          </div>
        </div>
      </div>
      <div v-else class="player__placeholder">
        <PawLoading variant="bubble" text="正在申请观看凭证…" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, VideoCamera } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { cameraApi, cameraFrameUrl } from '@/api/camera'
import type { CameraLiveItem, CameraSessionOut } from '@/types'

// ---- 页面结构（阅读顺序）----
// 1) 状态：items（可观看的在住宠物）、session（凭证 + 过期倒计时）
// 2) 播放：先申请短期凭证，再按 800ms 轮询单帧接口；真实帧一到自动从演示画面切到实时画面，
//    「演示 / 实时」由后端每帧的 X-Frame-Mode 决定，不再在签发凭证时一次性判定
//    （V8.4.2 实测：宠主先开页面、店员后开推流时，旧写法会永远停在演示画面）
// 3) 倒计时：凭证默认 5 分钟，到点自动停止播放并提示重新获取（避免看到别人的画面）
// 4) 生命周期：onUnmounted 必须 endSession + 清掉轮询，否则名额要等凭证自然过期才释放

const router = useRouter()
const route = useRoute()
const items = ref<CameraLiveItem[]>([])
const loading = ref(true)
const privacy = ref('')

const playerVisible = ref(false)
const playerTitle = ref('实时画面')
const current = ref<CameraLiveItem | null>(null)
const session = ref<CameraSessionOut | null>(null)
const playError = ref('')
const countdown = ref(0)
/** 当前帧地址（objectURL）与模式：live=门店推流中 / demo=演示画面 / none=等待推流 */
const frameUrl = ref('')
const frameMode = ref<'live' | 'demo' | 'none'>('none')
let timer: number | null = null
let frameTimer: number | null = null
/** 轮询代次：停止/重开时自增，让在途的旧循环自然退出 */
let loopToken = 0

async function load() {
  loading.value = true
  try {
    const [live, meta] = await Promise.all([cameraApi.live(), cameraApi.meta()])
    items.value = live
    privacy.value = meta.privacy
  } finally {
    loading.value = false
  }
}

/**
 * 打开播放器：**先把弹窗打开**再申请凭证。
 * 旧写法先 await 凭证、成功后才弹窗，一但接口报错（不在观看时段 / 设备离线 / 并发满）
 * 页面上什么都不会发生，用户看到的就是「点了观看没反应、没页面」。
 */
async function watch(item: CameraLiveItem) {
  current.value = item
  playerTitle.value = `${item.pet_name} · ${item.order_no}`
  session.value = null
  playError.value = ''
  clearFrame()
  playerVisible.value = true
  try {
    const data = await cameraApi.openSession(item.order_id)
    // 申请凭证期间用户可能已经关掉弹窗：立刻释放名额，别留一个「幽灵会话」占并发
    if (!playerVisible.value) {
      await cameraApi.endSession(data.session_id).catch(() => undefined)
      return
    }
    session.value = data
    startCountdown(data.expires_in)
    startFrameLoop()
  } catch (err: any) {
    playError.value = err?.response?.data?.message || err?.message || '暂时无法获取画面'
  }
}

function clearFrame() {
  if (frameUrl.value) URL.revokeObjectURL(frameUrl.value)
  frameUrl.value = ''
  frameMode.value = 'none'
}

/** 单帧轮询：有真实帧回真实帧，没有且开着演示模式才回演示帧（X-Frame-Mode 区分）。
 *  新帧先在隐藏的 Image 里解码完成再替换显示，避免每帧闪一下；
 *  间隔按门店推流帧率自适应（5fps → 200ms），把延迟压到「一帧之内」。
 */
async function pollFrame() {
  const current = session.value
  if (!current) return
  try {
    const res = await fetch(cameraFrameUrl(current.token))
    // 请求期间用户可能已经点了「结束观看」：不要再把帧塞回已关闭的播放器（会泄漏 objectURL）
    if (session.value !== current) return
    if (res.status === 204) {
      frameMode.value = 'none'
      return
    }
    if (!res.ok) return
    const blob = await res.blob()
    if (session.value !== current) return
    const mode = res.headers.get('x-frame-mode') === 'demo' ? 'demo' : 'live'
    const url = URL.createObjectURL(blob)
    const pre = new Image()
    pre.onload = () => {
      if (session.value !== current) {
        URL.revokeObjectURL(url)
        return
      }
      const previous = frameUrl.value
      frameUrl.value = url
      frameMode.value = mode
      // 旧帧等一拍再释放，避免 img 还没换源就被回收导致白屏
      if (previous) window.setTimeout(() => URL.revokeObjectURL(previous), 1000)
    }
    pre.onerror = () => URL.revokeObjectURL(url)
    pre.src = url
  } catch {
    /* 网络抖动丢一次轮询，下一轮再取 */
  }
}

/** 串行轮询（下一次等上一次回来再排），避免请求堆积把延迟越拖越大 */
function startFrameLoop() {
  stopFrameLoop()
  const token = ++loopToken
  const interval = Math.max(120, Math.round(1000 / Math.max(session.value?.fps || 5, 1)))
  const tick = async () => {
    if (token !== loopToken) return
    await pollFrame()
    if (token !== loopToken) return
    frameTimer = window.setTimeout(tick, interval)
  }
  void tick()
}

function stopFrameLoop() {
  loopToken += 1
  if (frameTimer) {
    window.clearTimeout(frameTimer)
    frameTimer = null
  }
  clearFrame()
}

/** 结束观看并关闭弹窗（按钮入口：**不要直接绑 stopWatch**，Vue 会把 MouseEvent 当 keepOpen 传进去） */
function closePlayer() {
  void stopWatch(false).then(() => ElMessage.success('已结束观看'))
}

/** 弹窗关闭（含右上角 X 与 ESC）：只做资源释放，不再重复触发关闭 */
function onDialogClosed() {
  void stopWatch(true)
}

async function retry() {
  if (!current.value) {
    playError.value = ''
    return
  }
  await stopWatch(true)
  await watch(current.value)
}

function startCountdown(seconds: number) {
  countdown.value = seconds
  if (timer) window.clearInterval(timer)
  timer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      window.clearInterval(timer!)
      timer = null
      stopFrameLoop()
      playError.value = '观看凭证已过期'
      ElMessage.warning('观看凭证已过期，请重新打开画面')
    }
  }, 1000)
}

async function stopWatch(keepOpen = false) {
  stopFrameLoop()
  if (timer) {
    window.clearInterval(timer)
    timer = null
  }
  if (session.value) {
    await cameraApi.endSession(session.value.session_id).catch(() => undefined)
  }
  session.value = null
  playError.value = ''
  if (!keepOpen) playerVisible.value = false
}

/**
 * 页面初始化：
 * 1) 拉可观看列表；
 * 2) 若从 AI 对话跳过来（`?order_id=xxx`），直接打开那一单的画面 ——
 *    用户说的是「看豆豆的实景」，不该让他到了页面自己再找一遍；
 * 3) 该单不可看（设备离线/停用/未装）时用小窗说明原因，不让人对着空列表猜。
 */
onMounted(async () => {
  await load()
  const wanted = Number(route.query.order_id)
  if (!wanted) return
  const item = items.value.find((i) => i.order_id === wanted)
  if (item?.can_watch) {
    await watch(item)
    return
  }
  const reason = item?.reason || '这一单现在还不能观看（可能需要先办理入住）'
  ElMessageBox.alert(reason, '暂时无法观看', {
    type: 'warning',
    confirmButtonText: '知道了',
    confirmButtonClass: 'el-button--primary'
  }).catch(() => undefined)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
  stopFrameLoop()
})
</script>

<style scoped>
.live-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
}

.live-card__name {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.live-card__meta {
  margin-top: 4px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.live-card__reason {
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.live-card__btn {
  margin-top: var(--pp-space-3);
  width: 100%;
}

.player {
  position: relative;
  border-radius: var(--pp-radius-lg);
  overflow: hidden;
  background: #1f1d1a;
}

.player__video {
  width: 100%;
  display: block;
}

.player__placeholder {
  height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 画面加载不出来时的兜底区：留白 + 可操作按钮，不能是空白 */
.player__empty {
  height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--pp-bg-sunken);
}

.player__watermark {
  position: absolute;
  right: 12px;
  bottom: 52px;
  padding: 2px 8px;
  border-radius: var(--pp-radius-sm);
  background: rgba(0, 0, 0, 0.35);
  color: #fff;
  font-size: var(--pp-fs-xs);
  font-family: var(--pp-font-num);
  letter-spacing: 1px;
  pointer-events: none;
}

.player__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
  padding: var(--pp-space-2) var(--pp-space-3);
  background: var(--pp-bg-card);
  flex-wrap: wrap;
}

.player__hint {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
}

.player__ops {
  display: flex;
  gap: var(--pp-space-2);
}
</style>
