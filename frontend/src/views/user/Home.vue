<!--
  宠主首页：欢迎区（含 AI 入口卡）、快捷入口、指标行、我的毛孩子、最近预约。
  数据来源：GET /pets、/appointments、/messages/unread。
-->

<template>
  <div class="pp-page">
    <!-- 欢迎区 -->
    <section class="welcome pp-gradient-soft">
      <span class="pp-blob pp-blob--blue" style="width: 220px; height: 220px; right: 40px; top: -70px" />
      <div class="welcome__text">
        <h2 class="welcome__title">{{ greeting }}，{{ userStore.displayName }} 🐾</h2>
        <p class="welcome__desc">
          今天{{ overview.today_total ? `有 ${overview.today_total} 条预约安排` : '还没有预约安排' }}，
          {{ overview.today_finished ? `已经完成 ${overview.today_finished} 次洗护` : '随时可以为毛孩子安排一次香喷喷的洗护' }}。
        </p>
        <div class="welcome__actions">
          <el-button type="primary" :icon="Calendar" @click="router.push('/user/appointment/create')">
            发起预约
          </el-button>
          <el-button :icon="MagicStick" @click="router.push('/user/chat')">问问 AI 助手</el-button>
        </div>
      </div>
      <AgentEntry to="/user/chat" title="AI 洗护助手" desc="问时段、看档案、直接约" />
    </section>

    <!-- 快捷入口 -->
    <div class="pp-grid pp-mt-5">
      <div
        v-for="entry in quickEntries"
        :key="entry.path"
        class="quick pp-card pp-card--hover"
        @click="router.push(entry.path)"
      >
        <div class="quick__icon" :style="{ background: entry.bg, color: entry.color }">
          <el-icon :size="20"><component :is="entry.icon" /></el-icon>
        </div>
        <div class="quick__body">
          <div class="quick__title">{{ entry.title }}</div>
          <div class="quick__desc">{{ entry.desc }}</div>
        </div>
        <el-icon class="quick__arrow" :size="14"><ArrowRight /></el-icon>
      </div>
    </div>

    <!-- 指标 -->
    <el-row :gutter="16" class="pp-mt-5">
      <el-col :xs="12" :sm="8" :md="6"><StatCard label="今日预约" :value="overview.today_total" icon="Calendar" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8" :md="6"><StatCard label="待确认" :value="overview.today_pending" icon="Clock" tone="warning" /></el-col>
      <el-col :xs="12" :sm="8" :md="6"><StatCard label="今日完成" :value="overview.today_finished" icon="CircleCheck" tone="success" /></el-col>
      <el-col :xs="12" :sm="8" :md="6"><StatCard label="未读消息" :value="userStore.unread" icon="Bell" tone="ai" /></el-col>
    </el-row>

    <!-- 我的毛孩子 -->
    <section class="pp-card pp-mt-5">
      <div class="pp-card-title">
        我的毛孩子
        <span class="pp-card-extra">
          <el-button link type="primary" @click="router.push('/user/pets')">管理档案</el-button>
        </span>
      </div>

      <PawLoading v-if="loading" variant="paw" text="正在叫醒毛孩子…" />
      <EmptyState
        v-else-if="!pets.length"
        illustration="paw"
        title="还没有毛孩子档案"
        description="先为它建一个温暖的小窝吧，之后就能一键预约洗护啦。"
      >
        <el-button type="primary" :icon="Plus" @click="router.push('/user/pets/edit')">新建宠物档案</el-button>
      </EmptyState>

      <div v-else class="pp-grid">
        <div
          v-for="pet in pets"
          :key="pet.id"
          class="pet-card"
          @click="router.push(`/user/pets/edit/${pet.id}`)"
        >
          <PetAvatar :species="pet.species" :size="52" />
          <div class="pet-card__body">
            <div class="pet-card__name">{{ pet.name }}</div>
            <div class="pet-card__meta">
              {{ SPECIES_LABEL[pet.species] }} · {{ pet.breed || '未知品种' }} · {{ formatAge(pet.age_month) }}
            </div>
            <div class="pet-card__tags">
              <el-tag size="small" :type="pet.sterilized ? 'success' : 'info'" effect="light">
                {{ pet.sterilized ? '已绝育' : '未绝育' }}
              </el-tag>
              <el-tag v-if="pet.stress_level >= 2" size="small" type="warning" effect="light">
                应激{{ STRESS_LABEL[pet.stress_level] }}
              </el-tag>
              <el-tag v-if="pet.aggressive" size="small" type="danger" effect="light">有攻击倾向</el-tag>
              <el-tag v-if="pet.allergy" size="small" type="warning" effect="light">过敏史</el-tag>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 最近预约 -->
    <section class="pp-card pp-mt-4">
      <div class="pp-card-title">
        最近预约
        <span class="pp-card-extra">
          <el-button link type="primary" @click="router.push('/user/appointments')">查看全部</el-button>
        </span>
      </div>

      <PawLoading v-if="loading" variant="bubble" text="加载中…" />
      <EmptyState
        v-else-if="!recent.length"
        illustration="cat"
        title="今天还没有预约"
        description="要不要给毛孩子安排一次香喷喷的洗护？"
      >
        <el-button type="primary" @click="router.push('/user/appointment/create')">去预约</el-button>
      </EmptyState>

      <div v-else class="recent-list">
        <div v-for="item in recent" :key="item.id" class="recent-item">
          <PetAvatar :species="petSpecies(item.pet_id)" :size="40" />
          <div class="recent-item__main">
            <div class="recent-item__title">
              {{ item.pet_name }} · {{ item.service_type_label }}
              <RiskBadge :level="item.risk_level" />
            </div>
            <div class="recent-item__meta">
              {{ item.appoint_date }} {{ item.slot_time }} · 单号 {{ item.order_no }}
            </div>
          </div>
          <StatusTag :status="item.status" :label="item.status_label" />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Calendar, MagicStick, Plus } from '@element-plus/icons-vue'
import AgentEntry from '@/components/AgentEntry.vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import StatCard from '@/components/StatCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { appointmentApi } from '@/api/appointment'
import { petApi } from '@/api/pet'
import { useUserStore } from '@/stores/user'
import { SPECIES_LABEL, STRESS_LABEL } from '@/utils/dict'
import { formatAge } from '@/utils/format'
import type { Appointment, OverviewStats, Pet } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const pets = ref<Pet[]>([])
const recent = ref<Appointment[]>([])
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

const quickEntries = [
  { title: '创建预约', desc: '挑个合适的时间给毛孩子洗澡', path: '/user/appointment/create', icon: 'Calendar', bg: 'var(--pp-primary-lighter)', color: 'var(--pp-primary-dark)' },
  { title: '我的宠物', desc: '完善档案，让洗护更安心', path: '/user/pets', icon: 'Star', bg: 'var(--pp-warning-bg)', color: '#c47c2b' },
  { title: '我的预约', desc: '查看每一笔预约的进度', path: '/user/appointments', icon: 'Tickets', bg: 'var(--pp-success-bg)', color: '#4e8a4d' },
  { title: 'AI 助手', desc: '问时段、看档案、直接约', path: '/user/chat', icon: 'MagicStick', bg: 'var(--pp-ai-bg)', color: '#7361a4' }
]

function petSpecies(petId: number): string {
  return pets.value.find((p) => p.id === petId)?.species || 'dog'
}

async function load() {
  loading.value = true
  try {
    const [petList, apptList, ov] = await Promise.all([
      petApi.list(),
      appointmentApi.list({ page: 1, size: 5 }),
      appointmentApi.overview()
    ])
    pets.value = petList
    recent.value = apptList.items
    Object.assign(overview, ov)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* ---------------- 欢迎区 ---------------- */
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
  max-width: 560px;
}

.welcome__actions {
  display: flex;
  gap: var(--pp-space-2);
}

/* ---------------- 快捷入口 ---------------- */
.quick {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  cursor: pointer;
}

.quick__icon {
  width: 44px;
  height: 44px;
  border-radius: var(--pp-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.quick__body {
  flex: 1;
  min-width: 0;
}

.quick__title {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.quick__desc {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  margin-top: 2px;
}

.quick__arrow {
  color: var(--pp-text-placeholder);
}

/* ---------------- 宠物卡 ---------------- */
.pet-card {
  display: flex;
  gap: var(--pp-space-3);
  padding: var(--pp-space-4);
  border-radius: var(--pp-radius-lg);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur) var(--pp-ease);
}

.pet-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--pp-shadow-md);
  border-color: var(--pp-primary-light);
}

.pet-card__body {
  min-width: 0;
}

.pet-card__name {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.pet-card__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  margin: 2px 0 var(--pp-space-2);
}

.pet-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ---------------- 最近预约 ---------------- */
.recent-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.recent-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  padding: var(--pp-space-3) var(--pp-space-4);
  border-radius: var(--pp-radius-md);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-sunken);
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.recent-item:hover {
  background: var(--pp-primary-lighter);
  border-color: transparent;
}

.recent-item__main {
  flex: 1;
  min-width: 0;
}

.recent-item__title {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.recent-item__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
  margin-top: 2px;
}
</style>
