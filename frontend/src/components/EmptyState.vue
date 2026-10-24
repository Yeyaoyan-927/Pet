<!--
  空状态占位：插画 + 温柔文案 + 可选操作按钮。
  项目约定「空状态必配插画与引导」，不要直接用 el-empty。
-->
<template>
  <div class="pp-empty">
    <PetIllustration :type="illustration" :size="size" class="pp-empty__art pp-float" />
    <p class="pp-empty__title">{{ title }}</p>
    <p v-if="description" class="pp-empty__desc">{{ description }}</p>
    <slot />
  </div>
</template>

<script setup lang="ts">
import PetIllustration from './PetIllustration.vue'

withDefaults(
  defineProps<{
    title: string
    description?: string
    illustration?: 'dog' | 'cat' | 'paw'
    size?: number
  }>(),
  { illustration: 'paw', size: 92 }
)
</script>

<style scoped>
.pp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--pp-space-6) var(--pp-space-4);
  text-align: center;
}

.pp-empty__art {
  opacity: 0.9;
  margin-bottom: var(--pp-space-3);
}

.pp-empty__title {
  margin: 0;
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-regular);
}

.pp-empty__desc {
  margin: var(--pp-space-1) 0 var(--pp-space-3);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
  max-width: 420px;
}
</style>
