<!--
  发起预约（宠主）：选宠物 → 选日期时段 → 看风险提示 → 提交。
  数据来源：GET /appointments/slots 与 /options；提交带幂等键，重复点击不会落两单。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">发起洗护预约</h2>
        <p class="pp-page-desc">
          选择服务与到店时段后，右侧会实时展示预约摘要；提交后门店会在配置时限内确认。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Tickets" @click="router.push('/user/appointments')">我的预约</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <!-- 选择宠物 -->
        <section class="pp-card">
          <div class="pp-card-title">选择毛孩子</div>
          <PawLoading v-if="loadingPets" variant="paw" text="加载宠物档案中…" />
          <EmptyState
            v-else-if="!pets.length"
            illustration="paw"
            title="还没有宠物档案"
            description="先为毛孩子建一个温暖的小窝，再回来预约吧。"
          >
            <el-button type="primary" @click="router.push('/user/pets/edit')">新建宠物档案</el-button>
          </EmptyState>
          <div v-else class="pet-picker">
            <button
              v-for="pet in pets"
              :key="pet.id"
              type="button"
              class="pet-option"
              :class="{ 'is-active': form.pet_id === pet.id }"
              @click="form.pet_id = pet.id"
            >
              <PetAvatar :species="pet.species" :size="42" />
              <div class="pet-option__body">
                <div class="pet-option__name">{{ pet.name }}</div>
                <div class="pet-option__meta">{{ SPECIES_LABEL[pet.species] }} · {{ pet.breed || '未知品种' }}</div>
              </div>
              <el-tag v-if="petRiskTag(pet)" size="small" type="warning" effect="light">需风险关注</el-tag>
            </button>
          </div>
        </section>

        <!-- 选择服务 -->
        <section class="pp-card">
          <div class="pp-card-title">选择洗护服务</div>
          <div class="service-picker">
            <button
              v-for="svc in services"
              :key="svc.value"
              type="button"
              class="service-option"
              :class="{ 'is-active': form.service_type === svc.value }"
              @click="form.service_type = svc.value"
            >
              <div class="service-option__icon"><el-icon :size="20"><component :is="svc.icon" /></el-icon></div>
              <div class="service-option__title">{{ svc.label }}</div>
              <div class="service-option__desc">{{ svc.desc }}</div>
            </button>
          </div>
        </section>

        <!-- 选择时段 -->
        <section class="pp-card">
          <div class="pp-card-title">
            选择到店时间
            <span class="pp-card-extra">营业时段 09:00 - 18:00，每时段容量 {{ capacity }}</span>
          </div>

          <el-date-picker
            v-model="form.appoint_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择到店日期"
            :disabled-date="disabledDate"
            style="width: 240px; margin-bottom: 16px"
            @change="loadSlots"
          />

          <PawLoading v-if="loadingSlots" variant="bubble" text="正在看看还有没有空位…" />
          <div v-else class="slot-grid">
            <button
              v-for="slot in slots"
              :key="slot.slot_time"
              type="button"
              class="slot-option"
              :class="{ 'is-active': form.slot_time === slot.slot_time, 'is-full': slot.disabled }"
              :disabled="slot.disabled"
              @click="pickSlot(slot)"
            >
              <span class="slot-option__time">{{ slot.slot_time }}</span>
              <span class="slot-option__remain">
                {{ slot.disabled ? '已约满' : `余 ${slot.remain}/${slot.capacity}` }}
              </span>
            </button>
          </div>

          <div class="pp-mt-4">
            <el-input
              v-model="form.remark"
              type="textarea"
              :rows="3"
              maxlength="255"
              show-word-limit
              placeholder="有什么想让门店特别留意的吗？例如：上次洗护后皮肤有点红，请用低敏浴液"
            />
          </div>
        </section>
      </el-col>

      <!-- 预约摘要 -->
      <el-col :xs="24" :lg="9">
        <section class="pp-card summary-card">
          <div class="pp-card-title">预约摘要</div>

          <div class="summary-row">
            <span class="summary-label">毛孩子</span>
            <span class="summary-value">{{ selectedPet?.name || '未选择' }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">洗护服务</span>
            <span class="summary-value">{{ serviceLabel }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">到店时间</span>
            <span class="summary-value">
              {{ form.appoint_date || '未选择' }} {{ form.slot_time || '' }}
            </span>
          </div>

          <div v-if="selectedPetRisk" class="summary-risk">
            <el-icon :size="14"><WarnTriangleFilled /></el-icon>
            <div>
              <div class="summary-risk__title">档案提示</div>
              <div class="summary-risk__text">{{ selectedPetRisk }}</div>
            </div>
          </div>
          <el-alert
            v-else-if="selectedPet"
            type="success"
            :closable="false"
            show-icon
            title="档案没有需要特别留意的标记"
            class="pp-mt-4"
          />

          <el-button
            type="primary"
            class="summary-submit"
            :loading="submitting"
            :disabled="!form.pet_id || !form.slot_time"
            @click="submit"
          >
            提交预约
          </el-button>
          <p class="summary-tip">
            提交后我们会立即生成洗护风险提示，店员会在洗护前复核确认。
          </p>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Sunny, Tickets, WarnTriangleFilled } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import { appointmentApi } from '@/api/appointment'
import { petApi } from '@/api/pet'
import { SPECIES_LABEL } from '@/utils/dict'
import { genIdempotentKey, toDateStr } from '@/utils/format'
import type { Pet, SlotItem } from '@/types'

const router = useRouter()
const route = useRoute()

const loadingPets = ref(true)
const loadingSlots = ref(false)
const submitting = ref(false)
const pets = ref<Pet[]>([])
const slots = ref<SlotItem[]>([])
const capacity = ref(3)

/** 幂等键：整张表单只生成一次，重复点击不会产生重复订单 */
const idempotentKey = ref(genIdempotentKey('form'))

const form = reactive({
  pet_id: undefined as number | undefined,
  service_type: 'basic_bath',
  appoint_date: toDateStr(new Date()),
  slot_time: '',
  remark: ''
})

const serviceCatalog = [
  { value: 'basic_bath', label: '基础洗澡', desc: '清洁、吹干、指甲修剪', icon: 'Sunny' },
  { value: 'medicated_bath', label: '药浴护理', desc: '针对皮肤问题的温和药浴', icon: 'FirstAidKit' },
  { value: 'grooming', label: '美容修剪', desc: '造型修剪 + 全套洗护', icon: 'Scissor' }
]
const services = ref(serviceCatalog)

const selectedPet = computed(() => pets.value.find((p) => p.id === form.pet_id))
const serviceLabel = computed(
  () => services.value.find((s) => s.value === form.service_type)?.label || '-'
)
const selectedPetRisk = computed(() => {
  const pet = selectedPet.value
  if (!pet) return ''
  const items: string[] = []
  if (pet.aggressive) items.push('有攻击倾向，门店会安排防护')
  if (pet.allergy) items.push(`过敏史：${pet.allergy}`)
  if (pet.skin_disease) items.push(`皮肤病史：${pet.skin_disease}`)
  if (pet.stress_level >= 2) items.push('应激等级偏高，建议安排安静时段')
  return items.join('；')
})

function petRiskTag(pet: Pet) {
  return pet.aggressive || pet.allergy || pet.skin_disease || pet.stress_level >= 2
}

function disabledDate(d: Date) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return d.getTime() < today.getTime()
}

async function loadPets() {
  loadingPets.value = true
  try {
    pets.value = await petApi.list()
    const preset = Number(route.query.pet)
    if (preset && pets.value.some((p) => p.id === preset)) form.pet_id = preset
    else if (pets.value.length === 1) form.pet_id = pets.value[0].id
  } finally {
    loadingPets.value = false
  }
}

async function loadSlots() {
  if (!form.appoint_date) {
    slots.value = []
    return
  }
  loadingSlots.value = true
  try {
    const res = await appointmentApi.slots(form.appoint_date)
    capacity.value = res.capacity
    slots.value = res.slots
    const picked = slots.value.find((s) => s.slot_time === form.slot_time)
    if (picked?.disabled) form.slot_time = ''
  } finally {
    loadingSlots.value = false
  }
}

function pickSlot(slot: SlotItem) {
  if (slot.disabled) return
  form.slot_time = slot.slot_time
}

async function submit() {
  if (!form.pet_id || !form.slot_time) return
  submitting.value = true
  try {
    const res = await appointmentApi.create({ ...form, idempotent_key: idempotentKey.value })
    await ElMessageBox.alert(
      `预约单号：${res.order_no}\n到店时间：${res.appoint_date} ${res.slot_time}\n当前状态：${res.status_label || '待确认'}\n\n门店确认后会通过站内消息通知你 🐾`,
      '预约提交成功',
      { confirmButtonText: '查看我的预约', confirmButtonClass: 'el-button--primary' }
    )
    router.push('/user/appointments')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadPets()
  try {
    const opts = await appointmentApi.options()
    if (opts.services?.length) {
      services.value = opts.services.map((s) => {
        const meta = serviceCatalog.find((c) => c.value === s.value)
        return { value: s.value, label: s.label, desc: meta?.desc || '', icon: meta?.icon || 'Sunny' }
      })
    }
  } catch {
    /* 选项接口不可用时使用内置目录兜底 */
  }
  await loadSlots()
})
</script>

<style scoped>
/* ---------------- 宠物选择 ---------------- */
.pet-picker {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--pp-space-3);
}

.pet-option {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  border: 1.5px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  font-family: inherit;
  text-align: left;
}

.pet-option:hover {
  border-color: var(--pp-primary-light);
  transform: translateY(-1px);
}

.pet-option.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
  box-shadow: 0 6px 18px rgba(91, 155, 213, 0.16);
}

.pet-option__body {
  flex: 1;
  min-width: 0;
}

.pet-option__name {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.pet-option__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

/* ---------------- 服务选择 ---------------- */
.service-picker {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--pp-space-3);
}

.service-option {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--pp-space-2);
  padding: var(--pp-space-4) var(--pp-space-3);
  border-radius: var(--pp-radius-lg);
  border: 1.5px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  font-family: inherit;
  text-align: center;
}

.service-option:hover {
  border-color: var(--pp-primary-light);
  transform: translateY(-2px);
  box-shadow: var(--pp-shadow-sm);
}

.service-option.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
}

.service-option__icon {
  width: 44px;
  height: 44px;
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-cream);
  color: var(--pp-primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}

.service-option.is-active .service-option__icon {
  background: #fff;
  color: var(--pp-primary);
}

.service-option__title {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.service-option__desc {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

/* ---------------- 时段选择 ---------------- */
.slot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: var(--pp-space-2);
}

.slot-option {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 8px;
  border-radius: var(--pp-radius-pill);
  border: 1.5px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  font-family: var(--pp-font-num);
}

.slot-option:hover:not(.is-full) {
  border-color: var(--pp-primary-light);
  transform: translateY(-1px);
}

.slot-option.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
  box-shadow: 0 6px 16px rgba(91, 155, 213, 0.16);
}

.slot-option.is-full {
  background: var(--pp-bg-cream);
  border-color: transparent;
  cursor: not-allowed;
  opacity: 0.7;
}

.slot-option__time {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.slot-option__remain {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.slot-option.is-full .slot-option__remain {
  color: var(--pp-danger);
}

.slot-option.is-full .slot-option__time {
  color: var(--pp-text-placeholder);
}

/* ---------------- 摘要 ---------------- */
.summary-card {
  position: sticky;
  top: var(--pp-space-4);
  background: linear-gradient(180deg, #fffdfa 0%, #ffffff 100%);
}

.summary-row {
  display: flex;
  justify-content: space-between;
  gap: var(--pp-space-3);
  padding: var(--pp-space-3) 0;
  border-bottom: 1px dashed var(--pp-border-light);
}

.summary-row:last-of-type {
  border-bottom: none;
}

.summary-label {
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
}

.summary-value {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
  text-align: right;
}

.summary-risk {
  display: flex;
  gap: var(--pp-space-2);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-warning-bg);
  color: #a8681f;
  margin-top: var(--pp-space-3);
}

.summary-risk__title {
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-semibold);
  margin-bottom: 2px;
}

.summary-risk__text {
  font-size: var(--pp-fs-xs);
  line-height: 1.6;
}

.summary-submit {
  width: 100%;
  height: 46px;
  margin-top: var(--pp-space-4);
  font-size: var(--pp-fs-md);
}

.summary-tip {
  margin: var(--pp-space-3) 0 0;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  line-height: 1.7;
}
</style>
