<!--
  门店看板（店员/店长）：今日预约时间轴、待确认/待复核待办、近 7 日预约量折线。
  数据来源：GET /appointments、/report/summary；待办可一键跳到对应处理页。
-->

<template>
  <div class="pp-page">
    <section class="welcome pp-gradient-soft">
      <span class="pp-blob pp-blob--blue" style="width: 220px; height: 220px; right: 60px; top: -80px" />
      <div class="welcome__text">
        <h2 class="welcome__title">{{ greeting }}，{{ userStore.displayName }} 🐾</h2>
        <p class="welcome__desc">
          今天共有 <b>{{ overview.today_total }}</b> 条预约，
          其中 <b>{{ overview.today_pending }}</b> 条待确认、<b>{{ pendingRisks }}</b> 份风险报告待复核。
        </p>
        <div class="welcome__actions">
          <el-button type="primary" :icon="Calendar" @click="router.push('/staff/appointments')">处理预约</el-button>
          <el-button :icon="WarnTriangleFilled" @click="router.push('/staff/risk')">风险复核</el-button>
          <el-button :icon="Phone" @click="openStaffCreate">代客预约</el-button>
        </div>
      </div>
      <AgentEntry :to="agentEntry.to" :title="agentEntry.title" :desc="agentEntry.desc" />
    </section>

    <el-row :gutter="16" class="pp-mt-5">
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="今日预约" :value="overview.today_total" icon="Calendar" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待确认" :value="overview.today_pending" icon="Clock" tone="warning" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="已确认" :value="overview.today_confirmed" icon="CircleCheck" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="已到店" :value="overview.today_arrived" icon="Location" tone="default" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="今日完成" :value="overview.today_finished" icon="Sunny" tone="success" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待复核风险" :value="pendingRisks" icon="WarnTriangleFilled" tone="danger" /></el-col>
    </el-row>

    <el-row :gutter="16" class="pp-mt-5">
      <el-col :xs="24" :lg="14">
        <section class="pp-card">
          <div class="pp-card-title">
            今日预约
            <span class="pp-card-extra">
              <el-button link type="primary" @click="router.push('/staff/appointments')">全部预约</el-button>
            </span>
          </div>

          <PawLoading v-if="loading" variant="paw" text="加载今日排期…" />
          <EmptyState
            v-else-if="!todayList.length"
            illustration="cat"
            title="今天还没有预约安排"
            description="可以帮到店的宠主做一次代客预约。"
          >
            <el-button type="primary" @click="openStaffCreate">代客预约</el-button>
          </EmptyState>

          <div v-else class="today-list">
            <div v-for="item in todayList" :key="item.id" class="today-item">
              <div class="today-item__time">{{ item.slot_time }}</div>
              <PetAvatar :species="'dog'" :size="40" />
              <div class="today-item__main">
                <div class="today-item__title">
                  {{ item.pet_name }} · {{ item.service_type_label }}
                  <RiskBadge :level="item.risk_level" />
                </div>
                <div class="today-item__meta">{{ item.owner_name }} · {{ item.owner_phone || '未留电话' }}</div>
              </div>
              <StatusTag :status="item.status" :label="item.status_label" />
            </div>
          </div>
        </section>
      </el-col>

      <el-col :xs="24" :lg="10">
        <section class="pp-card">
          <div class="pp-card-title">待办提醒</div>
          <el-alert
            v-if="overview.today_pending > 0"
            type="warning"
            :closable="false"
            show-icon
            :title="`${overview.today_pending} 条预约待确认`"
            description="超过门店配置的确认时限会触发升级提醒，并按配置自动取消。"
            class="pp-mb-4"
          />
          <el-alert
            v-if="pendingRisks > 0"
            type="error"
            :closable="false"
            show-icon
            :title="`${pendingRisks} 份风险报告待复核`"
            description="风险判别仅作辅助提示，需店员现场复核后方可执行洗护。"
            class="pp-mb-4"
          />
          <EmptyState
            v-if="!overview.today_pending && !pendingRisks"
            illustration="paw"
            title="暂时没有待办事项"
            description="一切都在顺利运转，辛苦了 🐾"
            :size="72"
          />
        </section>

        <section class="pp-card">
          <div class="pp-card-title">近 7 日预约量</div>
          <BaseChart v-if="trend.length" :option="trendOption" height="220px" />
          <EmptyState v-else illustration="paw" title="暂无数据" :size="64" />
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Calendar, Phone, WarnTriangleFilled } from '@element-plus/icons-vue'
import BaseChart from '@/components/BaseChart.vue'
import AgentEntry from '@/components/AgentEntry.vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import StatCard from '@/components/StatCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { appointmentApi } from '@/api/appointment'
import { reportApi } from '@/api/report'
import { riskApi } from '@/api/risk'
import { useUserStore } from '@/stores/user'
import { toDateStr } from '@/utils/format'
import type { Appointment, OverviewStats } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const todayList = ref<Appointment[]>([])
const pendingRisks = ref(0)
const trend = ref<{ label: string; value: number }[]>([])
const overview = reactive<OverviewStats>({
  today_total: 0,
  today_pending: 0,
  today_confirmed: 0,
  today_arrived: 0,
  today_finished: 0,
  week_total: 0
})

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

/** 右侧 Agent 入口：店员进「运营助理」、店长进「经营助理」，
 *  同一页面同一内核，实际的工具画像由后端按角色下发。 */
const agentEntry = computed(() =>
  userStore.role === 'manager'
    ? { to: '/staff/chat', title: '经营助理', desc: '经营数据、流失预警、门店配置' }
    : { to: '/staff/chat', title: '运营助理', desc: '今日待办、客户档案、代客预约' }
)

const trendOption = computed<EChartsOption>(() => ({
  color: ['#5B9BD5'],
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 16, top: 20, bottom: 28 },
  xAxis: {
    type: 'category',
    data: trend.value.map((i) => i.label),
    axisLabel: { color: '#9C948B', fontSize: 12 },
    axisLine: { lineStyle: { color: '#EDE6DB' } }
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLabel: { color: '#9C948B', fontSize: 12 },
    splitLine: { lineStyle: { color: '#F5EFE6' } }
  },
  series: [
    {
      type: 'line',
      smooth: true,
      symbolSize: 7,
      data: trend.value.map((i) => i.value),
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(91,155,213,.28)' },
            { offset: 1, color: 'rgba(91,155,213,.02)' }
          ]
        }
      },
      lineStyle: { width: 2.5 }
    }
  ]
}))

function openStaffCreate() {
  router.push({ path: '/staff/appointments', query: { create: '1' } })
}

async function load() {
  loading.value = true
  try {
    const today = toDateStr(new Date())
    const [ov, list, risks, summary] = await Promise.all([
      appointmentApi.overview(),
      appointmentApi.list({ page: 1, size: 8, appoint_date: today }),
      riskApi.list({ page: 1, size: 1, only_unconfirmed: true }),
      reportApi.summary({})
    ])
    Object.assign(overview, ov)
    todayList.value = list.items
    pendingRisks.value = risks.total
    trend.value = summary.daily_trend.slice(-7)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.welcome {
  position: relative;
  overflow: hidden;
  border-radius: var(--pp-radius-xl);
  padding: var(--pp-space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--pp-space-5);
  border: 1px solid var(--pp-border-light);
  box-shadow: var(--pp-shadow-sm);
}

.welcome__title {
  font-size: var(--pp-fs-xl);
  font-weight: var(--pp-fw-semibold);
}

.welcome__desc {
  margin: var(--pp-space-2) 0 var(--pp-space-4);
  font-size: var(--pp-fs-base);
  color: var(--pp-text-regular);
}

.welcome__desc b {
  color: var(--pp-primary-dark);
  font-family: var(--pp-font-num);
}

.welcome__actions {
  display: flex;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.today-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.today-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.today-item:hover {
  background: var(--pp-primary-lighter);
}

.today-item__time {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-primary-dark);
  width: 48px;
  flex: none;
}

.today-item__main {
  flex: 1;
  min-width: 0;
}

.today-item__title {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.today-item__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
  margin-top: 2px;
}
</style>
