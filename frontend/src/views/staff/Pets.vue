<!--
  客户档案（店员/店长）：按宠主/关键词检索档案，查看过敏史与历史订单。
  数据来源：GET /pets。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">客户档案</h2>
        <p class="pp-page-desc">
          店员与店长都可查看并维护全部客户档案，不按负责店员限制（现场轮流排班，谁在前台都能查改）。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button v-if="userStore.isManager" :icon="Download" @click="router.push('/report/export')">
          导出档案
        </el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="宠物名">
          <el-input v-model="keyword" placeholder="输入宠物名搜索" clearable style="width: 220px" @keyup.enter="load" />
        </el-form-item>
        <el-form-item label="只看风险档案">
          <el-switch v-model="onlyRisk" @change="applyFilter" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">查询</el-button>
          <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="加载客户档案…" />
      <EmptyState v-else-if="!filtered.length" illustration="paw" title="没有符合条件的档案" description="换个关键词试试吧。" />

      <div v-else class="pp-scroll-x">
        <el-table :data="filtered" style="width: 100%">
          <el-table-column prop="id" label="档案 ID" width="90" />
          <el-table-column label="宠物" min-width="160">
            <template #default="{ row }">
              <div class="cell-pet">
                <PetAvatar :species="row.species" :size="34" />
                <div>
                  <div class="cell-pet__name">{{ row.name }}</div>
                  <div class="cell-pet__sub">{{ SPECIES_LABEL[row.species] }} · {{ row.breed || '未知品种' }}</div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="月龄" width="120">
            <template #default="{ row }">{{ formatAge(row.age_month) }}</template>
          </el-table-column>
          <el-table-column label="体重" width="90">
            <template #default="{ row }">{{ row.weight ?? '-' }} kg</template>
          </el-table-column>
          <el-table-column label="风险档案" min-width="240">
            <template #default="{ row }">
              <div class="cell-tags">
                <el-tag v-if="row.aggressive" size="small" type="danger" effect="light">攻击倾向</el-tag>
                <el-tag v-if="row.allergy" size="small" type="warning" effect="light">过敏史</el-tag>
                <el-tag v-if="row.skin_disease" size="small" type="warning" effect="light">皮肤病</el-tag>
                <el-tag v-if="row.stress_level >= 2" size="small" type="warning" effect="light">应激偏高</el-tag>
                <span v-if="!hasRisk(row)" class="pp-dim">无</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
              <el-button link type="primary" @click="router.push(`/user/pets/edit/${row.id}`)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" title="宠物档案详情" size="540px">
      <template v-if="current">
        <div class="detail-head">
          <PetAvatar :species="current.species" :size="56" />
          <div>
            <div class="detail-head__name">{{ current.name }}</div>
            <div class="detail-head__sub">
              {{ SPECIES_LABEL[current.species] }} · {{ current.breed || '未知品种' }} ·
              {{ GENDER_LABEL[current.gender] }} · {{ formatAge(current.age_month) }}
            </div>
          </div>
        </div>

        <el-descriptions :column="1" border class="pp-mt-4">
          <el-descriptions-item label="体重">{{ current.weight ?? '-' }} kg</el-descriptions-item>
          <el-descriptions-item label="生日">{{ formatDate(current.birthday) }}</el-descriptions-item>
          <el-descriptions-item label="绝育">{{ current.sterilized ? '已绝育' : '未绝育' }}</el-descriptions-item>
          <el-descriptions-item label="应激等级">
            <el-tag size="small" :type="current.stress_level >= 2 ? 'warning' : 'info'" effect="light">
              {{ STRESS_LABEL[current.stress_level] }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="攻击倾向">{{ current.aggressive ? '有' : '无' }}</el-descriptions-item>
          <el-descriptions-item label="过敏史">{{ current.allergy || '无' }}</el-descriptions-item>
          <el-descriptions-item label="皮肤病史">{{ current.skin_disease || '无' }}</el-descriptions-item>
          <el-descriptions-item label="应急联系人">{{ current.emergency_contact || '-' }}</el-descriptions-item>
          <el-descriptions-item label="应急电话">
            <span class="pp-num">{{ current.emergency_phone || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="备注">{{ current.remark || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="pp-card-title pp-mt-5">
          疫苗驱虫记录
          <span class="pp-card-extra">
            <el-button link type="primary" @click="router.push(`/user/pets/edit/${current.id}`)">去维护</el-button>
          </span>
        </div>
        <PawLoading v-if="vaccineLoading" variant="tail" />
        <EmptyState v-else-if="!vaccines.length" illustration="cat" title="还没有记录" :size="64" />
        <el-table v-else :data="vaccines" size="small">
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ VACCINE_TYPE_LABEL[row.record_type] }}</template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="130" show-overflow-tooltip />
          <el-table-column prop="record_date" label="本次" width="110" />
          <el-table-column prop="next_date" label="下次" width="110" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Download, Refresh, RefreshLeft, Search } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import { petApi } from '@/api/pet'
import { useUserStore } from '@/stores/user'
import { GENDER_LABEL, SPECIES_LABEL, STRESS_LABEL, VACCINE_TYPE_LABEL } from '@/utils/dict'
import { formatAge, formatDate } from '@/utils/format'
import type { Pet, VaccineRecord } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const list = ref<Pet[]>([])
const keyword = ref('')
const onlyRisk = ref(false)

const detailVisible = ref(false)
const current = ref<Pet | null>(null)
const vaccines = ref<VaccineRecord[]>([])
const vaccineLoading = ref(false)

function hasRisk(pet: Pet) {
  return pet.aggressive || pet.allergy || pet.skin_disease || pet.stress_level >= 2
}

const filtered = computed(() =>
  onlyRisk.value ? list.value.filter(hasRisk) : list.value
)

function applyFilter() {
  /* 纯前端筛选，无需重新请求 */
}

async function load() {
  loading.value = true
  try {
    list.value = await petApi.list(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

function reset() {
  keyword.value = ''
  onlyRisk.value = false
  load()
}

async function openDetail(pet: Pet) {
  current.value = pet
  detailVisible.value = true
  vaccineLoading.value = true
  try {
    vaccines.value = await petApi.vaccines(pet.id)
  } finally {
    vaccineLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.cell-pet {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
}

.cell-pet__name {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.cell-pet__sub {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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
  margin-top: 2px;
}
</style>
