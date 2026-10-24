<!--
  403 无权限页：告知「这块归店长/店员」，并给回首页的出口。
-->

<template>
  <div class="pp-error-page">
    <PetIllustration type="cat" :size="168" class="pp-float" />
    <h2 class="pp-error-page__code">403</h2>
    <p class="pp-error-page__title">这个页面不属于当前角色的服务范围</p>
    <p class="pp-error-page__desc">
      你当前以「{{ userStore.roleLabel }}」身份登录{{ from ? `，无法访问 ${from}` : '' }}。
      可以回到自己的首页继续操作 🐾
    </p>
    <div class="pp-error-page__actions">
      <el-button type="primary" @click="router.replace(userStore.homePath)">回到我的首页</el-button>
      <el-button @click="router.back()">返回上一页</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PetIllustration from '@/components/PetIllustration.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const from = computed(() => (route.query.from as string) || '')
</script>

<style scoped>
.pp-error-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--pp-space-6);
  background: linear-gradient(135deg, #eef5fc 0%, #fbf8f3 100%);
}

.pp-error-page__code {
  font-family: var(--pp-font-num);
  font-size: 56px;
  font-weight: var(--pp-fw-bold);
  color: var(--pp-primary-light);
  margin: var(--pp-space-3) 0 0;
  line-height: 1;
}

.pp-error-page__title {
  margin: var(--pp-space-3) 0 var(--pp-space-2);
  font-size: var(--pp-fs-lg);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.pp-error-page__desc {
  margin: 0 0 var(--pp-space-5);
  font-size: var(--pp-fs-base);
  color: var(--pp-text-secondary);
  max-width: 480px;
}

.pp-error-page__actions {
  display: flex;
  gap: var(--pp-space-3);
}
</style>
