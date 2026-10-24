<!--
  加载动效：爪印跳动 / 泡泡上升（按 variant 切换），替代默认转圈。
  项目约定：加载态统一用它，不要出现 el-loading 的默认圈。
-->

<template>
  <div class="pp-loading" :class="`pp-loading--${variant}`">
    <!-- 爪印跳动 -->
    <div v-if="variant === 'paw'" class="pp-paw-loader">
      <span></span><span></span><span></span><span></span>
    </div>

    <!-- 泡泡上升 -->
    <div v-else-if="variant === 'bubble'" class="pp-bubble-loader">
      <i></i><i></i><i></i>
    </div>

    <!-- 小猫尾巴摇摆 -->
    <div v-else class="pp-tail-loader">
      <svg viewBox="0 0 44 30">
        <path d="M6 24c6 0 10-6 12-12 1.6-4.6 6-6 9-3 3 3 1.4 7-2 8" />
      </svg>
    </div>

    <span v-if="text" class="pp-loading__text">{{ text }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'paw' | 'bubble' | 'tail'
    text?: string
  }>(),
  { variant: 'paw' }
)
</script>

<style scoped>
.pp-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--pp-space-2);
  padding: var(--pp-space-5);
}

.pp-loading__text {
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
}

.pp-loading--inline {
  flex-direction: row;
  padding: 0;
  gap: var(--pp-space-2);
}
</style>
