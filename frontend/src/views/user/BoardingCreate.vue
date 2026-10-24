<!--
  新建寄养（宠主）：六段式表单（毛孩子 → 日期 → 宠舍 → 喂食与接送 → 照护要求 → 紧急联系与条款），
  右侧实时费用明细。日期变化即刷新房态与报价（用 watch 驱动，不依赖组件 @change）。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">寄养申请</h2>
        <p class="pp-page-desc">
          为毛孩子挑一个安心的小窝：先选宠物与日期，再挑宠舍，最后确认费用与寄养条款。
          疫苗完整是寄养的硬门槛，不通过无法提交。
        </p>
      </div>
      <el-button :icon="Back" @click="router.back()">返回</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <!-- ① 宠物 -->
        <section class="pp-card">
          <div class="pp-card-title">① 选择毛孩子</div>
          <PawLoading v-if="loadingPets" variant="paw" text="正在叫醒毛孩子…" />
          <EmptyState
            v-else-if="!pets.length"
            illustration="paw"
            title="还没有毛孩子档案"
            description="先建一个档案，才能预约寄养哦。"
          >
            <el-button type="primary" @click="router.push('/user/pets/edit')">新建宠物档案</el-button>
          </EmptyState>
          <div v-else class="pet-picker">
            <div
              v-for="pet in pets"
              :key="pet.id"
              class="pet-picker__item"
              :class="{ 'is-active': form.pet_id === pet.id }"
              @click="pickPet(pet.id)"
            >
              <PetAvatar :species="pet.species" :size="40" />
              <div>
                <div class="pet-picker__name">{{ pet.name }}</div>
                <div class="pet-picker__meta">
                  {{ SPECIES_LABEL[pet.species] }} · {{ pet.weight ? pet.weight + 'kg' : '体重未填' }}
                </div>
              </div>
              <el-tag v-if="pet.sterilized === 0" size="small" type="warning" effect="light">未绝育</el-tag>
              <el-tag v-if="pet.aggressive" size="small" type="danger" effect="light">攻击倾向</el-tag>
            </div>
          </div>
        </section>

        <!-- ② 日期 -->
        <section class="pp-card">
          <div class="pp-card-title">
            ② 寄养日期
            <span class="pp-card-extra">最少 {{ rules.min_nights || 2 }} 晚</span>
          </div>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="入住日期"
            end-placeholder="离店日期"
            :disabled-date="disableDate"
          />
          <p class="hint">
            寄养晚数按「离店日 − 入住日」计算；跨节假日的晚数按节假日系数计价（当前系数
            {{ (rules.holiday_percent || 130) / 100 }} 倍）。
          </p>
        </section>

        <!-- ③ 房型 -->
        <section class="pp-card">
          <div class="pp-card-title">③ 选择宠舍</div>
          <!-- 资格预检：不通过时直接给原因与补救入口，别等用户填完整张表单再报错 -->
          <el-alert
            v-if="eligibility && !eligibility.ok"
            type="warning"
            :closable="false"
            show-icon
            class="pp-mb-4"
            :title="eligibility.message"
          >
            <div class="pp-mt-2">
              <el-button size="small" type="primary" plain @click="goVaccine">
                去登记疫苗
              </el-button>
              <span class="hint">登记后回到本页重新选择日期即可</span>
            </div>
          </el-alert>
          <el-alert
            v-else-if="eligibility?.ok"
            type="success"
            :closable="false"
            show-icon
            class="pp-mb-4"
            :title="`疫苗有效：${eligibility.message}`"
          />
          <el-alert
            v-if="roomTip"
            type="info"
            :closable="false"
            show-icon
            :title="roomTip"
            class="pp-mb-4"
          />
          <div v-if="loadingRooms" class="pp-mt-3"><PawLoading variant="bubble" text="正在查看房态…" /></div>
          <!-- 两级选择：先挑房型，再挑房号（每类最多 10 个号，避免一屏几十张房卡） -->
          <div v-else class="room-picker">
            <div class="room-types">
              <button
                v-for="t in roomTypes"
                :key="t.value"
                type="button"
                class="type-chip"
                :class="{ 'is-active': roomType === t.value, 'is-empty': !t.available }"
                @click="pickType(t.value)"
              >
                <span class="type-chip__name">{{ t.label }}</span>
                <span class="type-chip__meta">
                  {{ t.available }}/{{ t.total }} 可订<template v-if="t.price"> · 约 {{ t.price }} 元/晚起</template>
                </span>
              </button>
            </div>

            <div v-if="!roomType" class="room-hint">先选上面的房型，再挑具体房号</div>
            <template v-else>
              <div class="room-hint">
                {{ roomTypeLabel }} · 共 {{ roomsOfType.length }} 间（最多显示 {{ MAX_ROOMS_PER_TYPE }} 间）
              </div>
              <div class="room-nos">
                <button
                  v-for="room in roomsOfType"
                  :key="room.id"
                  type="button"
                  class="room-no"
                  :class="{ 'is-active': form.room_id === room.id, 'is-disabled': !room.available }"
                  @click="room.available && pickRoom(room)"
                >
                  <span class="room-no__code">{{ room.room_no }}</span>
                  <!-- 房态是「此刻」的状态，能不能订要看所选日期区间：可订就直说可订 -->
                  <span class="room-no__state">{{ room.available ? '可预订' : (room.unavailable_note || '不可订') }}</span>
                  <span class="room-no__price">
                    <template v-if="room.available">约 {{ (room.est_daily_cents || 0) / 100 }} 元/晚</template>
                    <template v-else>—</template>
                  </span>
                </button>
              </div>
            </template>

            <div v-if="selectedRoom" class="room-picked">
              已选：<b>{{ selectedRoom.name }}</b>
              <span class="room-picked__meta">
                · 系数 {{ selectedRoom.ratio_percent / 100 }}×
                <el-tag v-for="f in selectedRoom.facilities" :key="f" size="small" effect="plain">{{ f }}</el-tag>
              </span>
            </div>
          </div>
        </section>

        <!-- ④ 喂食与接送 -->
        <section class="pp-card">
          <div class="pp-card-title">④ 喂食与接送</div>
          <el-form label-position="top">
            <el-form-item label="喂食方案">
              <el-radio-group v-model="form.feeding_plan" @change="refreshQuote">
                <el-radio-button
                  v-for="(label, key) in meta.feeding_plan"
                  :key="key"
                  :value="key"
                >{{ label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="form.feeding_plan === 'self'" label="自备食物明细与喂食说明">
              <el-input
                v-model="form.food_note"
                type="textarea"
                :rows="2"
                maxlength="255"
                show-word-limit
                placeholder="如：每日 2 顿，每顿 120g，品牌 XX；剩余粮离店原样退还"
              />
            </el-form-item>
            <el-form-item label="① 送宠到店">
              <el-radio-group v-model="form.dropoff_method" @change="refreshQuote">
                <el-radio-button
                  v-for="(label, key) in meta.dropoff_method"
                  :key="key"
                  :value="key"
                >{{ label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="② 离店接宠">
              <el-radio-group v-model="form.pickup_back_method" @change="refreshQuote">
                <el-radio-button
                  v-for="(label, key) in meta.pickup_back_method"
                  :key="key"
                  :value="key"
                >{{ label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <p class="hint">送宠到店与离店接宠各选一个，可以「自行送到 + 自行接取」都不产生接送费。</p>
            <template v-if="needShipping">
              <el-form-item label="接送地址">
                <el-input v-model="form.shipping_address" maxlength="255" placeholder="详细到门牌号，方便店员上门" />
              </el-form-item>
              <el-form-item label="上门时间段">
                <el-input v-model="form.shipping_slot" maxlength="32" placeholder="如 10:00-12:00" />
              </el-form-item>
            </template>
          </el-form>
        </section>

        <!-- ⑤ 照护要求 -->
        <section class="pp-card">
          <div class="pp-card-title">
            ⑤ 照护要求
            <span class="pp-card-extra">
              <el-button link type="primary" @click="addCareItem">添加一条</el-button>
            </span>
          </div>
          <EmptyState
            v-if="!form.care_items.length"
            illustration="paw"
            title="还没有特殊照护要求"
            description="有用药、遛放或禁忌需要特别交代？点上面的「添加一条」告诉店员。"
            :size="72"
          />
          <div v-for="(item, idx) in form.care_items" :key="idx" class="care-row">
            <el-select v-model="item.item_type" style="width: 110px">
              <el-option v-for="(label, key) in meta.care_item_types" :key="key" :label="label" :value="key" />
            </el-select>
            <el-input v-model="item.content" placeholder="具体内容，如：关节营养片 1 粒" />
            <el-input v-model="item.frequency" placeholder="频次，如：每日 1 次" style="width: 140px" />
            <el-checkbox v-model="item.need_staff">需店员操作</el-checkbox>
            <el-button link type="danger" :icon="Delete" @click="form.care_items.splice(idx, 1)" />
          </div>
        </section>

        <!-- ⑥ 紧急联系与条款 -->
        <section class="pp-card">
          <div class="pp-card-title">⑥ 紧急联系与授权</div>
          <el-form label-position="top">
            <el-row :gutter="12">
              <el-col :xs="24" :sm="12">
                <el-form-item label="紧急联系人">
                  <el-input v-model="form.emergency_contact" maxlength="50" placeholder="如：张女士" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="紧急联系电话">
                  <el-input v-model="form.emergency_phone" maxlength="11" placeholder="11 位手机号" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item>
              <el-checkbox v-model="form.medical_authorized">
                授权门店在紧急情况下送医（费用由宠主承担）
              </el-checkbox>
            </el-form-item>
            <el-divider />
            <el-form-item>
              <el-checkbox v-model="form.terms_confirmed">
                我已阅读并确认《寄养条款与责任划分》：宠物在寄养期间的异常情况门店会第一时间告知并按流程处置，
                具体赔付标准以门店现场条款为准
              </el-checkbox>
            </el-form-item>
          </el-form>
        </section>
      </el-col>

      <!-- 费用摘要 -->
      <el-col :xs="24" :lg="9">
        <section class="pp-card summary">
          <div class="pp-card-title">费用明细</div>
          <template v-if="quote">
            <div class="summary__row"><span>体重档</span><b>{{ quote.weight_label }}</b></div>
            <div class="summary__row"><span>房型系数</span><b>{{ quote.room_ratio_percent / 100 }}×</b></div>
            <div class="summary__row"><span>平均日费</span><b>¥{{ (quote.daily_fee_cents / 100).toFixed(2) }}</b></div>
            <div class="summary__row"><span>寄养晚数</span><b>{{ quote.nights }} 晚</b></div>
            <div v-if="quote.holiday_nights" class="summary__row">
              <span>其中节假日</span><b>{{ quote.holiday_nights }} 晚</b>
            </div>
            <div class="summary__row"><span>房费小计</span><b>¥{{ (quote.subtotal_cents / 100).toFixed(2) }}</b></div>
            <div v-if="quote.discount_percent < 100" class="summary__row summary__row--discount">
              <span>长住折扣</span><b>{{ quote.discount_percent / 10 }} 折</b>
            </div>
            <div v-if="quote.feeding_fee_cents" class="summary__row">
              <span>升级喂食</span><b>¥{{ (quote.feeding_fee_cents / 100).toFixed(2) }}</b>
            </div>
            <div v-if="quote.shipping_fee_cents" class="summary__row">
              <span>接送费</span><b>¥{{ (quote.shipping_fee_cents / 100).toFixed(2) }}</b>
            </div>
            <el-divider />
            <div class="summary__total">
              <span>应付总额</span>
              <b>¥{{ (quote.total_cents / 100).toFixed(2) }}</b>
            </div>
            <p class="hint">
              门店确认后按订单结算；提前接回按实际天数结算，差额线下退还。
            </p>
          </template>
          <EmptyState
            v-else
            illustration="cat"
            title="还没有可计算的价格"
            description="选好毛孩子、日期与宠舍，这里会实时算出费用。"
            :size="72"
          />

          <el-button
            type="primary"
            size="large"
            class="summary__submit"
            :loading="submitting"
            :disabled="!canSubmit"
            @click="submit"
          >
            提交寄养申请
          </el-button>
          <p class="hint">提交后门店会核对房态与疫苗记录并确认；状态变更会推送站内消息。</p>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, Delete } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import { boardingApi, type BoardingCreatePayload } from '@/api/boarding'
import { petApi } from '@/api/pet'
import { SPECIES_LABEL } from '@/utils/dict'
import type {
  BoardingEligibility,
  BoardingMeta,
  BoardingQuote,
  BoardingRoom,
  Pet
} from '@/types'

const router = useRouter()
const pets = ref<Pet[]>([])
const rooms = ref<BoardingRoom[]>([])
const quote = ref<BoardingQuote | null>(null)
const dateRange = ref<[string, string] | null>(null)
const loadingPets = ref(true)
const loadingRooms = ref(false)
/** 寄养资格预检结果（疫苗硬门槛）：null 表示还没查 */
const eligibility = ref<BoardingEligibility | null>(null)
const submitting = ref(false)
const idempotentKey = ref(genKey())

const meta = reactive<BoardingMeta>({
  order_status: {},
  room_type: {},
  room_status: {},
  feeding_plan: {},
  shipping_method: {},
  dropoff_method: {},
  pickup_back_method: {},
  pickup_status: {},
  care_item_types: {},
  rules: {}
})

const form = reactive({
  pet_id: 0,
  room_id: 0,
  feeding_plan: 'self',
  food_note: '',
  dropoff_method: 'self',
  pickup_back_method: 'self',
  shipping_address: '',
  shipping_slot: '',
  emergency_contact: '',
  emergency_phone: '',
  medical_authorized: true,
  terms_confirmed: false,
  care_items: [] as { item_type: string; content: string; frequency: string; need_staff: boolean }[]
})

const rules = computed(() => meta.rules || {})
const roomTip = computed(() => {
  if (!dateRange.value) return '先选寄养日期，房型会显示该区间是否可订。'
  const pet = pets.value.find((p) => p.id === form.pet_id)
  if (pet && pet.sterilized === 0) return '该毛孩子未绝育：按门店规范需独占一间房舍。'
  if (pet?.aggressive) return '该毛孩子有攻击倾向记录：需独占房舍并由双人操作。'
  return ''
})
/** 任一段选择了接送，才需要填地址与时间段 */
const needShipping = computed(
  () => form.dropoff_method === 'pickup' || form.pickup_back_method === 'return'
)
const canSubmit = computed(
  () =>
    !!form.pet_id &&
    !!form.room_id &&
    !!dateRange.value &&
    form.terms_confirmed &&
    !!quote.value &&
    // 资格预检明确不通过时禁止提交（null 表示未查到，仍交给后端兜底）
    eligibility.value?.ok !== false
)

function genKey() {
  return `board-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function disableDate(d: Date) {
  return d.getTime() < Date.now() - 86400000
}

async function loadPets() {
  loadingPets.value = true
  try {
    pets.value = await petApi.list()
    if (pets.value.length === 1) pickPet(pets.value[0].id)
  } finally {
    loadingPets.value = false
  }
}

function pickPet(id: number) {
  form.pet_id = id
  form.room_id = 0
  quote.value = null
  eligibility.value = null
  loadRooms()
  void checkEligibility()
}

/** 查询寄养资格（疫苗是否覆盖入住日）：选完宠物与日期就先查，别等提交才报错 */
async function checkEligibility() {
  if (!form.pet_id || !dateRange.value || dateRange.value.length !== 2) {
    eligibility.value = null
    return
  }
  try {
    eligibility.value = await boardingApi.eligibility(form.pet_id, dateRange.value[0])
  } catch {
    // 预检失败不阻断填写，后端下单时仍会做硬校验
    eligibility.value = null
  }
}

/** 去登记疫苗：直达档案页并自动打开该宠物的疫苗记录抽屉 */
function goVaccine() {
  router.push({ path: '/user/pets', query: { vaccine: String(form.pet_id) } })
}

/** 两级选择的第二级：每个房型最多展示 10 个房号 */
const MAX_ROOMS_PER_TYPE = 10
/** 第一级：当前选中的房型 */
const roomType = ref('')

/** 房型聚合：可订数量与起价（按房型分组，用户先看这一层） */
const roomTypes = computed(() => {
  const groups = new Map<string, { value: string; label: string; total: number; available: number; minCents: number }>()
  for (const room of rooms.value) {
    const g = groups.get(room.room_type) || {
      value: room.room_type,
      label: room.room_type_label || room.room_type,
      total: 0,
      available: 0,
      minCents: Number.POSITIVE_INFINITY
    }
    g.total += 1
    if (room.available) {
      g.available += 1
      g.minCents = Math.min(g.minCents, room.est_daily_cents || Number.POSITIVE_INFINITY)
    }
    groups.set(room.room_type, g)
  }
  return [...groups.values()]
    .sort((a, b) => a.value.localeCompare(b.value))
    .map((g) => ({ ...g, price: Number.isFinite(g.minCents) ? Math.round(g.minCents / 100) : 0 }))
})

/** 当前房型下的房号（最多 10 个，房号升序） */
const roomsOfType = computed(() =>
  rooms.value
    .filter((r) => r.room_type === roomType.value)
    .sort((a, b) => a.room_no.localeCompare(b.room_no))
    .slice(0, MAX_ROOMS_PER_TYPE)
)

const roomTypeLabel = computed(
  () => roomTypes.value.find((t) => t.value === roomType.value)?.label || ''
)

const selectedRoom = computed(() => rooms.value.find((r) => r.id === form.room_id) || null)

/** 切房型时清掉另一房型的已选房号，避免「选的是标准间、提交的却是花园房」 */
function pickType(type: string) {
  roomType.value = type
  const picked = selectedRoom.value
  if (picked && picked.room_type !== type) {
    form.room_id = 0
    quote.value = null
  }
}

function pickRoom(room: BoardingRoom) {
  form.room_id = room.id
  refreshQuote()
}

async function loadRooms() {
  if (!form.pet_id || !dateRange.value || dateRange.value.length !== 2) return
  loadingRooms.value = true
  try {
    rooms.value = await boardingApi.rooms({
      pet_id: form.pet_id,
      check_in: dateRange.value[0],
      check_out: dateRange.value[1]
    })
    // 已选房型若不可订则清空，避免提交时才报错
    const picked = rooms.value.find((r) => r.id === form.room_id)
    if (picked && picked.available) {
      roomType.value = picked.room_type
    } else {
      form.room_id = 0
      // 默认落在第一个有可订房号的房型，用户不用先盲点一次
      roomType.value =
        roomTypes.value.find((t) => t.available > 0)?.value || roomTypes.value[0]?.value || ''
    }
    refreshQuote()
  } finally {
    loadingRooms.value = false
  }
}

async function refreshQuote() {
  if (!form.pet_id || !form.room_id || !dateRange.value) {
    quote.value = null
    return
  }
  try {
    quote.value = await boardingApi.quote({
      pet_id: form.pet_id,
      room_id: form.room_id,
      check_in_date: dateRange.value[0],
      check_out_date: dateRange.value[1],
      feeding_plan: form.feeding_plan,
      dropoff_method: form.dropoff_method,
      pickup_back_method: form.pickup_back_method
    })
  } catch {
    quote.value = null
  }
}

function addCareItem() {
  form.care_items.push({ item_type: 'medication', content: '', frequency: '', need_staff: true })
}

async function submit() {
  if (!dateRange.value) return
  const payload: BoardingCreatePayload = {
    pet_id: form.pet_id,
    room_id: form.room_id,
    check_in_date: dateRange.value[0],
    check_out_date: dateRange.value[1],
    feeding_plan: form.feeding_plan,
    food_note: form.food_note || undefined,
    dropoff_method: form.dropoff_method,
    pickup_back_method: form.pickup_back_method,
    shipping_address: form.shipping_address || undefined,
    shipping_slot: form.shipping_slot || undefined,
    emergency_contact: form.emergency_contact || undefined,
    emergency_phone: form.emergency_phone || undefined,
    medical_authorized: form.medical_authorized,
    terms_confirmed: form.terms_confirmed,
    care_items: form.care_items
      .filter((i) => i.content.trim())
      .map((i) => ({
        item_type: i.item_type,
        content: i.content.trim(),
        frequency: i.frequency || undefined,
        need_staff: i.need_staff
      })),
    idempotent_key: idempotentKey.value
  }
  submitting.value = true
  try {
    const order = await boardingApi.createOrder(payload)
    ElMessage.success(`寄养申请已提交：${order.order_no}`)
    idempotentKey.value = genKey()
    router.push(`/user/boarding/${order.id}`)
  } finally {
    submitting.value = false
  }
}

// 日期一变化就重新查房态与报价。
// 不用 el-date-picker 的 @change：实测该事件在 daterange 下可能不触发，
// v-model 已更新但页面毫无反应（真实 bug：选了日期房型列表仍为空、永远算不出价格）。
watch(
  () => dateRange.value,
  async (val) => {
    if (!val || val.length !== 2) return
    await Promise.all([loadRooms(), checkEligibility()])
  }
)

onMounted(async () => {
  const m = await boardingApi.meta()
  Object.assign(meta, m)
  await loadPets()
})
</script>

<style scoped>
.pet-picker {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--pp-space-3);
}

.pet-picker__item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  padding: var(--pp-space-3);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.pet-picker__item:hover {
  border-color: var(--pp-primary-light);
}

.pet-picker__item.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
  box-shadow: var(--pp-shadow-sm);
}

.pet-picker__name {
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.pet-picker__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

/* 两级房舍选择：房型 chip → 房号小卡（每类最多 10 个） */
.room-picker {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.room-types {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--pp-space-2);
}

.type-chip {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--pp-space-3);
  text-align: left;
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  font-family: inherit;
}

.type-chip:hover {
  border-color: var(--pp-primary-light);
  box-shadow: var(--pp-shadow-sm);
}

.type-chip.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
}

.type-chip.is-empty {
  opacity: 0.55;
}

.type-chip__name {
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.type-chip__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.room-hint {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.room-nos {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--pp-space-2);
}

.room-no {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--pp-space-2) var(--pp-space-3);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-card);
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.room-no:hover {
  border-color: var(--pp-primary-light);
  box-shadow: var(--pp-shadow-sm);
}

.room-no.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
  box-shadow: 0 6px 18px rgba(91, 155, 213, 0.14);
}

.room-no.is-disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: var(--pp-bg-sunken);
}

.room-no__code {
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
  font-family: var(--pp-font-num);
}

.room-no__state {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.room-no__price {
  font-size: var(--pp-fs-xs);
  color: var(--pp-primary-dark);
}

.room-picked {
  padding: var(--pp-space-2) var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-primary-lighter);
  color: var(--pp-text-regular);
  font-size: var(--pp-fs-sm);
}

.room-picked__meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 4px;
  color: var(--pp-text-secondary);
  font-size: var(--pp-fs-xs);
}

.care-row {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  margin-bottom: var(--pp-space-2);
  flex-wrap: wrap;
}

.hint {
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.7;
}

.summary__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  font-size: var(--pp-fs-base);
  color: var(--pp-text-regular);
}

.summary__row b {
  font-family: var(--pp-font-num);
  color: var(--pp-text-primary);
}

.summary__row--discount b {
  color: var(--pp-success);
}

.summary__total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--pp-fs-md);
  color: var(--pp-text-primary);
}

.summary__total b {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-2xl);
  color: var(--pp-danger);
}

.summary__submit {
  width: 100%;
  margin-top: var(--pp-space-4);
}
</style>
