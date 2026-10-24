<!--
  寄养详情（宠主）：寄养信息、费用明细、接送任务、每日照护日报（异常条目高亮并标注已推送）。
  数据来源：GET /boarding/orders/:id。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">
          寄养详情
          <el-tag v-if="order" size="small" :type="tone(order.status)" effect="light">
            {{ order.status_label }}
          </el-tag>
        </h2>
        <p class="pp-page-desc">{{ order?.order_no }} · {{ order?.room_no }}</p>
      </div>
      <div class="actions">
        <el-button :icon="Back" @click="router.push('/user/boarding')">返回列表</el-button>
        <el-button v-if="order && order.status === 'pending'" type="danger" plain @click="cancel">取消申请</el-button>
        <el-button v-if="canApplyEarlyPickup" type="warning" plain @click="openEarlyPickup">申请提前接回</el-button>
        <el-button v-if="canExtend" type="primary" plain @click="extendVisible = true">延期</el-button>
      </div>
    </div>

    <!-- 提前接回申请进度：宠主提交 → 门店审核（V8.4.9） -->
    <el-alert
      v-if="order?.early_pickup && order.early_pickup.status !== 'approved'"
      :type="order.early_pickup.status === 'pending' ? 'info' : 'warning'"
      :closable="false"
      show-icon
      class="pp-mb-4"
      :title="`提前接回申请${order.early_pickup.status_label}：期望 ${order.early_pickup.expect_pickup_date} 接回`"
    >
      <div class="early-note">
        <span v-if="order.early_pickup.reason">原因：{{ order.early_pickup.reason }}</span>
        <span v-if="order.early_pickup.review_note">门店意见：{{ order.early_pickup.review_note }}</span>
        <span v-if="order.early_pickup.status === 'pending'" class="pp-dim">
          门店审核通过后，订单会自动转为「提前接回」
        </span>
      </div>
    </el-alert>

    <PawLoading v-if="loading" variant="paw" text="正在加载寄养信息…" />

    <template v-else-if="order">
      <el-alert
        v-if="order.isolate_required"
        type="warning"
        :closable="false"
        show-icon
        title="需隔离观察"
        description="该毛孩子档案中有皮肤病史，入住后会先隔离观察，使用独立工具并单独时段活动。"
        class="pp-mb-4"
      />
      <el-alert
        v-if="order.settle_note"
        type="info"
        :closable="false"
        show-icon
        title="结算说明"
        :description="order.settle_note"
        class="pp-mb-4"
      />

      <el-row :gutter="16">
        <el-col :xs="24" :lg="15">
          <section class="pp-card">
            <div class="pp-card-title">寄养信息</div>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="毛孩子">{{ order.pet_name }}</el-descriptions-item>
              <el-descriptions-item label="房型">{{ order.room_type_label }}</el-descriptions-item>
              <el-descriptions-item label="入住">{{ order.check_in_date }}</el-descriptions-item>
              <el-descriptions-item label="离店">{{ order.check_out_date }}</el-descriptions-item>
              <el-descriptions-item label="寄养晚数">{{ order.nights }} 晚</el-descriptions-item>
              <el-descriptions-item label="喂食方案">{{ order.feeding_plan_label }}</el-descriptions-item>
              <el-descriptions-item label="送宠到店 / 离店接宠">
                {{ order.dropoff_method_label }} / {{ order.pickup_back_method_label }}
              </el-descriptions-item>
              <el-descriptions-item label="疫苗校验">{{ order.vaccine_note || '—' }}</el-descriptions-item>
              <el-descriptions-item label="用药 / 遛放要求" :span="2">
                <template v-if="order.care_plans?.length">
                  <el-tag
                    v-for="plan in order.care_plans"
                    :key="plan.id"
                    size="small"
                    effect="plain"
                    class="pp-mr-2"
                  >
                    {{ CARE_ITEM_LABEL[plan.item_type] || plan.item_type }}：{{ plan.content }}
                    <template v-if="plan.frequency">（{{ plan.frequency }}）</template>
                  </el-tag>
                </template>
                <span v-else>无特殊要求</span>
              </el-descriptions-item>
              <el-descriptions-item v-if="order.checkin_note" label="入住体检" :span="2">
                {{ order.checkin_note }}
              </el-descriptions-item>
              <el-descriptions-item v-if="order.cancel_reason" label="取消原因" :span="2">
                {{ order.cancel_reason }}
              </el-descriptions-item>
              <el-descriptions-item v-if="order.terminate_reason" label="终止原因" :span="2">
                {{ order.terminate_reason }}
              </el-descriptions-item>
            </el-descriptions>
          </section>

          <section class="pp-card">
            <div class="pp-card-title">
              每日照护日报
              <span class="pp-card-extra">{{ order.care_logs?.length || 0 }} 条记录</span>
            </div>
            <EmptyState
              v-if="!order.care_logs?.length"
              illustration="cat"
              title="还没有照护日报"
              description="入住后店员会每天记录进食、饮水、精神与活动情况，并至少上传一张照片。"
              :size="76"
            />
            <div v-else class="log-list">
              <div v-for="log in order.care_logs" :key="log.id" class="log-item" :class="{ 'is-abnormal': log.abnormal }">
                <div class="log-item__head">
                  <span class="log-item__date">{{ log.log_date }}</span>
                  <el-tag v-if="log.abnormal" size="small" type="danger" effect="light">异常已推送</el-tag>
                  <el-tag v-else size="small" type="success" effect="light">正常</el-tag>
                </div>
                <div class="log-item__grid">
                  <span>进食：{{ log.eating || '正常' }}</span>
                  <span>饮水：{{ log.drinking || '正常' }}</span>
                  <span>排便：{{ log.stool || '正常' }}</span>
                  <span>精神：{{ log.spirit || '正常' }}</span>
                  <span>活动：{{ log.activity || '正常' }}</span>
                </div>
                <p v-if="log.abnormal_note" class="log-item__note">异常记录：{{ log.abnormal_note }}</p>
                <div v-if="log.photos.length" class="log-item__photos">
                  <el-tag v-for="p in log.photos" :key="p" size="small" effect="plain">{{ p }}</el-tag>
                </div>
              </div>
            </div>
          </section>
        </el-col>

        <el-col :xs="24" :lg="9">
          <section class="pp-card">
            <div class="pp-card-title">费用明细</div>
            <div class="fee-row"><span>平均日费</span><b>¥{{ order.daily_fee.toFixed(2) }}</b></div>
            <div class="fee-row"><span>{{ order.nights }} 晚房费</span><b>¥{{ order.subtotal.toFixed(2) }}</b></div>
            <div v-if="order.discount_percent < 100" class="fee-row fee-row--discount">
              <span>长住折扣</span><b>{{ order.discount_percent / 10 }} 折</b>
            </div>
            <div v-if="order.extra_fee" class="fee-row"><span>喂食升级</span><b>¥{{ order.extra_fee.toFixed(2) }}</b></div>
            <div v-if="order.shipping_fee" class="fee-row"><span>接送费</span><b>¥{{ order.shipping_fee.toFixed(2) }}</b></div>
            <el-divider />
            <div class="fee-total"><span>应付总额</span><b>¥{{ order.total_amount.toFixed(2) }}</b></div>
          </section>

          <section v-if="order.pickup_tasks?.length" class="pp-card">
            <div class="pp-card-title">接送任务</div>
            <div v-for="task in order.pickup_tasks" :key="task.id" class="task-item">
              <div class="task-item__head">
                <span>{{ task.task_type_label }}</span>
                <el-tag size="small" effect="light">{{ task.status_label }}</el-tag>
              </div>
              <div class="task-item__meta">
                {{ task.address || '—' }}<template v-if="task.slot_time"> · {{ task.slot_time }}</template>
                · 费用 ¥{{ task.fee.toFixed(2) }}
              </div>
              <div v-if="task.sign_off_by" class="task-item__meta">签收：{{ task.sign_off_by }}</div>
            </div>
          </section>

          <section class="pp-card">
            <div class="pp-card-title">紧急联系与授权</div>
            <p class="kv">紧急联系人：{{ order.emergency_contact || '未填写' }}</p>
            <p class="kv">联系电话：{{ order.emergency_phone || '未填写' }}</p>
            <p class="kv">授权就医：{{ order.medical_authorized ? '已授权' : '未授权' }}</p>
          </section>
        </el-col>
      </el-row>
    </template>

    <el-dialog v-model="extendVisible" title="延长寄养" width="420px">
      <p class="hint">延期会重新校验房态并按新时长重算费用；若房态冲突会提示更换房型。</p>
      <el-date-picker
        v-model="newCheckOut"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="新的离店日期"
        :disabled-date="(d: Date) => !order || d.getTime() <= new Date(order.check_out_date).getTime()"
        style="width: 100%"
      />
      <template #footer>
        <el-button @click="extendVisible = false">取消</el-button>
        <el-button type="primary" :loading="extending" @click="submitExtend">确认延期</el-button>
      </template>
    </el-dialog>

    <!-- 申请提前接回：宠主填期望日期与原因，提交后等门店审核 -->
    <el-dialog v-model="earlyVisible" title="申请提前接回" width="440px">
      <p class="hint">
        提交后由门店审核；通过后订单自动转为「提前接回」，费用按实际天数结算。
      </p>
      <el-form label-position="top">
        <el-form-item label="期望接回日期" required>
          <el-date-picker
            v-model="earlyDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择接回日期"
            :disabled-date="disableEarlyDate"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="原因">
          <el-input
            v-model="earlyReason"
            type="textarea"
            :rows="2"
            maxlength="120"
            show-word-limit
            placeholder="如：行程有变、毛孩子状态不好想早点接回"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="earlyVisible = false">取消</el-button>
        <el-button type="primary" :loading="earlySubmitting" @click="submitEarlyPickup">提交申请</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { boardingApi } from '@/api/boarding'
import { BOARDING_STATUS_TONE, CARE_ITEM_LABEL } from '@/utils/dict'
import type { BoardingOrder } from '@/types'

const route = useRoute()
const router = useRouter()
const order = ref<BoardingOrder | null>(null)
const loading = ref(true)
const extendVisible = ref(false)
const extending = ref(false)
const newCheckOut = ref('')

const orderId = computed(() => Number(route.params.id))
const canExtend = computed(() =>
  ['pending', 'confirmed', 'waiting_checkin', 'checked_in', 'waiting_pickup'].includes(order.value?.status || '')
)

// ---- 提前接回：寄养中/待接回、且没有待审核的申请时才能提交 ----
const earlyVisible = ref(false)
const earlyDate = ref('')
const earlyReason = ref('')
const earlySubmitting = ref(false)

const canApplyEarlyPickup = computed(() => {
  const status = order.value?.status || ''
  if (!['checked_in', 'waiting_pickup'].includes(status)) return false
  return order.value?.early_pickup?.status !== 'pending'
})

/** 只能选「今天 ~ 原定离店前一天」 */
function disableEarlyDate(d: Date) {
  if (!order.value) return true
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const checkout = new Date(order.value.check_out_date)
  return d.getTime() < today.getTime() || d.getTime() >= checkout.getTime()
}

/** 日期格式化（不能用 toISOString：东八区会差一天） */
function fmtDate(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function openEarlyPickup() {
  // 默认填「明天」；若明天已到/超过离店日，就取离店前一天 —— 用户不选也能直接提交
  const tomorrow = new Date()
  tomorrow.setDate(tomorrow.getDate() + 1)
  let base = tomorrow
  if (order.value) {
    const checkout = new Date(order.value.check_out_date)
    if (tomorrow.getTime() >= checkout.getTime()) {
      base = new Date(checkout.getTime() - 86400000)
    }
  }
  earlyDate.value = fmtDate(base)
  earlyReason.value = ''
  earlyVisible.value = true
}

async function submitEarlyPickup() {
  if (!order.value) return
  if (!earlyDate.value) {
    ElMessage.warning('请选择期望接回日期')
    return
  }
  earlySubmitting.value = true
  try {
    await boardingApi.applyEarlyPickup(order.value.id, {
      expect_pickup_date: earlyDate.value,
      reason: earlyReason.value.trim() || undefined
    })
    ElMessage.success('申请已提交，等待门店审核')
    earlyVisible.value = false
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.message || '提交失败')
  } finally {
    earlySubmitting.value = false
  }
}

function tone(s: string) {
  return BOARDING_STATUS_TONE[s] || 'info'
}

async function load() {
  loading.value = true
  try {
    order.value = await boardingApi.orderDetail(orderId.value)
    newCheckOut.value = order.value.check_out_date
  } finally {
    loading.value = false
  }
}

async function cancel() {
  await ElMessageBox.confirm('取消后该房舍会释放给其他毛孩子，确定取消这次寄养申请吗？', '取消寄养', {
    confirmButtonText: '确定取消',
    cancelButtonText: '再想想',
    type: 'warning'
  })
  await boardingApi.cancelOrder(orderId.value, '宠主自助取消')
  ElMessage.success('寄养申请已取消')
  load()
}

async function submitExtend() {
  if (!newCheckOut.value) return
  extending.value = true
  try {
    await boardingApi.extendOrder(orderId.value, newCheckOut.value)
    ElMessage.success('已延期')
    extendVisible.value = false
    load()
  } finally {
    extending.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.early-note {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
}

.actions {
  display: flex;
  gap: var(--pp-space-2);
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.log-item {
  padding: var(--pp-space-3) var(--pp-space-4);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
}

.log-item.is-abnormal {
  border-color: rgba(224, 122, 95, 0.4);
  background: var(--pp-danger-bg);
}

.log-item__head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  margin-bottom: var(--pp-space-2);
}

.log-item__date {
  font-family: var(--pp-font-num);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.log-item__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 4px;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.log-item__note {
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-sm);
  color: var(--pp-danger);
}

.log-item__photos {
  display: flex;
  gap: 4px;
  margin-top: var(--pp-space-2);
  flex-wrap: wrap;
}

.fee-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: var(--pp-fs-base);
  color: var(--pp-text-regular);
}

.fee-row b {
  font-family: var(--pp-font-num);
  color: var(--pp-text-primary);
}

.fee-row--discount b {
  color: var(--pp-success);
}

.fee-total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--pp-fs-md);
}

.fee-total b {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-2xl);
  color: var(--pp-danger);
}

.task-item {
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  margin-bottom: var(--pp-space-2);
}

.task-item__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.task-item__meta {
  margin-top: 4px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.kv {
  padding: 4px 0;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.hint {
  margin-bottom: var(--pp-space-3);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  line-height: 1.7;
}
</style>
