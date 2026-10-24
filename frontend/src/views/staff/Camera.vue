<!--
  实景采集台（店员）：选在住宠物 → 打开本机摄像头 → 预览并逐帧推送，右侧显示设备在线状态。
  注意：浏览器只能打开**本机**摄像头，页面上必须写清楚，避免店员误以为能远程开门店设备。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">实景采集台</h2>
        <p class="pp-page-desc">
          门店电脑摄像头采集 → 后端转发 → 宠主端播放。开启采集后请保持本页在前台，关闭即停止推流。
        </p>
      </div>
      <div class="header-ops">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openAddDevice">添加摄像头</el-button>
      </div>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="使用说明"
      description="浏览器只能打开「本机」摄像头；接真网络摄像头时把设备的采集方式改为 RTSP→HLS（正式版，需 FFmpeg）。"
      class="pp-mb-4"
    />

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <section class="pp-card">
          <div class="pp-card-title">采集与推流</div>
          <el-form label-position="top">
            <el-form-item label="要观看的在住宠物（对应宠舍摄像头）">
              <el-select v-model="orderId" placeholder="选择在住宠物" style="width: 100%" @change="onPickOrder">
                <el-option
                  v-for="item in live"
                  :key="item.order_id"
                  :label="`${item.pet_name}（${item.order_no}）`"
                  :value="item.order_id"
                  :disabled="!item.can_watch && !item.device_id"
                />
              </el-select>
            </el-form-item>
            <el-form-item v-if="pickedDevice" label="目标设备">
              <el-tag size="small" effect="plain">{{ pickedDevice.name }}</el-tag>
              <el-tag size="small" :type="pickedDevice.status === 'online' ? 'success' : 'info'" effect="light">
                {{ pickedDevice.status_label }}
              </el-tag>
            </el-form-item>
          </el-form>

          <div ref="videoBox" class="capture">
            <video ref="videoEl" autoplay playsinline muted class="capture__video" />
            <div v-if="!streaming" class="capture__mask">
              <p>{{ captureError || '点击下方按钮开启本机摄像头' }}</p>
            </div>
            <div v-if="streaming" class="capture__badge">
              <i class="dot" :class="{ bad: pushStalled }" />
              推流中 · 已推送 {{ pushedFrames }} 帧 · {{ fps }} fps
              <template v-if="pushStalled">· 推送异常，请停止后重新开启</template>
            </div>
          </div>

          <div class="capture__ops">
            <el-button v-if="!streaming" type="primary" :icon="VideoCamera" :disabled="!orderId" @click="startCapture">
              开启采集并推流
            </el-button>
            <el-button v-else type="danger" plain @click="stopCapture">停止推流</el-button>
            <el-button v-if="pickedDevice" :icon="Aim" @click="heartbeat">上报心跳</el-button>
          </div>
          <p class="hint">
            提示：推流只在内存转发、不落盘；抓拍由宠主端一键保存。门店上行不足时可在门店配置里调低帧率。
          </p>
        </section>
      </el-col>

      <el-col :xs="24" :lg="10">
        <section class="pp-card">
          <div class="pp-card-title">
            设备与在住宠物
            <span class="pp-card-extra">
              {{ devices.length }} 台设备<template v-if="pendingDevices.length"> · {{ pendingDevices.length }} 条待接入</template>
            </span>
          </div>
          <div class="device-list">
            <div v-for="device in devices" :key="device.id" class="device">
              <div>
                <div class="device__name">{{ device.room_no }} · {{ device.name }}</div>
                <div class="device__meta">
                  {{ device.provider_label }} · {{ device.fps }}fps · {{ device.resolution }}
                </div>
              </div>
              <div class="device__right">
                <el-tag size="small" :type="device.status === 'online' ? 'success' : 'info'" effect="light">
                  {{ device.status_label }}
                </el-tag>
                <el-button size="small" link type="primary" @click="heartbeatOf(device.id)">心跳</el-button>
                <el-button
                  v-if="device.status !== 'disabled'"
                  size="small"
                  link
                  type="danger"
                  :loading="deviceBusy === device.id"
                  @click="toggleDevice(device)"
                >关闭摄像头</el-button>
                <el-button v-else size="small" link type="success" @click="toggleDevice(device)">重新启用</el-button>
              </div>
            </div>
          </div>

          <!-- 待接入设备：演示功能，提交只存在浏览器本地，不写设备库 -->
          <div v-if="pendingDevices.length" class="pending">
            <div class="pending__title">待接入设备（演示）</div>
            <div v-for="(item, index) in pendingDevices" :key="item.id" class="device">
              <div>
                <div class="device__name">{{ item.room_no }} · {{ item.name }}</div>
                <div class="device__meta">
                  {{ item.provider_label }} · {{ item.fps }}fps · {{ item.resolution }}
                </div>
              </div>
              <div class="device__right">
                <el-tag size="small" type="warning" effect="light">待接入</el-tag>
                <el-button size="small" link type="danger" @click="removePending(index)">撤销</el-button>
              </div>
            </div>
          </div>

          <el-divider />
          <div class="pp-card-title">在住宠物</div>
          <EmptyState
            v-if="!live.length"
            illustration="paw"
            title="当前没有在住宠物"
            description="办理入住后，店员就可以为它开启实时画面。"
            :size="64"
          />
          <div v-else class="pet-list">
            <div v-for="item in live" :key="item.order_id" class="pet">
              <div>
                <div class="device__name">{{ item.pet_name }}</div>
                <div class="device__meta">{{ item.order_no }} · {{ item.check_out_date }} 接回</div>
              </div>
              <el-tag size="small" :type="item.device_status === 'online' ? 'success' : 'info'" effect="light">
                {{ item.device_status === 'online' ? '设备在线' : (item.reason || '设备离线') }}
              </el-tag>
            </div>
          </div>
        </section>
      </el-col>
    </el-row>

    <!-- 添加摄像头：演示功能 —— 可以提交与查看，但不会真正接入设备 -->
    <el-dialog v-model="addVisible" title="添加摄像头与配置" width="560px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="演示功能：配置可以提交，但不会真正生效"
        description="后端不会写入设备库；真实摄像头需要硬件到位后由店长接入。提交后可在设备列表下方看到「待接入」。"
        class="pp-mb-4"
      />
      <el-form label-position="top">
        <el-form-item label="所属宠舍" required>
          <el-select v-model="addForm.room_id" placeholder="选择宠舍" style="width: 100%">
            <el-option
              v-for="room in rooms"
              :key="room.id"
              :label="`${room.room_no} · ${room.name}`"
              :value="room.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="设备名称" required>
          <el-input v-model="addForm.name" maxlength="30" show-word-limit placeholder="例如：标准单间 A102 摄像头" />
        </el-form-item>
        <el-form-item label="接入方式">
          <el-select v-model="addForm.provider_type" style="width: 100%">
            <el-option v-for="(label, key) in providers" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="addForm.resolution" style="width: 100%">
            <el-option label="640 × 480（推荐，省带宽）" value="640x480" />
            <el-option label="1280 × 720" value="1280x720" />
          </el-select>
        </el-form-item>
        <el-form-item label="帧率（fps）">
          <el-input-number v-model="addForm.fps" :min="1" :max="15" />
        </el-form-item>
        <el-form-item v-if="addForm.provider_type === 'rtsp_hls'" label="RTSP 地址">
          <el-input
            v-model="addForm.stream_url"
            placeholder="rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAddDevice">提交配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Aim, Plus, Refresh, VideoCamera } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import { cameraApi } from '@/api/camera'
import { boardingApi } from '@/api/boarding'
import type { BoardingRoom, CameraDeviceItem, CameraLiveItem, CameraSessionOut } from '@/types'

/** 待接入设备：演示功能，仅存浏览器本地，不写后端设备库 */
interface PendingDevice {
  id: string
  room_id: number
  room_no: string
  name: string
  provider_type: string
  provider_label: string
  resolution: string
  fps: number
}

const PENDING_KEY = 'pawpilot_camera_pending'

const devices = ref<CameraDeviceItem[]>([])
const live = ref<CameraLiveItem[]>([])
const rooms = ref<BoardingRoom[]>([])
const providers = ref<Record<string, string>>({})
const orderId = ref<number | undefined>()
const videoEl = ref<HTMLVideoElement>()
const streaming = ref(false)
const pushedFrames = ref(0)
const pushStalled = ref(false)
const captureError = ref('')
const fps = ref(5)
const session = ref<CameraSessionOut | null>(null)
/** 正在切换启停状态的设备 id（按钮 loading，避免连点） */
const deviceBusy = ref<number | null>(null)

// 添加摄像头（演示）表单
const addVisible = ref(false)
const submitting = ref(false)
const pendingDevices = ref<PendingDevice[]>([])
const addForm = ref({
  room_id: undefined as number | undefined,
  name: '',
  provider_type: 'local_webcam',
  resolution: '640x480',
  fps: 5,
  stream_url: ''
})

let mediaStream: MediaStream | null = null
let pushWorker: Worker | null = null
let canvas: HTMLCanvasElement | null = null

const pickedOrder = computed(() => live.value.find((i) => i.order_id === orderId.value))
const pickedDevice = computed(() => {
  const deviceId = pickedOrder.value?.device_id
  if (!deviceId) return null
  return devices.value.find((d) => d.id === deviceId) || null
})

/**
 * 推流定时器跑在 Web Worker 里：浏览器会把**后台标签页**的页面定时器节流到约 1 次/分钟，
 * 店员一切走，页面还显示「推流中」，帧却停了（实测 322 帧后定格），宠主端 10 秒后就
 * 只能落到演示画面。Worker 有独立事件循环，不受同款节流影响。
 */
function startPushWorker(intervalMs: number) {
  stopPushWorker()
  const code =
    'let t=null;onmessage=(e)=>{' +
    'if(e.data&&e.data.cmd==="start"){if(t)clearInterval(t);t=setInterval(()=>postMessage(1),e.data.interval)}' +
    'else{if(t)clearInterval(t);t=null}}'
  pushWorker = new Worker(URL.createObjectURL(new Blob([code], { type: 'application/javascript' })))
  pushWorker.onmessage = () => {
    void pushFrame()
  }
  pushWorker.postMessage({ cmd: 'start', interval: intervalMs })
}

function stopPushWorker() {
  pushWorker?.terminate()
  pushWorker = null
}

async function load() {
  const [deviceList, liveList, meta, roomList] = await Promise.all([
    cameraApi.devices(),
    cameraApi.live(),
    cameraApi.meta(),
    boardingApi.rooms()
  ])
  devices.value = deviceList
  live.value = liveList
  fps.value = meta.rules?.fps || 5
  providers.value = meta.providers || {}
  rooms.value = roomList
}

// ---------------------------------------------------------------- 待接入设备（演示）
function loadPending() {
  try {
    const raw = localStorage.getItem(PENDING_KEY)
    pendingDevices.value = raw ? (JSON.parse(raw) as PendingDevice[]) : []
  } catch {
    pendingDevices.value = []
  }
}

function savePending() {
  localStorage.setItem(PENDING_KEY, JSON.stringify(pendingDevices.value))
}

function openAddDevice() {
  addForm.value = {
    room_id: undefined,
    name: '',
    provider_type: 'local_webcam',
    resolution: '640x480',
    fps: fps.value,
    stream_url: ''
  }
  addVisible.value = true
}

/**
 * 提交配置：**演示功能** —— 只做前端校验与本地登记，不调用 `/camera/devices`，
 * 因此不会写设备库、也不会真的让宠主端看到画面。真实接入需硬件到位后由店长配置。
 */
function submitAddDevice() {
  const { room_id, name, provider_type, resolution, fps: rate, stream_url } = addForm.value
  if (!room_id) {
    ElMessage.warning('请选择所属宠舍')
    return
  }
  if (!name.trim()) {
    ElMessage.warning('请填写设备名称')
    return
  }
  if (provider_type === 'rtsp_hls' && !stream_url.trim()) {
    ElMessage.warning('接入方式为 RTSP 时请填写 RTSP 地址')
    return
  }
  submitting.value = true
  const room = rooms.value.find((r) => r.id === room_id)
  pendingDevices.value.unshift({
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    room_id,
    room_no: room?.room_no || '',
    name: name.trim(),
    provider_type,
    provider_label: providers.value[provider_type] || provider_type,
    resolution,
    fps: rate
  })
  savePending()
  submitting.value = false
  addVisible.value = false
  ElMessage.success('配置已提交（演示：设备接入前不会生效）')
}

function removePending(index: number) {
  pendingDevices.value.splice(index, 1)
  savePending()
  ElMessage.info('已撤销该条配置')
}

// ---------------------------------------------------------------- 关闭 / 启用摄像头
/**
 * 关闭摄像头 = 把该宠舍设备置为「已停用」，宠主端立刻不可观看（可追溯审计）。
 * 与「停止推流」不同：后者只是停止本机采集，设备仍然在线。
 */
async function toggleDevice(device: CameraDeviceItem) {
  const disabling = device.status !== 'disabled'
  if (disabling) {
    try {
      await ElMessageBox.confirm(
        `关闭后宠主端将立刻看不到「${device.room_no || ''} ${device.name}」的画面，` +
          '重新启用需要在本页操作。确定关闭这台摄像头吗？',
        '关闭摄像头',
        { type: 'warning', confirmButtonText: '关闭摄像头', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
  }
  deviceBusy.value = device.id
  try {
    await cameraApi.setDeviceStatus(device.id, disabling ? 'disabled' : 'online')
    ElMessage.success(disabling ? '摄像头已关闭，宠主端不再可见' : '摄像头已重新启用')
    await load()
  } finally {
    deviceBusy.value = null
  }
}

function onPickOrder() {
  captureError.value = ''
}

async function startCapture() {
  if (!orderId.value) return
  captureError.value = ''
  try {
    // 门店端只负责采集与转发：凭证用当前登录的店员身份签发
    session.value = await cameraApi.openSession(orderId.value)
    fps.value = session.value.fps || 5
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480 }
    })
    if (videoEl.value) {
      videoEl.value.srcObject = mediaStream
      await videoEl.value.play()
    }
    canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 480
    streaming.value = true
    pushedFrames.value = 0
    pushStalled.value = false
    startPushWorker(Math.round(1000 / Math.max(fps.value, 1)))
    if (pickedDevice.value) await cameraApi.heartbeat(pickedDevice.value.id)
    ElMessage.success('已开始推流，宠主端即可观看')
  } catch (err) {
    captureError.value =
      err instanceof Error && err.name === 'NotAllowedError'
        ? '摄像头权限被拒绝，请在浏览器地址栏允许后重试'
        : '未检测到可用摄像头（或已被其他程序占用）'
    streaming.value = false
  }
}

/** 上一帧还在编码/上传时跳过本 tick：否则 toBlob 与网络一慢，帧就在队列里越积越多（延迟变高） */
let pushBusy = false

async function pushFrame() {
  if (!session.value || !canvas || !videoEl.value || pushBusy) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.drawImage(videoEl.value, 0, 0, canvas.width, canvas.height)
  pushBusy = true
  canvas.toBlob(async (blob) => {
    try {
      if (!blob || !session.value) return
      const accessToken = localStorage.getItem('pawpilot_access_token')
      const res = await fetch(`/api/v1/camera/frames/${session.value.token}`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/octet-stream'
        },
        body: blob
      })
      if (res.ok) {
        pushedFrames.value += 1
        pushStalled.value = false
      } else {
        // 凭证过期 / 被挤下线等：不能无声失败，店员要知道宠主端已经看不到画面了
        pushStalled.value = true
      }
    } catch {
      pushStalled.value = true
    } finally {
      pushBusy = false
    }
  }, 'image/jpeg', 0.75)
}

async function stopCapture() {
  stopPushWorker()
  mediaStream?.getTracks().forEach((t) => t.stop())
  mediaStream = null
  streaming.value = false
  if (session.value) {
    await cameraApi.endSession(session.value.session_id).catch(() => undefined)
    session.value = null
  }
  ElMessage.info('已停止推流')
}

async function heartbeat() {
  if (!pickedDevice.value) return
  await heartbeatOf(pickedDevice.value.id)
}

async function heartbeatOf(deviceId: number) {
  await cameraApi.heartbeat(deviceId)
  ElMessage.success('心跳已上报，设备转为在线')
  devices.value = await cameraApi.devices()
}

onMounted(() => {
  loadPending()
  void load()
})
onUnmounted(() => {
  stopPushWorker()
  mediaStream?.getTracks().forEach((t) => t.stop())
})
</script>

<style scoped>
.capture {
  position: relative;
  margin: var(--pp-space-3) 0;
  border-radius: var(--pp-radius-lg);
  overflow: hidden;
  background: #1f1d1a;
  aspect-ratio: 4 / 3;
}

.capture__video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.capture__mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--pp-space-4);
  color: #f5f0e8;
  font-size: var(--pp-fs-sm);
  text-align: center;
}

.capture__badge {
  position: absolute;
  left: 12px;
  top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--pp-radius-pill);
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  font-size: var(--pp-fs-xs);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7fb77e;
  animation: pulse 1.4s ease-in-out infinite;
}

.dot.bad {
  background: #e07a5f;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.capture__ops {
  display: flex;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.hint {
  margin-top: var(--pp-space-3);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.7;
}

.device-list,
.pet-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.header-ops {
  display: flex;
  gap: var(--pp-space-2);
}

.pending {
  margin-top: var(--pp-space-3);
  padding-top: var(--pp-space-3);
  border-top: 1px dashed var(--pp-border-color);
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.pending__title {
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-regular);
}

.device,
.pet {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
  padding: var(--pp-space-2) var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
}

.device__name {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.device__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.device__right {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
}
</style>
