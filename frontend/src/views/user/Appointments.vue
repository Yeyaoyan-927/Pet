<!--
  我的预约（宠主）：状态筛选、改期、取消、查看风险提示。
  数据来源：GET /appointments（后端自动收敛到本人）。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">我的预约</h2>
        <p class="pp-page-desc">可以在这里关注预约进度、查看洗护风险提示，或取消还没开始的预约。</p>
      </div>
      <div class="pp-page-actions">
        <el-button type="primary" :icon="Plus" @click="router.push('/user/appointment/create')">发起预约</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="订单状态">
          <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 160px" @change="reload">
            <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="到店日期">
          <el-date-picker v-model="query.appoint_date" type="date" value-format="YYYY-MM-DD"
                          placeholder="选择日期" clearable style="width: 170px" @change="reload" />
        </el-form-item>
        <el-form-item label="预约单号">
          <el-input v-model="query.keyword" placeholder="输入单号" clearable style="width: 180px" @keyup.enter="reload" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
          <el-button :icon="RefreshLeft" @click="resetQuery">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="加载预约中…" />
      <EmptyState
        v-else-if="!list.length"
        illustration="cat"
        title="今天还没有预约"
        description="要不要给毛孩子安排一次香喷喷的洗护？"
      >
        <el-button type="primary" @click="router.push('/user/appointment/create')">去预约</el-button>
      </EmptyState>

      <div v-else class="appt-list">
        <article v-for="item in list" :key="item.id" class="appt-item">
          <div class="appt-item__left">
            <PetAvatar :species="petSpecies(item)" :size="46" />
          </div>

          <div class="appt-item__main">
            <div class="appt-item__head">
              <span class="appt-item__pet">{{ item.pet_name }}</span>
              <span class="appt-item__service">{{ item.service_type_label }}</span>
              <StatusTag :status="item.status" :label="item.status_label" />
              <RiskBadge :level="item.risk_level" />
            </div>
            <div class="appt-item__meta">
              <span><el-icon :size="13"><Clock /></el-icon> {{ item.appoint_date }} {{ item.slot_time }}</span>
              <span><el-icon :size="13"><Tickets /></el-icon> {{ item.order_no }}</span>
              <span v-if="item.reschedule_times">改期 {{ item.reschedule_times }} 次</span>
            </div>
            <div v-if="item.cancel_reason || item.terminate_reason" class="appt-item__reason">
              {{ item.cancel_reason || item.terminate_reason }}
            </div>
          </div>

          <div class="appt-item__actions">
            <el-button size="small" @click="openDetail(item)">详情</el-button>
            <el-button v-if="canCancel(item)" size="small" type="danger" plain @click="cancel(item)">取消</el-button>
          </div>
        </article>
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

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" title="预约详情" size="520px">
      <template v-if="current">
        <div class="detail-head">
          <PetAvatar :species="petSpecies(current)" :size="52" />
          <div>
            <div class="detail-head__name">{{ current.pet_name }}</div>
            <div class="detail-head__order">{{ current.order_no }}</div>
          </div>
          <StatusTag :status="current.status" :label="current.status_label" />
        </div>

        <el-descriptions :column="1" border class="pp-mt-4">
          <el-descriptions-item label="洗护服务">{{ current.service_type_label }}</el-descriptions-item>
          <el-descriptions-item label="到店时间">{{ current.appoint_date }} {{ current.slot_time }}</el-descriptions-item>
          <el-descriptions-item label="风险等级">
            <RiskBadge :level="current.risk_level" />
          </el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatDateTime(current.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="门店确认">{{ formatDateTime(current.confirm_at) }}</el-descriptions-item>
          <el-descriptions-item label="到店时间">{{ formatDateTime(current.arrive_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatDateTime(current.finish_at) }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ current.remark || '-' }}</el-descriptions-item>
          <el-descriptions-item label="取消 / 终止原因">
            {{ current.cancel_reason || current.terminate_reason || '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="riskReport">
          <div class="pp-card-title pp-mt-5">洗护风险提示</div>
          <el-alert
            :type="riskReport.risk_level === 'high' ? 'error' : 'warning'"
            :closable="false"
            show-icon
            :title="riskReport.risk_level_label"
            :description="riskReport.suggestion || ''"
          />
          <div v-if="riskReport.risk_items.length" class="risk-list">
            <div v-for="ri in riskReport.risk_items" :key="ri.key" class="risk-list__item">
              <el-tag size="small" :type="ri.level === 'high' ? 'danger' : 'warning'" effect="light">
                {{ ri.level === 'high' ? '高风险' : '低风险' }}
              </el-tag>
              <span>{{ ri.desc }}</span>
            </div>
          </div>
          <p class="disclaimer">{{ riskReport.ai_summary }}</p>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, Plus, RefreshLeft, Search, Tickets } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import StatusTag from '@/components/StatusTag.vue'
import { appointmentApi } from '@/api/appointment'
import { petApi } from '@/api/pet'
import { riskApi } from '@/api/risk'
import { useUserStore } from '@/stores/user'
import { formatDateTime } from '@/utils/format'
import type { Appointment, DictOption, Pet, RiskReport } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const list = ref<Appointment[]>([])
const total = ref(0)
const pets = ref<Pet[]>([])
const statusOptions = ref<DictOption[]>([])

const query = reactive({ page: 1, size: 10, status: '', appoint_date: '', keyword: '' })

const detailVisible = ref(false)
const current = ref<Appointment | null>(null)
const riskReport = ref<RiskReport | null>(null)

function petSpecies(item: Appointment) {
  return pets.value.find((p) => p.id === item.pet_id)?.species || 'dog'
}

function canCancel(item: Appointment) {
  return ['pending', 'confirmed'].includes(item.status)
}

async function load() {
  loading.value = true
  try {
    const res = await appointmentApi.list({
      page: query.page,
      size: query.size,
      status: query.status || undefined,
      appoint_date: query.appoint_date || undefined,
      keyword: query.keyword || undefined
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
  reload()
}

async function openDetail(item: Appointment) {
  current.value = item
  riskReport.value = null
  detailVisible.value = true
  try {
    riskReport.value = await riskApi.byAppointment(item.id)
  } catch {
    riskReport.value = null
  }
}

async function cancel(item: Appointment) {
  let reason = ''
  try {
    const res = await ElMessageBox.prompt(
      '可以和门店说一下原因吗？这会帮我们更好地安排时段。',
      '取消预约',
      {
        confirmButtonText: '确认取消',
        cancelButtonText: '保留预约',
        inputPlaceholder: '如：临时有事，改天再约',
        inputValidator: (v: string) => (v && v.trim() ? true : '需要填写取消原因')
      }
    )
    reason = res.value
  } catch {
    return
  }
  await appointmentApi.changeStatus(item.id, { status: 'cancelled', reason })
  ElMessage.success('预约已取消，时段已释放给其他毛孩子')
  load()
  userStore.refreshUnread()
}

onMounted(async () => {
  const [opts, petList] = await Promise.all([
    appointmentApi.options().catch(() => ({ services: [], statuses: [] })),
    petApi.list().catch(() => [])
  ])
  statusOptions.value = opts.statuses as DictOption[]
  pets.value = petList as Pet[]
  await load()
})
</script>

<style scoped>
.appt-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.appt-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  padding: var(--pp-space-4);
  border-radius: var(--pp-radius-lg);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  transition: all var(--pp-dur) var(--pp-ease);
}

.appt-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--pp-shadow-md);
  border-color: var(--pp-primary-light);
}

.appt-item__main {
  flex: 1;
  min-width: 0;
}

.appt-item__head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.appt-item__pet {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.appt-item__service {
  font-size: var(--pp-fs-sm);
  color: var(--pp-primary-dark);
  background: var(--pp-primary-lighter);
  padding: 2px 10px;
  border-radius: var(--pp-radius-pill);
}

.appt-item__meta {
  display: flex;
  align-items: center;
  gap: var(--pp-space-4);
  flex-wrap: wrap;
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
}

.appt-item__meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.appt-item__reason {
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-danger);
  background: var(--pp-danger-bg);
  padding: 4px 10px;
  border-radius: var(--pp-radius-sm);
  display: inline-block;
}

.appt-item__actions {
  display: flex;
  gap: var(--pp-space-2);
  flex: none;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
}

.detail-head__name {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.detail-head__order {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
}

.detail-head > :last-child {
  margin-left: auto;
}

.risk-list {
  margin-top: var(--pp-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.risk-list__item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.disclaimer {
  margin-top: var(--pp-space-4);
  font-size: var(--pp-fs-xs);
  line-height: 1.8;
  color: var(--pp-text-placeholder);
  white-space: pre-wrap;
  background: var(--pp-bg-sunken);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
}
</style>
