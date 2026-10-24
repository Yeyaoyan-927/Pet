<!--
  风险徽标：低/中/高对应抹茶绿 / 蜜桃橙 / 珊瑚红，用于列表与详情。
-->
<template>
  <span v-if="!level" class="pp-dim">待判别</span>
  <span v-else class="pp-risk" :style="{ backgroundColor: tone.bg, color: tone.color }">
    <el-icon :size="12"><component :is="icon" /></el-icon>
    {{ RISK_LEVEL_META[level]?.label || level }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RISK_LEVEL_META } from '@/utils/dict'

const props = defineProps<{ level?: string | null }>()

const tone = computed(
  () => RISK_LEVEL_META[props.level || ''] || { bg: 'var(--pp-neutral-bg)', color: '#857b6e' }
)

const icon = computed(() => {
  if (props.level === 'high') return 'WarningFilled'
  if (props.level === 'low') return 'InfoFilled'
  return 'CircleCheckFilled'
})
</script>

<style scoped>
.pp-risk {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 10px;
  border-radius: var(--pp-radius-pill);
  font-size: var(--pp-fs-xs);
  font-weight: var(--pp-fw-semibold);
  white-space: nowrap;
}
</style>
