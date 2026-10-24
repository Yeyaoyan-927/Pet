<!--
  风险复核（店员/店长）：待复核风险列表、详情与知识依据，确认后记录复核人与结论。
  数据来源：GET /risks、POST /risks/{id}/confirm。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">风险复核</h2>
        <p class="pp-page-desc">
          规则引擎初筛 + AI 增强仅作安全辅助提示，最终处置由店员现场复核确认。AI 不会执行任何写操作。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="pp-mb-4">
      <el-col :xs="12" :sm="6"><StatCard label="风险报告总数" :value="stats.total" icon="Document" tone="primary" /></el-col>
      <el-col :xs="12" :sm="6"><StatCard label="待复核" :value="stats.pending" icon="Clock" tone="warning" /></el-col>
      <el-col :xs="12" :sm="6"><StatCard label="高风险" :value="stats.high" icon="WarnTriangleFilled" tone="danger" /></el-col>
      <el-col :xs="12" :sm="6"><StatCard label="已复核" :value="stats.confirmed" icon="CircleCheck" tone="success" /></el-col>
    </el-row>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="复核状态">
          <el-radio-group v-model="onlyUnconfirmed" @change="reload">
            <el-radio-button :value="false">全部</el-radio-button>
            <el-radio-button :value="true">待复核</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="加载风险报告…" />
      <EmptyState v-else-if="!list.length" illustration="paw" title="没有需要复核的风险报告" description="所有预约的风险都已确认完成 🐾" />

      <div v-else class="risk-grid">
        <article
          v-for="item in list"
          :key="item.id"
          class="risk-card"
          :class="`risk-card--${item.risk_level}`"
          @click="open(item)"
        >
          <div class="risk-card__head">
            <span class="risk-card__pet">{{ item.pet_name }}</span>
            <el-tag size="small" :type="item.confirmed ? 'success' : 'warning'" effect="light">
              {{ item.confirmed ? '已复核' : '待复核' }}
            </el-tag>
          </div>
          <div class="risk-card__order">{{ item.order_no }}</div>
          <div class="risk-card__meta">
            <RiskBadge :level="item.risk_level" />
            <el-tag size="small" type="info" effect="light">{{ ENGINE_LABEL[item.engine_type] || item.engine_type }}</el-tag>
            <span class="risk-card__count">命中 {{ item.risk_items.length }} 项</span>
          </div>
          <p class="risk-card__advice">{{ item.suggestion || '暂无处置建议' }}</p>
          <div class="risk-card__foot">
            <span>{{ item.appoint_date }} {{ item.slot_time }}</span>
            <el-button link type="primary">查看详情</el-button>
          </div>
        </article>
      </div>

      <div v-if="total > size" class="pp-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="load"
          @current-change="load"
        />
      </div>
    </section>

    <!-- 复核抽屉 -->
    <el-drawer v-model="visible" title="风险报告复核" size="560px">
      <template v-if="current">
        <div class="detail-head">
          <PetAvatar species="dog" :size="46" />
          <div>
            <div class="detail-head__name">{{ current.pet_name }}</div>
            <div class="detail-head__order">{{ current.order_no }}</div>
          </div>
          <RiskBadge :level="current.risk_level" />
        </div>

        <div class="pp-card-title pp-mt-5">命中风险项</div>
        <el-table :data="current.risk_items" size="small" empty-text="未命中风险规则">
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
        <p class="summary-text">{{ current.ai_summary }}</p>

        <div class="pp-card-title pp-mt-5">店员复核</div>
        <el-form label-position="top">
          <el-form-item label="处置措施">
            <el-input v-model="handleMeasure" type="textarea" :rows="3" maxlength="500"
                      :disabled="!!current.confirmed" placeholder="记录本次实际采取的防护与处置措施" />
          </el-form-item>
          <el-form-item label="人工修正风险等级（可选）">
            <el-select v-model="manualLevel" placeholder="保持系统判别结果" clearable
                       :disabled="!!current.confirmed" style="width: 100%">
              <el-option label="高风险" value="high" />
              <el-option label="低风险" value="low" />
              <el-option label="无风险" value="none" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-button v-if="!current.confirmed" type="primary" :loading="submitting" @click="confirm">复核确认</el-button>
        <el-button :loading="submitting" @click="rerun">重跑判别</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import StatCard from '@/components/StatCard.vue'
import { riskApi } from '@/api/risk'
import { ENGINE_LABEL } from '@/utils/dict'
import type { RiskReport } from '@/types'

const loading = ref(true)
const submitting = ref(false)
const list = ref<RiskReport[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(9)
const onlyUnconfirmed = ref(false)
const stats = reactive({ total: 0, pending: 0, high: 0, confirmed: 0 })

const visible = ref(false)
const current = ref<RiskReport | null>(null)
const handleMeasure = ref('')
const manualLevel = ref('')

async function load() {
  loading.value = true
  try {
    const [res, all, pending] = await Promise.all([
      riskApi.list({ page: page.value, size: size.value, only_unconfirmed: onlyUnconfirmed.value }),
      riskApi.list({ page: 1, size: 100 }),
      riskApi.list({ page: 1, size: 100, only_unconfirmed: true })
    ])
    list.value = res.items
    total.value = res.total
    stats.total = all.total
    stats.pending = pending.total
    stats.high = all.items.filter((r) => r.risk_level === 'high').length
    stats.confirmed = all.items.filter((r) => r.confirmed).length
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function open(row: RiskReport) {
  current.value = row
  handleMeasure.value = row.handle_measure || ''
  manualLevel.value = ''
  visible.value = true
}

async function confirm() {
  if (!current.value) return
  submitting.value = true
  try {
    await riskApi.confirm(current.value.appointment_id, {
      handle_measure: handleMeasure.value || undefined,
      manual_level: manualLevel.value || undefined
    })
    ElMessage.success('风险报告已复核')
    visible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

async function rerun() {
  if (!current.value) return
  submitting.value = true
  try {
    current.value = await riskApi.rerun(current.value.appointment_id)
    ElMessage.success('风险判别已重跑')
    load()
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.risk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--pp-space-4);
}

.risk-card {
  position: relative;
  padding: var(--pp-space-4);
  border-radius: var(--pp-radius-lg);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur) var(--pp-ease);
  overflow: hidden;
}

.risk-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}

.risk-card--high::before {
  background: var(--pp-danger);
}
.risk-card--low::before {
  background: var(--pp-warning);
}
.risk-card--none::before {
  background: var(--pp-success);
}

.risk-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--pp-shadow-md);
}

.risk-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
}

.risk-card__pet {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.risk-card__order {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
  margin-top: 2px;
}

.risk-card__meta {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
  margin: var(--pp-space-3) 0;
}

.risk-card__count {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.risk-card__advice {
  margin: 0;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 68px;
}

.risk-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--pp-space-3);
  padding-top: var(--pp-space-3);
  border-top: 1px dashed var(--pp-border-light);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
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
