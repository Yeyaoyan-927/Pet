<!--
  我的宠物（宠主）：档案卡片网格，进编辑页维护档案与疫苗记录。
  数据来源：GET /pets。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">宠物档案</h2>
        <p class="pp-page-desc">
          完整的档案是洗护风险判别的基础。过敏史、皮肤病史、应激等级与攻击倾向会直接影响洗护方案。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button type="primary" :icon="Plus" @click="router.push('/user/pets/edit')">新增宠物</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="宠物名">
          <el-input v-model="keyword" placeholder="输入宠物名搜索" clearable style="width: 220px" @keyup.enter="load" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">查询</el-button>
          <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <PawLoading v-if="loading" variant="paw" text="正在加载毛孩子的档案…" />

    <EmptyState
      v-else-if="!list.length"
      illustration="paw"
      title="还没有毛孩子档案"
      description="先为它建一个温暖的小窝吧，之后就能一键预约洗护啦。"
    >
      <el-button type="primary" :icon="Plus" @click="router.push('/user/pets/edit')">新建宠物档案</el-button>
    </EmptyState>

    <div v-else class="pp-grid">
      <div v-for="pet in list" :key="pet.id" class="pet-card pp-card pp-card--hover">
        <div class="pet-card__head">
          <PetAvatar :species="pet.species" :size="56" />
          <div class="pet-card__title">
            <div class="pet-card__name">{{ pet.name }}</div>
            <div class="pet-card__breed">{{ SPECIES_LABEL[pet.species] }} · {{ pet.breed || '未知品种' }}</div>
          </div>
          <el-dropdown trigger="click" @command="(cmd: string) => onCommand(cmd, pet)">
            <el-icon class="pet-card__more"><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑档案</el-dropdown-item>
                <el-dropdown-item command="vaccine">疫苗驱虫记录</el-dropdown-item>
                <el-dropdown-item command="appointment">为它预约</el-dropdown-item>
                <el-dropdown-item divided command="remove">作废档案</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <dl class="pet-card__facts">
          <div><dt>月龄</dt><dd>{{ formatAge(pet.age_month) }}</dd></div>
          <div><dt>体重</dt><dd>{{ pet.weight ?? '-' }} kg</dd></div>
          <div><dt>性别</dt><dd>{{ GENDER_LABEL[pet.gender] }}</dd></div>
          <div><dt>生日</dt><dd>{{ formatDate(pet.birthday) }}</dd></div>
        </dl>

        <div class="pet-card__tags">
          <el-tag size="small" :type="pet.sterilized ? 'success' : 'info'" effect="light">
            {{ pet.sterilized ? '已绝育' : '未绝育' }}
          </el-tag>
          <el-tag size="small" :type="pet.stress_level >= 2 ? 'warning' : 'info'" effect="light">
            应激 {{ STRESS_LABEL[pet.stress_level] }}
          </el-tag>
          <el-tag size="small" :type="pet.aggressive ? 'danger' : 'info'" effect="light">
            {{ pet.aggressive ? '有攻击倾向' : '性格温和' }}
          </el-tag>
        </div>

        <div v-if="pet.allergy || pet.skin_disease" class="pet-card__warn">
          <el-icon :size="13"><WarnTriangleFilled /></el-icon>
          <span v-if="pet.allergy">过敏史：{{ pet.allergy }}</span>
          <span v-if="pet.skin_disease">皮肤病史：{{ pet.skin_disease }}</span>
        </div>

        <div class="pet-card__actions">
          <el-button size="small" @click="router.push(`/user/pets/edit/${pet.id}`)">编辑</el-button>
          <el-button size="small" :icon="FirstAidKit" @click="openVaccine(pet)">疫苗驱虫</el-button>
          <el-button size="small" type="primary" plain @click="router.push(`/user/appointment/create?pet=${pet.id}`)">
            发起预约
          </el-button>
        </div>
      </div>
    </div>

    <!-- 疫苗驱虫记录抽屉（与档案编辑页共用同一个组件） -->
    <VaccineDrawer v-model="vaccineVisible" :pet-id="current?.id ?? null" :pet-name="current?.name" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FirstAidKit, MoreFilled, Plus, RefreshLeft, Search, WarnTriangleFilled } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import VaccineDrawer from '@/components/VaccineDrawer.vue'
import { petApi } from '@/api/pet'
import { GENDER_LABEL, SPECIES_LABEL, STRESS_LABEL } from '@/utils/dict'
import { formatAge, formatDate } from '@/utils/format'
import type { Pet } from '@/types'

const router = useRouter()
const route = useRoute()

const loading = ref(true)
const keyword = ref('')
const list = ref<Pet[]>([])

const vaccineVisible = ref(false)
const current = ref<Pet | null>(null)

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
  load()
}

function onCommand(cmd: string, pet: Pet) {
  if (cmd === 'edit') router.push(`/user/pets/edit/${pet.id}`)
  else if (cmd === 'appointment') router.push(`/user/appointment/create?pet=${pet.id}`)
  else if (cmd === 'vaccine') openVaccine(pet)
  else if (cmd === 'remove') remove(pet)
}

function openVaccine(pet: Pet) {
  current.value = pet
  vaccineVisible.value = true
}

async function remove(pet: Pet) {
  try {
    await ElMessageBox.confirm(
      `确认作废「${pet.name}」的档案吗？作废后历史预约仍会保留。`,
      '作废确认',
      { confirmButtonText: '作废', cancelButtonText: '再想想', type: 'warning' }
    )
  } catch {
    return
  }
  await petApi.remove(pet.id)
  ElMessage.success('档案已作废')
  load()
}

onMounted(async () => {
  await load()
  // 从寄养下单页「去登记疫苗」跳过来时，直接打开对应宠物的疫苗抽屉
  const petId = Number(route.query.vaccine || 0)
  if (petId) {
    const target = list.value.find((p) => p.id === petId)
    if (target) openVaccine(target)
  }
})
</script>

<style scoped>
.pet-card {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.pet-card__head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
}

.pet-card__title {
  flex: 1;
  min-width: 0;
}

.pet-card__name {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.pet-card__breed {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  margin-top: 2px;
}

.pet-card__more {
  color: var(--pp-text-placeholder);
  cursor: pointer;
}

.pet-card__facts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--pp-space-2) var(--pp-space-3);
  margin: 0;
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
}

.pet-card__facts div {
  display: flex;
  justify-content: space-between;
  gap: var(--pp-space-2);
}

.pet-card__facts dt {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.pet-card__facts dd {
  margin: 0;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-primary);
  font-family: var(--pp-font-num);
}

.pet-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pet-card__warn {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
  padding: 8px 12px;
  border-radius: var(--pp-radius-sm);
  background: var(--pp-warning-bg);
  color: #a8681f;
  font-size: var(--pp-fs-xs);
}

.pet-card__actions {
  display: flex;
  gap: var(--pp-space-2);
  margin-top: auto;
  flex-wrap: wrap;
}
</style>

