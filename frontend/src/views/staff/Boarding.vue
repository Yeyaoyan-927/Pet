<!--
  寄养工作台（店员/店长）：状态指标卡 + 订单 / 接送任务 / 房态三页签。
  数据来源：GET /boarding/orders、/pickup-tasks、/rooms。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">寄养管理</h2>
        <p class="pp-page-desc">
          寄养订单全流程：确认 → 待入住 → 办理入住（含健康初检）→ 每日照护日志 → 待接回 → 完成接回；
          异常终止类必须填写原因，全程审计留痕。
        </p>
      </div>
      <div class="header-ops">
        <el-badge :value="earlyPending.length" :hidden="!earlyPending.length" :max="99">
          <el-button :icon="Tickets" @click="openEarly">提前接回审核</el-button>
        </el-badge>
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="12">
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待确认" :value="stat.pending" icon="Clock" tone="warning" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待入住" :value="stat.waiting_checkin" icon="Calendar" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="寄养中" :value="stat.checked_in" icon="HomeFilled" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待接回" :value="stat.waiting_pickup" icon="Van" tone="ai" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="异常终止" :value="stat.abnormal" icon="WarnTriangleFilled" tone="danger" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="房舍占用" :value="occupiedRooms" icon="House" tone="success" /></el-col>
    </el-row>

    <section class="pp-card pp-mt-5">
      <el-tabs v-model="tab">
        <el-tab-pane label="寄养订单" name="orders">
          <div class="pp-filter">
            <el-radio-group v-model="status" @change="loadOrders(1)">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button
                v-for="(label, key) in statusOptions"
                :key="key"
                :value="key"
              >{{ label }}</el-radio-button>
            </el-radio-group>
          </div>

          <PawLoading v-if="loading" variant="paw" text="正在加载寄养单…" />
          <EmptyState
            v-else-if="!orders.length"
            illustration="dog"
            title="暂时没有寄养订单"
            description="有新的寄养申请时会在这里出现，确认后即可安排房舍。"
          />

          <el-table v-else :data="orders" stripe>
            <el-table-column prop="order_no" label="寄养单号" width="190" />
            <el-table-column label="毛孩子" width="130">
              <template #default="{ row }">
                <div class="cell-pet">
                  <PetAvatar :species="row.pet_species === 'cat' ? 'cat' : 'dog'" :size="32" />
                  <span>{{ row.pet_name }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="宠主" width="150">
              <template #default="{ row }">
                <div>{{ row.owner_name }}</div>
                <div class="cell-sub">{{ row.owner_phone }}</div>
              </template>
            </el-table-column>
            <el-table-column label="房舍" width="120">
              <template #default="{ row }">
                {{ row.room_no }}
                <div class="cell-sub">{{ row.room_type_label }}</div>
              </template>
            </el-table-column>
            <el-table-column label="寄养区间" width="200">
              <template #default="{ row }">
                {{ row.check_in_date }} ~ {{ row.check_out_date }}
                <div class="cell-sub">{{ row.nights }} 晚</div>
              </template>
            </el-table-column>
            <el-table-column label="标记" width="130">
              <template #default="{ row }">
                <el-tag v-if="row.isolate_required" size="small" type="warning" effect="light">隔离观察</el-tag>
                <el-tag v-if="row.extend_times" size="small" effect="plain">已延期{{ row.extend_times }}次</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="tone(row.status)" effect="light">{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="260" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-for="act in actionsOf(row.status)"
                  :key="act.target"
                  size="small"
                  :type="act.danger ? 'danger' : 'primary'"
                  plain
                  @click="openAction(row, act)"
                >{{ act.label }}</el-button>
                <el-button
                  v-if="['checked_in', 'waiting_pickup'].includes(row.status)"
                  size="small"
                  type="primary"
                  @click="openLog(row)"
                >写日报</el-button>
                <el-button size="small" link type="info" @click="openDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="total > size" class="pp-pager">
            <el-pagination
              layout="prev, pager, next"
              :total="total"
              :page-size="size"
              :current-page="page"
              @current-change="loadOrders"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`接送任务（${tasks.length}）`" name="tasks">
          <EmptyState
            v-if="!tasks.length"
            illustration="paw"
            title="没有待处理的接送任务"
            description="宠主选择上门接宠或送宠到家时，会自动生成接送任务。"
            :size="76"
          />
          <el-table v-else :data="tasks" stripe>
            <el-table-column prop="order_no" label="寄养单号" width="190" />
            <el-table-column prop="task_type_label" label="类型" width="110" />
            <el-table-column prop="address" label="地址" min-width="180" show-overflow-tooltip />
            <el-table-column prop="slot_time" label="时间段" width="120" />
            <el-table-column label="费用" width="100">
              <template #default="{ row }">¥{{ row.fee.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="light">{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.status !== 'arrived'"
                  size="small"
                  type="primary"
                  @click="advance(row)"
                >推进到下一状态</el-button>
                <span v-else class="cell-sub">已完成</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`房态（${rooms.length}）`" name="rooms">
          <div class="room-grid">
            <div v-for="room in rooms" :key="room.id" class="room-card">
              <div class="room-card__head">
                <b>{{ room.room_no }}</b>
                <el-tag size="small" :type="ROOM_STATUS_TONE[room.status] || 'info'" effect="light">
                  {{ room.status_label }}
                </el-tag>
              </div>
              <div class="cell-sub">{{ room.name }} · 系数 {{ room.ratio_percent / 100 }}×</div>
              <div v-if="isManager" class="room-card__ops">
                <el-button
                  v-if="room.status === 'cleaning'"
                  size="small"
                  type="success"
                  plain
                  @click="setRoomStatus(room, 'idle')"
                >消杀完成 → 空闲</el-button>
                <el-button
                  v-if="room.status === 'idle'"
                  size="small"
                  plain
                  @click="setRoomStatus(room, 'maintenance')"
                >转维护</el-button>
                <el-button
                  v-if="room.status === 'maintenance'"
                  size="small"
                  type="success"
                  plain
                  @click="setRoomStatus(room, 'idle')"
                >维护完成</el-button>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <!-- 状态操作 -->
    <el-dialog v-model="actionVisible" :title="actionTitle" width="460px">
      <el-form label-position="top">
        <el-form-item v-if="current?.checkin" label="入住健康初检记录">
          <el-input
            v-model="actionForm.checkin_note"
            type="textarea"
            :rows="2"
            placeholder="如：体温正常、皮肤无明显异常、已单独隔离安排"
          />
        </el-form-item>
        <el-form-item v-if="current?.target === 'completed'" label="退房物品清点与消杀记录">
          <el-input
            v-model="actionForm.checkout_note"
            type="textarea"
            :rows="2"
            placeholder="如：自备粮剩余 300g 已退还，房舍已消杀"
          />
        </el-form-item>
        <el-form-item v-if="current?.needReason" label="原因（必填）">
          <el-input v-model="actionForm.reason" type="textarea" :rows="2" placeholder="请填写原因，将写入审计日志" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="actionVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAction">确认</el-button>
      </template>
    </el-dialog>

    <!-- 照护日志 -->
    <el-dialog v-model="logVisible" title="填写每日照护日志" width="560px">
      <el-alert
        v-if="logForm.abnormal"
        type="warning"
        :closable="false"
        show-icon
        title="异常记录会立即单独推送宠主"
        class="pp-mb-4"
      />
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="进食"><el-input v-model="logForm.eating" placeholder="正常 / 偏少 / 拒食" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="饮水"><el-input v-model="logForm.drinking" placeholder="正常 / 偏少 / 偏多" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="排便"><el-input v-model="logForm.stool" placeholder="次数与性状" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="精神"><el-input v-model="logForm.spirit" placeholder="活泼 / 正常 / 萎靡 / 焦躁" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="活动量"><el-input v-model="logForm.activity" placeholder="遛放次数与时长" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="照片地址（逗号分隔）">
              <el-input v-model="logForm.photosText" placeholder="/static/board/xxx.jpg" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="已完成 SOP 检查项">
          <el-checkbox-group v-model="logForm.sop_checked">
            <el-checkbox v-for="item in SOP_ITEMS" :key="item" :value="item">{{ item }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="logForm.abnormal">存在异常情况</el-checkbox>
        </el-form-item>
        <el-form-item v-if="logForm.abnormal" label="异常描述">
          <el-input v-model="logForm.abnormal_note" type="textarea" :rows="2" placeholder="如：下午出现轻微呕吐，已观察并联系医生" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="logVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitLog">提交并推送宠主</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="寄养单详情" width="640px">
      <el-descriptions v-if="detail" :column="2" border>
        <el-descriptions-item label="单号">{{ detail.order_no }}</el-descriptions-item>
        <el-descriptions-item label="毛孩子">{{ detail.pet_name }}</el-descriptions-item>
        <el-descriptions-item label="宠主">{{ detail.owner_name }} {{ detail.owner_phone }}</el-descriptions-item>
        <el-descriptions-item label="房舍">{{ detail.room_no }}（{{ detail.room_type_label }}）</el-descriptions-item>
        <el-descriptions-item label="寄养区间">{{ detail.check_in_date }} ~ {{ detail.check_out_date }}</el-descriptions-item>
        <el-descriptions-item label="晚数">{{ detail.nights }} 晚</el-descriptions-item>
        <el-descriptions-item label="喂食">{{ detail.feeding_plan_label }}</el-descriptions-item>
        <el-descriptions-item label="送宠到店 / 离店接宠">
          {{ detail.dropoff_method_label }} / {{ detail.pickup_back_method_label }}
        </el-descriptions-item>
        <el-descriptions-item label="疫苗校验" :span="2">{{ detail.vaccine_note || '—' }}</el-descriptions-item>
        <el-descriptions-item label="费用" :span="2">
          房租 ¥{{ detail.subtotal.toFixed(2) }} + 喂食 ¥{{ detail.extra_fee.toFixed(2) }}
          + 接送 ¥{{ detail.shipping_fee.toFixed(2) }} =
          <b>¥{{ detail.total_amount.toFixed(2) }}</b>
          <template v-if="detail.discount_percent < 100">（已按 {{ detail.discount_percent / 10 }} 折）</template>
        </el-descriptions-item>
        <el-descriptions-item label="照护要求" :span="2">
          <template v-if="detail.care_plans?.length">
            <div v-for="plan in detail.care_plans" :key="plan.id">
              · {{ CARE_ITEM_LABEL[plan.item_type] || plan.item_type }}：{{ plan.content }}
              <template v-if="plan.frequency">（{{ plan.frequency }}）</template>
              <el-tag v-if="plan.need_staff" size="small" effect="plain">需店员操作</el-tag>
            </div>
          </template>
          <span v-else>无</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
    <!-- 提前接回审核：宠主申请 → 门店通过/驳回（V8.4.9） -->
    <el-dialog v-model="earlyVisible" title="提前接回审核" width="720px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="宠主提交申请后由门店审核；通过会自动把订单转为「提前接回」并释放房舍。"
        class="pp-mb-4"
      />
      <PawLoading v-if="earlyLoading" variant="paw" text="正在加载申请…" />
      <EmptyState
        v-else-if="!earlyList.length"
        illustration="cat"
        title="暂无提前接回申请"
        description="宠主在「寄养详情」里提交后，这里会出现待审核记录。"
        :size="72"
      />
      <el-table v-else :data="earlyList" stripe>
        <el-table-column prop="order_no" label="单号" width="180" show-overflow-tooltip />
        <el-table-column prop="pet_name" label="宠物" width="90" />
        <el-table-column prop="expect_pickup_date" label="期望接回" width="110" />
        <el-table-column prop="reason" label="原因" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.reason || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.status === 'pending' ? 'warning' : row.status === 'approved' ? 'success' : 'info'"
              effect="light"
            >{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="review_note" label="审核意见" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.review_note || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button link type="primary" @click="reviewEarly(row, true)">通过</el-button>
              <el-button link type="danger" @click="reviewEarly(row, false)">驳回</el-button>
            </template>
            <span v-else class="pp-dim">已处理</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Tickets } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import StatCard from '@/components/StatCard.vue'
import { boardingApi } from '@/api/boarding'
import { useUserStore } from '@/stores/user'
import { BOARDING_STATUS_TONE, CARE_ITEM_LABEL, ROOM_STATUS_TONE } from '@/utils/dict'
import type { BoardingEarlyPickup, BoardingOrder, BoardingPickupTask, BoardingRoom } from '@/types'

// ---- 页面结构（阅读顺序）----
// 1) 状态：orders / pickupTasks / rooms（三个页签）、detail（订单详情抽屉）、careLog（照护日志表单）
// 2) computed：统计卡（待确认/待入住/寄养中/待接回/异常/房舍占用）由 orders 与 rooms 直接推导
// 3) 操作按钮由状态机生成：nextActions(status) 决定能推进到哪些状态，终止类强制填原因
// 4) 房态闭环：退房后房态转「清洁中」，由店长确认消杀后才转回空闲
// 5) 生命周期：onMounted 并行拉订单、接送任务、房态

interface ActionDef {
  label: string
  target: string
  needReason?: boolean
  danger?: boolean
  checkin?: boolean
}

const SOP_ITEMS = ['喂食', '换水', '房间清洁', '猫砂清理', '遛放', '互动陪伴', '健康观察', '拍照', '日志提交']

const userStore = useUserStore()
const isManager = computed(() => userStore.role === 'manager')

const tab = ref('orders')
const status = ref('')
const orders = ref<BoardingOrder[]>([])
const tasks = ref<BoardingPickupTask[]>([])
const rooms = ref<BoardingRoom[]>([])
const loading = ref(true)
const submitting = ref(false)
const page = ref(1)
const size = ref(10)
const total = ref(0)

const actionVisible = ref(false)
const logVisible = ref(false)
const detailVisible = ref(false)
const current = ref<(ActionDef & { id: number }) | null>(null)
const detail = ref<BoardingOrder | null>(null)

const actionForm = reactive({ reason: '', checkin_note: '', checkout_note: '' })
const logForm = reactive({
  orderId: 0,
  eating: '',
  drinking: '',
  stool: '',
  spirit: '',
  activity: '',
  photosText: '',
  sop_checked: [] as string[],
  abnormal: false,
  abnormal_note: ''
})

const statusOptions = {
  pending: '待确认',
  confirmed: '已确认',
  waiting_checkin: '待入住',
  checked_in: '寄养中',
  waiting_pickup: '待接回',
  completed: '已完成',
  early_pickup: '提前接回',
  overdue_unpicked: '超时未接回',
  cancelled: '已取消',
  no_show: '爽约',
  medical_terminated: '异常终止'
}

const stat = computed(() => {
  const base: Record<string, number> = {
    pending: 0, waiting_checkin: 0, checked_in: 0, waiting_pickup: 0, abnormal: 0
  }
  for (const o of orders.value) {
    if (o.status in base) base[o.status] += 1
    if (['medical_terminated', 'overdue_unpicked'].includes(o.status)) base.abnormal += 1
  }
  return base
})
const occupiedRooms = computed(() => rooms.value.filter((r) => r.status === 'occupied').length)
const actionTitle = computed(() => (current.value ? `确认执行：${current.value.label}` : ''))

function tone(s: string) {
  return BOARDING_STATUS_TONE[s] || 'info'
}

/** 按状态机生成可用操作（与后端 BOARDING_TRANSITIONS 对齐） */
function actionsOf(s: string): ActionDef[] {
  const map: Record<string, ActionDef[]> = {
    pending: [
      { label: '确认订单', target: 'confirmed' },
      { label: '取消', target: 'cancelled', needReason: true, danger: true }
    ],
    confirmed: [
      { label: '待入住', target: 'waiting_checkin' },
      { label: '爽约未入住', target: 'no_show', needReason: true, danger: true }
    ],
    waiting_checkin: [
      { label: '办理入住', target: 'checked_in', checkin: true },
      { label: '爽约未入住', target: 'no_show', needReason: true, danger: true }
    ],
    checked_in: [
      { label: '待接回', target: 'waiting_pickup' },
      // 「提前接回」改成宠主申请 + 门店审核（V8.4.9），这里不再直接推进状态
      { label: '健康异常终止', target: 'medical_terminated', needReason: true, danger: true }
    ],
    waiting_pickup: [
      { label: '完成接回', target: 'completed' },
      { label: '超时未接回', target: 'overdue_unpicked', needReason: true, danger: true }
    ]
  }
  return map[s] || []
}

function openAction(row: BoardingOrder, act: ActionDef) {
  current.value = { ...act, id: row.id }
  actionForm.reason = ''
  actionForm.checkin_note = ''
  actionForm.checkout_note = ''
  actionVisible.value = true
}

async function submitAction() {
  if (!current.value) return
  const { id, target, needReason } = current.value
  if (needReason && !actionForm.reason.trim()) {
    ElMessage.warning('请填写原因')
    return
  }
  submitting.value = true
  try {
    const res = await boardingApi.changeStatus(id, {
      target_status: target,
      reason: actionForm.reason || undefined,
      checkin_note: actionForm.checkin_note || undefined,
      checkout_note: actionForm.checkout_note || undefined
    })
    ElMessage.success(
      `状态已更新为「${res.status_label}」${res.settle_note ? '；' + res.settle_note : ''}`
    )
    actionVisible.value = false
    await loadAll()
  } finally {
    submitting.value = false
  }
}

function openLog(row: BoardingOrder) {
  logForm.orderId = row.id
  logForm.eating = ''
  logForm.drinking = ''
  logForm.stool = ''
  logForm.spirit = ''
  logForm.activity = ''
  logForm.photosText = ''
  logForm.sop_checked = []
  logForm.abnormal = false
  logForm.abnormal_note = ''
  logVisible.value = true
}

async function submitLog() {
  submitting.value = true
  try {
    await boardingApi.addCareLog(logForm.orderId, {
      eating: logForm.eating || undefined,
      drinking: logForm.drinking || undefined,
      stool: logForm.stool || undefined,
      spirit: logForm.spirit || undefined,
      activity: logForm.activity || undefined,
      photos: logForm.photosText ? logForm.photosText.split(',').map((p) => p.trim()).filter(Boolean) : [],
      sop_checked: logForm.sop_checked,
      abnormal: logForm.abnormal,
      abnormal_note: logForm.abnormal_note || undefined
    })
    ElMessage.success(logForm.abnormal ? '日志已提交，异常已推送宠主' : '照护日报已推送宠主')
    logVisible.value = false
  } finally {
    submitting.value = false
  }
}

async function openDetail(row: BoardingOrder) {
  detail.value = await boardingApi.orderDetail(row.id)
  detailVisible.value = true
}

async function advance(task: BoardingPickupTask) {
  let signOff: string | undefined
  if (task.status === 'picked') {
    const { value } = await ElMessageBox.prompt('请填写宠主签收人', '送达签收', {
      confirmButtonText: '确认送达',
      cancelButtonText: '取消'
    }).catch(() => ({ value: '' }))
    if (!value) return
    signOff = value
  }
  await boardingApi.advancePickup(task.id, signOff ? { sign_off_by: signOff } : {})
  ElMessage.success('接送任务已推进')
  await loadAll()
}

async function setRoomStatus(room: BoardingRoom, target: string) {
  await boardingApi.updateRoomStatus(room.id, target)
  ElMessage.success('房态已更新')
  await loadAll()
}

async function loadOrders(p = page.value) {
  page.value = p
  loading.value = true
  try {
    const res = await boardingApi.orders({ status: status.value || undefined, page: p, size: 100 })
    orders.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  const [taskList, roomList] = await Promise.all([boardingApi.pickupTasks(), boardingApi.rooms()])
  tasks.value = taskList
  rooms.value = roomList
  await loadOrders(1)
  // 待审核数用角标提示，避免宠主提交后没人看见
  try {
    earlyPending.value = await boardingApi.earlyPickups('pending')
  } catch {
    earlyPending.value = []
  }
}

// ---------------------------------------------------------------- 提前接回审核
const earlyVisible = ref(false)
const earlyLoading = ref(false)
const earlyList = ref<BoardingEarlyPickup[]>([])
const earlyPending = ref<BoardingEarlyPickup[]>([])

async function openEarly() {
  earlyVisible.value = true
  earlyLoading.value = true
  try {
    earlyList.value = await boardingApi.earlyPickups()
  } finally {
    earlyLoading.value = false
  }
}

async function reviewEarly(req: BoardingEarlyPickup, approve: boolean) {
  let note = ''
  if (approve) {
    try {
      const res = await ElMessageBox.prompt(
        `通过后订单「${req.order_no}」会转为「提前接回」并释放房舍。`,
        '通过提前接回',
        { inputPlaceholder: '备注（可选）', confirmButtonText: '通过', cancelButtonText: '取消' }
      )
      note = res.value || ''
    } catch {
      return
    }
  } else {
    try {
      const res = await ElMessageBox.prompt('驳回需要说明原因，宠主会收到通知。', '驳回申请', {
        inputPlaceholder: '如：当日已有接送任务 / 需确认宠物状态',
        inputValidator: (v: string) => (v && v.trim() ? true : '请填写驳回原因'),
        confirmButtonText: '驳回',
        cancelButtonText: '取消'
      })
      note = res.value || ''
    } catch {
      return
    }
  }
  try {
    await boardingApi.reviewEarlyPickup(req.id, { approve, note: note || undefined })
    ElMessage.success(approve ? '已通过，订单已转为提前接回' : '已驳回并通知宠主')
    await openEarly()
    await loadAll()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.message || '审核失败')
  }
}

onMounted(loadAll)
</script>

<style scoped>
.header-ops {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
}

.cell-pet {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
}

.cell-sub {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.room-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--pp-space-3);
}

.room-card {
  padding: var(--pp-space-3) var(--pp-space-4);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-lg);
  background: var(--pp-bg-sunken);
}

.room-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  color: var(--pp-text-primary);
}

.room-card__ops {
  margin-top: var(--pp-space-2);
  display: flex;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}
</style>
