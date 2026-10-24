<!--
  404 页面不存在：温柔文案 + 回首页。
-->

<template>
  <div class="pp-error-page">
    <PetIllustration type="paw" :size="168" class="pp-float" />
    <h2 class="pp-error-page__code">404</h2>
    <p class="pp-error-page__title">这里好像没有毛孩子的足迹</p>
    <p class="pp-error-page__desc">页面可能已经被移动或删除了，回到首页重新找找吧。</p>
    <div class="pp-error-page__actions">
      <el-button type="primary" @click="router.replace(userStore.isLogin ? userStore.homePath : '/login')">
        回到首页
      </el-button>
      <el-button @click="router.back()">返回上一页</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import PetIllustration from '@/components/PetIllustration.vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
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
}

.pp-error-page__actions {
  display: flex;
  gap: var(--pp-space-3);
}
</style>
