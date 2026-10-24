<!--
  指标卡：图标 + 数值 + 单位 + 说明，可选趋势与颜色语义。
-->
<template>
  <div class="pp-stat" :class="`pp-stat--${tone}`">
    <div class="pp-stat-label">
      <el-icon v-if="icon" :size="15"><component :is="icon" /></el-icon>
      {{ label }}
    </div>
    <div class="pp-stat-value">
      {{ value }}
      <span v-if="suffix" class="pp-stat-suffix">{{ suffix }}</span>
    </div>
    <div v-if="hint" class="pp-stat-hint">{{ hint }}</div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string
    value: string | number
    suffix?: string
    hint?: string
    icon?: string
    tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'ai'
  }>(),
  { tone: 'default' }
)
</script>

<style scoped>
.pp-stat-hint {
  margin-top: var(--pp-space-1);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
}
</style>
