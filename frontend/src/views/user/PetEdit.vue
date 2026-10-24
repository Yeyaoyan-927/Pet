<!--
  宠物档案新建/编辑（宠主）：基础信息 + 过敏史/皮肤病史/应激等级/攻击倾向 + 疫苗记录。
  这些字段直接决定风险判别与用品推荐，因此表单里给了明确的填写说明。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">{{ isEdit ? '编辑宠物档案' : '新建宠物档案' }}</h2>
        <p class="pp-page-desc">
          带 <span class="required">*</span> 为必填。健康与安全分组会直接参与洗护风险判别，请尽量如实填写。
        </p>
      </div>
      <div class="pp-page-actions">
        <!-- 编辑态才显示：新建时还没有 pet_id，疫苗记录要先有档案才能登记 -->
        <el-button v-if="isEdit" :icon="FirstAidKit" @click="vaccineVisible = true">疫苗 / 驱虫记录</el-button>
        <el-button :icon="Back" @click="router.back()">返回</el-button>
      </div>
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="118px" v-loading="loading">
      <section class="pp-card">
        <div class="pp-card-title">基础信息</div>
        <el-row :gutter="16">
          <el-col :xs="24" :md="8">
            <el-form-item label="宠物名" prop="name">
              <el-input v-model="form.name" maxlength="50" placeholder="毛孩子的名字" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="类型" prop="species">
              <el-radio-group v-model="form.species">
                <el-radio-button value="dog">犬</el-radio-button>
                <el-radio-button value="cat">猫</el-radio-button>
                <el-radio-button value="other">其他</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="品种">
              <el-input v-model="form.breed" maxlength="50" placeholder="如：金毛寻回犬" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="性别" prop="gender">
              <el-radio-group v-model="form.gender">
                <el-radio-button value="male">公</el-radio-button>
                <el-radio-button value="female">母</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="生日">
              <el-date-picker
                v-model="form.birthday"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择生日"
                :disabled-date="(d: Date) => d.getTime() > Date.now()"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="体重 (kg)">
              <el-input-number v-model="form.weight" :min="0" :max="200" :precision="2" :step="0.5" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="是否绝育">
              <el-switch v-model="sterilized" active-text="已绝育" inactive-text="未绝育" inline-prompt />
            </el-form-item>
          </el-col>
        </el-row>
      </section>

      <section class="pp-card">
        <div class="pp-card-title">
          健康与安全
          <span class="pp-card-extra">这些信息会用于生成洗护风险提示</span>
        </div>
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="过敏史">
              <el-input
                v-model="form.allergy"
                type="textarea"
                :rows="3"
                maxlength="500"
                show-word-limit
                placeholder="如：对含燕麦成分的浴液过敏"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="皮肤病史">
              <el-input
                v-model="form.skin_disease"
                type="textarea"
                :rows="3"
                maxlength="500"
                show-word-limit
                placeholder="如：季节性湿疹（左前肢）"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="应激等级">
              <el-radio-group v-model="form.stress_level">
                <el-radio-button :value="0">无</el-radio-button>
                <el-radio-button :value="1">轻度</el-radio-button>
                <el-radio-button :value="2">中度</el-radio-button>
                <el-radio-button :value="3">重度</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="攻击倾向">
              <el-switch v-model="aggressive" active-text="有" inactive-text="无" inline-prompt />
              <span class="field-hint">有攻击倾向时，门店会安排双人操作与防护</span>
            </el-form-item>
          </el-col>
        </el-row>
      </section>

      <section class="pp-card">
        <div class="pp-card-title">应急联系</div>
        <el-row :gutter="16">
          <el-col :xs="24" :md="8">
            <el-form-item label="应急联系人">
              <el-input v-model="form.emergency_contact" maxlength="50" placeholder="如：张女士" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="应急电话">
              <el-input v-model="form.emergency_phone" maxlength="11" placeholder="11 位手机号（加密存储）" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" show-word-limit placeholder="其他需要门店知道的事情" />
        </el-form-item>
      </section>

      <div class="form-actions">
        <el-button type="primary" :loading="saving" @click="submit">保存档案</el-button>
        <el-button v-if="isEdit" :icon="FirstAidKit" @click="vaccineVisible = true">去登记疫苗 / 驱虫</el-button>
        <el-button @click="router.back()">取消</el-button>
      </div>
    </el-form>

    <!-- 与档案卡片页共用同一个抽屉组件，避免两处维护两套表单 -->
    <VaccineDrawer v-model="vaccineVisible" :pet-id="petId" :pet-name="form.name" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Back, FirstAidKit } from '@element-plus/icons-vue'
import VaccineDrawer from '@/components/VaccineDrawer.vue'
import { petApi } from '@/api/pet'
import { useUserStore } from '@/stores/user'
import type { Pet } from '@/types'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const petId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => petId.value !== null)

const loading = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()
const sterilized = ref(false)
const aggressive = ref(false)
const vaccineVisible = ref(false)

const form = reactive({
  name: '',
  species: 'dog' as Pet['species'],
  breed: '',
  gender: 'male' as Pet['gender'],
  birthday: null as string | null,
  weight: 5,
  allergy: '',
  skin_disease: '',
  stress_level: 0,
  emergency_contact: '',
  emergency_phone: '',
  remark: ''
})

const rules: FormRules = {
  name: [
    { required: true, message: '请输入宠物名', trigger: 'blur' },
    { min: 1, max: 50, message: '长度 1-50 位', trigger: 'blur' }
  ],
  species: [{ required: true, message: '请选择类型', trigger: 'change' }],
  gender: [{ required: true, message: '请选择性别', trigger: 'change' }]
}

async function loadDetail() {
  if (!petId.value) return
  loading.value = true
  try {
    const pet = await petApi.detail(petId.value)
    Object.assign(form, {
      name: pet.name,
      species: pet.species,
      breed: pet.breed || '',
      gender: pet.gender,
      birthday: pet.birthday,
      weight: pet.weight ?? 0,
      allergy: pet.allergy || '',
      skin_disease: pet.skin_disease || '',
      stress_level: pet.stress_level,
      emergency_contact: pet.emergency_contact || '',
      emergency_phone: pet.emergency_phone || '',
      remark: pet.remark || ''
    })
    sterilized.value = pet.sterilized === 1
    aggressive.value = pet.aggressive === 1
  } finally {
    loading.value = false
  }
}

async function submit() {
  await formRef.value?.validate()
  if (form.emergency_phone && !/^1\d{10}$/.test(form.emergency_phone)) {
    ElMessage.warning('应急电话需为 11 位手机号')
    return
  }
  saving.value = true
  const payload = {
    ...form,
    weight: form.weight ?? null,
    birthday: form.birthday || null,
    sterilized: sterilized.value ? 1 : 0,
    aggressive: aggressive.value ? 1 : 0
  } as Partial<Pet>
  try {
    if (isEdit.value && petId.value) {
      await petApi.update(petId.value, payload)
      ElMessage.success('档案已更新')
    } else {
      await petApi.create(payload)
      ElMessage.success('档案已创建，可以预约洗护啦 🐾')
    }
    router.push(userStore.isCustomer ? '/user/pets' : '/staff/pets')
  } finally {
    saving.value = false
  }
}

onMounted(loadDetail)
</script>

<style scoped>
.required {
  color: var(--pp-danger);
}

.field-hint {
  margin-left: var(--pp-space-3);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.form-actions {
  display: flex;
  gap: var(--pp-space-3);
  padding: var(--pp-space-2) 0 var(--pp-space-6);
}
</style>
