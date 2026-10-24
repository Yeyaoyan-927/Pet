<!--
  洗护记录（店员/店长）：按时间/店员/宠物筛选记录，补录服务细节与照片。
  数据来源：GET /wash/records。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">洗护记录</h2>
        <p class="pp-page-desc">
          预约完成后系统会自动生成洗护记录，店员可以补录皮肤毛发状况、使用产品与护理备注，形成完整的洗护档案。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="pp-mb-4">
      <el-col :xs="12" :sm="8"><StatCard label="洗护记录总数" :value="stats.total" icon="Sunny" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8"><StatCard label="本月完成" :value="stats.this_month" icon="Calendar" tone="success" /></el-col>
      <el-col :xs="12" :sm="8">
        <StatCard label="平均洗护时长" :value="stats.avg_minutes" suffix="分钟" icon="Timer" tone="warning" />
      </el-col>
    </el-row>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="洗护日期">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD"
                          range-separator="至" start-placeholder="开始" end-placeholder="结束"
                          style="width: 260px" @change="reload" />
        </el-form-item>
        <el-form-item v-if="userStore.isStaff" label="归属">
          <el-checkbox v-model="mine" @change="reload">仅看我经手的</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
          <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="bubble" text="加载洗护记录…" />
      <EmptyState v-else-if="!list.length" illustration="dog" title="还没有洗护记录" description="完成一次洗护后就会自动生成记录。" />

      <div v-else class="record-list">
        <article v-for="item in list" :key="item.id" class="record-item">
          <PetAvatar :species="item.pet_species || 'dog'" :size="46" />

          <div class="record-item__main">
            <div class="record-item__head">
              <span class="record-item__pet">{{ item.pet_name }}</span>
              <el-tag size="small" effect="light">{{ item.service_type_label }}</el-tag>
              <span class="record-item__duration">
                <el-icon :size="12"><Timer /></el-icon>
                {{ formatDuration(item.wash_start, item.wash_end) }}
              </span>
            </div>
            <div class="record-item__meta">
              <span>{{ item.appoint_date }} {{ item.slot_time }}</span>
              <span>单号 {{ item.order_no }}</span>
              <span>宠主 {{ item.owner_name || '-' }}</span>
            </div>
            <div class="record-item__detail">
              <span v-if="item.skin_condition"><b>皮肤</b>{{ item.skin_condition }}</span>
              <span v-if="item.hair_condition"><b>毛发</b>{{ item.hair_condition }}</span>
              <span v-if="item.products"><b>产品</b>{{ item.products }}</span>
            </div>
          </div>

          <div class="record-item__actions">
            <el-button v-if="canEdit(item)" size="small" @click="openEdit(item)">补录</el-button>
            <el-button size="small" type="primary" plain @click="openDetail(item)">详情</el-button>
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

    <!-- 补录 -->
    <el-dialog v-model="editVisible" title="补录洗护记录" width="560px" align-center>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="pp-mb-4"
        title="记录越完整，下一次洗护的风险判别就越准确。"
      />
      <el-form :model="editForm" label-width="104px">
        <el-form-item label="皮肤状况">
          <el-input v-model="editForm.skin_condition" type="textarea" :rows="2" maxlength="500"
                    placeholder="如：洗后皮肤无泛红，耳道清洁" />
        </el-form-item>
        <el-form-item label="毛发状况">
          <el-input v-model="editForm.hair_condition" type="textarea" :rows="2" maxlength="500"
                    placeholder="如：毛发蓬松顺滑，尾部有轻微打结已处理" />
        </el-form-item>
        <el-form-item label="使用产品">
          <el-input v-model="editForm.products" maxlength="255" placeholder="如：低敏沐浴露 + 护毛素" />
        </el-form-item>
        <el-form-item label="店员记录">
          <el-input v-model="editForm.staff_note" type="textarea" :rows="3" maxlength="500"
                    placeholder="记录宠物配合度、应激表现、特殊处置等" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存记录</el-button>
      </template>
    </el-dialog>

    <!-- 详情 -->
    <el-drawer v-model="detailVisible" title="洗护记录详情" size="520px">
      <template v-if="current">
        <div class="detail-head">
          <PetAvatar :species="current.pet_species || 'dog'" :size="52" />
          <div>
            <div class="detail-head__name">{{ current.pet_name }}</div>
            <div class="detail-head__sub">{{ current.service_type_label }} · {{ current.order_no }}</div>
          </div>
        </div>
        <el-descriptions :column="1" border class="pp-mt-4">
          <el-descriptions-item label="到店时间">{{ current.appoint_date }} {{ current.slot_time }}</el-descriptions-item>
          <el-descriptions-item label="洗护开始">{{ formatDateTime(current.wash_start) }}</el-descriptions-item>
          <el-descriptions-item label="洗护结束">{{ formatDateTime(current.wash_end) }}</el-descriptions-item>
          <el-descriptions-item label="洗护时长">{{ formatDuration(current.wash_start, current.wash_end) }}</el-descriptions-item>
          <el-descriptions-item label="宠主">{{ current.owner_name || '-' }}（{{ current.owner_phone || '-' }}）</el-descriptions-item>
          <el-descriptions-item label="皮肤状况">{{ current.skin_condition || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="毛发状况">{{ current.hair_condition || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="使用产品">{{ current.products || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="店员记录">{{ current.staff_note || '未记录' }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, RefreshLeft, Search, Timer } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import StatCard from '@/components/StatCard.vue'
import { washApi } from '@/api/wash'
import { useUserStore } from '@/stores/user'
import { formatDateTime, formatDuration } from '@/utils/format'
import type { WashRecord, WashStats } from '@/types'

const userStore = useUserStore()

const loading = ref(true)
const saving = ref(false)
const list = ref<WashRecord[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const mine = ref(false)
const dateRange = ref<[string, string] | null>(null)
const stats = reactive<WashStats>({ total: 0, this_month: 0, avg_minutes: 0, service_distribution: [] })

const editVisible = ref(false)
const current = ref<WashRecord | null>(null)
const detailVisible = ref(false)
const editForm = reactive({
  skin_condition: '',
  hair_condition: '',
  products: '',
  staff_note: ''
})

function canEdit(item: WashRecord) {
  if (userStore.isCustomer) return false
  return userStore.isManager || item.staff_id === userStore.userInfo?.id || item.staff_id === null
}

async function load() {
  loading.value = true
  try {
    const [res, statsRes] = await Promise.all([
      washApi.list({
        page: page.value,
        size: size.value,
        start: dateRange.value?.[0],
        end: dateRange.value?.[1],
        mine: mine.value
      }),
      washApi.stats()
    ])
    list.value = res.items
    total.value = res.total
    Object.assign(stats, statsRes)
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function reset() {
  dateRange.value = null
  mine.value = false
  reload()
}

function openEdit(item: WashRecord) {
  current.value = item
  editForm.skin_condition = item.skin_condition || ''
  editForm.hair_condition = item.hair_condition || ''
  editForm.products = item.products || ''
  editForm.staff_note = item.staff_note || ''
  editVisible.value = true
}

function openDetail(item: WashRecord) {
  current.value = item
  detailVisible.value = true
}

async function save() {
  if (!current.value) return
  saving.value = true
  try {
    await washApi.update(current.value.id, { ...editForm })
    ElMessage.success('洗护记录已保存')
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.record-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.record-item {
  display: flex;
  align-items: flex-start;
  gap: var(--pp-space-3);
  padding: var(--pp-space-4);
  border-radius: var(--pp-radius-lg);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  transition: all var(--pp-dur) var(--pp-ease);
}

.record-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--pp-shadow-md);
  border-color: var(--pp-primary-light);
}

.record-item__main {
  flex: 1;
  min-width: 0;
}

.record-item__head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.record-item__pet {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.record-item__duration {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-primary-dark);
  background: var(--pp-primary-lighter);
  padding: 3px 10px;
  border-radius: var(--pp-radius-pill);
  font-family: var(--pp-font-num);
}

.record-item__meta {
  display: flex;
  gap: var(--pp-space-4);
  flex-wrap: wrap;
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
}

.record-item__detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: var(--pp-space-3);
  padding: var(--pp-space-2) var(--pp-space-3);
  border-radius: var(--pp-radius-sm);
  background: var(--pp-bg-sunken);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.7;
}

.record-item__detail b {
  display: inline-block;
  min-width: 32px;
  margin-right: 6px;
  color: var(--pp-text-secondary);
  font-weight: var(--pp-fw-normal);
}

.record-item__actions {
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
  font-size: var(--pp-fs-lg);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.detail-head__sub {
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
  margin-top: 2px;
}
</style>
