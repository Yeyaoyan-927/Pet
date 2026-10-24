<!--
  预约管理（店员/店长）：列表筛选、推进状态、代客下单、查看风险与改期记录。
  数据来源：GET /appointments；状态按钮由状态机决定，终止类强制填原因。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">预约管理</h2>
        <p class="pp-page-desc">
          按状态机流转：待确认 → 已确认 → 已到店 → 洗护中 → 已完成。取消、爽约、到店放弃、洗护中断都必须填写原因。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Phone" @click="openStaffCreate">代客预约</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 150px" @change="reload">
            <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="到店日期">
          <el-date-picker v-model="query.appoint_date" type="date" value-format="YYYY-MM-DD"
                          placeholder="选择日期" clearable style="width: 170px" @change="reload" />
        </el-form-item>
        <el-form-item label="单号">
          <el-input v-model="query.keyword" placeholder="预约单号" clearable style="width: 170px" @keyup.enter="reload" />
        </el-form-item>
        <el-form-item label="归属">
          <el-checkbox v-model="query.mine" @change="reload">仅看我负责的</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
          <el-button :icon="RefreshLeft" @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="加载预约中…" />
      <EmptyState v-else-if="!list.length" illustration="dog" title="没有符合条件的预约" description="换个筛选条件试试吧。" />

      <div v-else class="pp-scroll-x">
        <el-table :data="list" style="width: 100%" :border="false">
          <el-table-column prop="order_no" label="预约单号" min-width="170" fixed="left" show-overflow-tooltip />
          <el-table-column label="宠物" width="110">
            <template #default="{ row }">
              <div class="cell-pet">
                <PetAvatar species="dog" :size="30" />
                <span>{{ row.pet_name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="owner_name" label="宠主" width="100" />
          <el-table-column prop="owner_phone" label="联系手机" width="130">
            <template #default="{ row }">
              <span class="pp-num">{{ row.owner_phone || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="服务" width="110">
            <template #default="{ row }">{{ row.service_type_label }}</template>
          </el-table-column>
          <el-table-column label="到店时间" width="160">
            <template #default="{ row }">
              <span class="pp-num">{{ row.appoint_date }} {{ row.slot_time }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }"><StatusTag :status="row.status" :label="row.status_label" /></template>
          </el-table-column>
          <el-table-column label="风险" width="100">
            <template #default="{ row }"><RiskBadge :level="row.risk_level" /></template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button
                v-for="action in actionsOf(row)"
                :key="action.status"
                link
                :type="action.type"
                @click="changeStatus(row, action)"
              >
                {{ action.label }}
              </el-button>
              <el-button v-if="canReschedule(row)" link type="warning" @click="openReschedule(row)">改期</el-button>
              <el-button link type="primary" @click="openRisk(row)">风险</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-if="total > query.size" class="pp-pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="load"
          @current-change="load"
        />
      </div>
    </section>

    <!-- 代客预约 -->
    <el-dialog v-model="staffCreateVisible" title="代客预约" width="580px" align-center>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="pp-mb-4"
        title="手机号不存在时会自动创建临时客户档案，宠主注册后可认领预约。"
      />
      <el-form ref="staffFormRef" :model="staffForm" :rules="staffRules" label-width="104px">
        <el-form-item label="宠主手机号" prop="phone">
          <el-input v-model="staffForm.phone" maxlength="11" placeholder="11 位手机号" />
        </el-form-item>
        <el-form-item label="选择宠物">
          <el-select v-model="staffForm.pet_id" placeholder="选择已有档案（可留空）" clearable filterable style="width: 100%">
            <el-option v-for="pet in pets" :key="pet.id" :value="pet.id" :label="`${pet.name}（档案 ID ${pet.id}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="宠物名">
          <el-input v-model="staffForm.pet_name" maxlength="50" placeholder="无档案时填写，用于临时建档" />
        </el-form-item>
        <el-form-item label="服务类型" prop="service_type">
          <el-radio-group v-model="staffForm.service_type">
            <el-radio-button v-for="s in serviceOptions" :key="s.value" :value="s.value">{{ s.label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="到店日期" prop="appoint_date">
          <el-date-picker v-model="staffForm.appoint_date" type="date" value-format="YYYY-MM-DD"
                          style="width: 100%" @change="loadStaffSlots" />
        </el-form-item>
        <el-form-item label="到店时段" prop="slot_time">
          <el-select v-model="staffForm.slot_time" style="width: 100%" placeholder="选择时段">
            <el-option v-for="s in staffSlots" :key="s.slot_time" :value="s.slot_time"
                       :label="`${s.slot_time}（余 ${s.remain}/${s.capacity}）`" :disabled="s.disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="staffForm.remark" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="staffCreateVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitStaffCreate">提交代客预约</el-button>
      </template>
    </el-dialog>

    <!-- 改期 -->
    <el-dialog v-model="rescheduleVisible" title="预约改期" width="500px" align-center>
      <el-alert
        v-if="current"
        type="info"
        :closable="false"
        class="pp-mb-4"
        :title="`单号 ${current.order_no}，已改期 ${current.reschedule_times} 次（上限由门店配置控制）`"
      />
      <el-form label-width="104px">
        <el-form-item label="新日期">
          <el-date-picker v-model="rescheduleForm.appoint_date" type="date" value-format="YYYY-MM-DD"
                          style="width: 100%" @change="loadRescheduleSlots" />
        </el-form-item>
        <el-form-item label="新时段">
          <el-select v-model="rescheduleForm.slot_time" style="width: 100%" placeholder="选择时段">
            <el-option v-for="s in rescheduleSlots" :key="s.slot_time" :value="s.slot_time"
                       :label="`${s.slot_time}（余 ${s.remain}/${s.capacity}）`" :disabled="s.disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="改期原因">
          <el-input v-model="rescheduleForm.reason" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rescheduleVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitReschedule">确认改期</el-button>
      </template>
    </el-dialog>

    <!-- 风险报告 -->
    <el-drawer v-model="riskVisible" title="洗护风险报告" size="540px">
      <template v-if="riskReport">
        <el-alert
          :type="riskReport.risk_level === 'high' ? 'error' : 'warning'"
          :closable="false"
          show-icon
          :title="`${riskReport.risk_level_label} · ${riskReport.confirmed ? '已复核' : '待复核'}`"
          :description="`判别引擎：${ENGINE_LABEL[riskReport.engine_type] || riskReport.engine_type}`"
        />
        <div class="pp-card-title pp-mt-5">命中风险项</div>
        <el-table :data="riskReport.risk_items" size="small" empty-text="未命中风险规则">
          <el-table-column label="等级" width="88">
            <template #default="{ row }">
              <el-tag size="small" :type="row.level === 'high' ? 'danger' : 'warning'" effect="light">
                {{ row.level === 'high' ? '高风险' : '低风险' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="desc" label="描述" min-width="140" show-overflow-tooltip />
          <el-table-column prop="advice" label="建议" min-width="160" show-overflow-tooltip />
        </el-table>

        <div class="pp-card-title pp-mt-5">摘要与免责声明</div>
        <p class="summary-text">{{ riskReport.ai_summary }}</p>

        <div class="pp-card-title pp-mt-5">店员复核</div>
        <el-form label-position="top">
          <el-form-item label="处置措施">
            <el-input v-model="handleMeasure" type="textarea" :rows="3" maxlength="500"
                      placeholder="如：双人操作，佩戴防咬嘴套，使用低敏浴液" />
          </el-form-item>
          <el-form-item label="人工修正风险等级（可选）">
            <el-select v-model="manualLevel" placeholder="保持系统判别结果" clearable style="width: 100%">
              <el-option label="高风险" value="high" />
              <el-option label="低风险" value="low" />
              <el-option label="无风险" value="none" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="submitting" @click="confirmRisk">复核确认</el-button>
        <el-button :loading="submitting" @click="rerunRisk">重跑判别</el-button>
      </template>
      <PawLoading v-else variant="bubble" text="加载风险报告…" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Phone, Refresh, RefreshLeft, Search } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import StatusTag from '@/components/StatusTag.vue'
import { appointmentApi } from '@/api/appointment'
import { petApi } from '@/api/pet'
import { riskApi } from '@/api/risk'
import { useUserStore } from '@/stores/user'
import { ENGINE_LABEL, REASON_REQUIRED_STATUS, STATUS_ACTIONS } from '@/utils/dict'
import { genIdempotentKey, toDateStr } from '@/utils/format'
import type { Appointment, DictOption, Pet, RiskReport, SlotItem } from '@/types'

const route = useRoute()
const userStore = useUserStore()

const loading = ref(true)
const submitting = ref(false)
const list = ref<Appointment[]>([])
const total = ref(0)
const pets = ref<Pet[]>([])
const statusOptions = ref<DictOption[]>([])
const serviceOptions = ref<DictOption[]>([])
const staffSlots = ref<SlotItem[]>([])
const rescheduleSlots = ref<SlotItem[]>([])

const query = reactive({ page: 1, size: 10, status: '', appoint_date: '', keyword: '', mine: false })

const staffCreateVisible = ref(false)
const staffFormRef = ref<FormInstance>()
const staffForm = reactive({
  phone: '',
  pet_id: undefined as number | undefined,
  pet_name: '',
  service_type: 'basic_bath',
  appoint_date: toDateStr(new Date()),
  slot_time: '',
  remark: ''
})
const staffRules: FormRules = {
  phone: [
    { required: true, message: '请输入宠主手机号', trigger: 'blur' },
    { pattern: /^1\d{10}$/, message: '手机号需为 11 位数字', trigger: 'blur' }
  ],
  service_type: [{ required: true, message: '请选择服务类型', trigger: 'change' }],
  appoint_date: [{ required: true, message: '请选择日期', trigger: 'change' }],
  slot_time: [{ required: true, message: '请选择时段', trigger: 'change' }]
}

const rescheduleVisible = ref(false)
const current = ref<Appointment | null>(null)
const rescheduleForm = reactive({ appoint_date: '', slot_time: '', reason: '' })

const riskVisible = ref(false)
const riskReport = ref<RiskReport | null>(null)
const handleMeasure = ref('')
const manualLevel = ref('')

function actionsOf(row: Appointment) {
  return STATUS_ACTIONS[row.status] || []
}

function canReschedule(row: Appointment) {
  return ['pending', 'confirmed'].includes(row.status)
}

async function load() {
  loading.value = true
  try {
    const res = await appointmentApi.list({
      page: query.page,
      size: query.size,
      status: query.status || undefined,
      appoint_date: query.appoint_date || undefined,
      keyword: query.keyword || undefined,
      mine: query.mine
    })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function reload() {
  query.page = 1
  load()
}

function resetQuery() {
  query.status = ''
  query.appoint_date = ''
  query.keyword = ''
  query.mine = false
  reload()
}

async function changeStatus(row: Appointment, action: { status: string; label: string }) {
  let reason: string | undefined

  if (REASON_REQUIRED_STATUS.includes(action.status)) {
    try {
      const res = await ElMessageBox.prompt(`请填写「${action.label}」的原因（必填）`, '操作确认', {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        inputPlaceholder: '如：宠主行程变更 / 宠物强烈应激',
        inputValidator: (v: string) => (v && v.trim() ? true : '原因不能为空')
      })
      reason = res.value
    } catch {
      return
    }
  } else {
    try {
      await ElMessageBox.confirm(`确认将「${row.pet_name}」的预约变更为「${action.label}」吗？`, '操作确认', {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      })
    } catch {
      return
    }
  }

  await appointmentApi.changeStatus(row.id, { status: action.status, reason })
  ElMessage.success(`已更新为「${action.label}」`)
  load()
  userStore.refreshUnread()
}

async function openStaffCreate() {
  staffCreateVisible.value = true
  staffForm.phone = ''
  staffForm.pet_id = undefined
  staffForm.pet_name = ''
  staffForm.slot_time = ''
  staffForm.remark = ''
  staffForm.appoint_date = toDateStr(new Date())
  if (!pets.value.length) pets.value = await petApi.list()
  await loadStaffSlots()
}

async function loadStaffSlots() {
  if (!staffForm.appoint_date) return
  const res = await appointmentApi.slots(staffForm.appoint_date)
  staffSlots.value = res.slots
}

async function submitStaffCreate() {
  await staffFormRef.value?.validate()
  submitting.value = true
  try {
    const res = await appointmentApi.createByStaff({
      phone: staffForm.phone,
      pet_id: staffForm.pet_id ?? 0,
      pet_name: staffForm.pet_name || undefined,
      service_type: staffForm.service_type,
      appoint_date: staffForm.appoint_date,
      slot_time: staffForm.slot_time,
      remark: staffForm.remark || undefined,
      idempotent_key: genIdempotentKey('staff')
    })
    ElMessage.success(`代客预约已创建：${res.order_no}`)
    staffCreateVisible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

async function openReschedule(row: Appointment) {
  current.value = row
  rescheduleForm.appoint_date = row.appoint_date
  rescheduleForm.slot_time = row.slot_time
  rescheduleForm.reason = ''
  rescheduleVisible.value = true
  await loadRescheduleSlots()
}

async function loadRescheduleSlots() {
  if (!rescheduleForm.appoint_date) return
  const res = await appointmentApi.slots(rescheduleForm.appoint_date)
  rescheduleSlots.value = res.slots
}

async function submitReschedule() {
  if (!current.value) return
  if (!rescheduleForm.appoint_date || !rescheduleForm.slot_time) {
    ElMessage.warning('请选择新的日期与时段')
    return
  }
  submitting.value = true
  try {
    await appointmentApi.reschedule(current.value.id, { ...rescheduleForm })
    ElMessage.success('预约已改期')
    rescheduleVisible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

async function openRisk(row: Appointment) {
  riskVisible.value = true
  riskReport.value = null
  handleMeasure.value = ''
  manualLevel.value = ''
  try {
    riskReport.value = await riskApi.byAppointment(row.id)
  } catch {
    riskReport.value = null
  }
}

async function confirmRisk() {
  if (!riskReport.value) return
  submitting.value = true
  try {
    await riskApi.confirm(riskReport.value.appointment_id, {
      handle_measure: handleMeasure.value || undefined,
      manual_level: manualLevel.value || undefined
    })
    ElMessage.success('风险报告已复核')
    riskVisible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

async function rerunRisk() {
  if (!riskReport.value) return
  submitting.value = true
  try {
    riskReport.value = await riskApi.rerun(riskReport.value.appointment_id)
    ElMessage.success('风险判别已重跑')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const [opts, petList] = await Promise.all([
    appointmentApi.options().catch(() => ({ services: [], statuses: [] })),
    petApi.list().catch(() => [])
  ])
  statusOptions.value = opts.statuses as DictOption[]
  serviceOptions.value = opts.services as DictOption[]
  pets.value = petList as Pet[]
  await load()
  if (route.query.create === '1') openStaffCreate()
})
</script>

<style scoped>
.cell-pet {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-text {
  font-size: var(--pp-fs-sm);
  line-height: 1.8;
  color: var(--pp-text-regular);
  white-space: pre-wrap;
  background: var(--pp-bg-sunken);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  margin: 0;
}
</style>
