<!--
  状态标签：按状态字典取中文名与语义色，统一各页面状态呈现。
-->
<template>
  <span class="pp-status" :style="{ backgroundColor: tone.bg, color: tone.color }">
    <i class="pp-status__dot" :style="{ background: tone.color }" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { APPOINTMENT_STATUS_META } from '@/utils/dict'

const props = defineProps<{ status: string; label?: string | null }>()

const tone = computed(() => {
  const meta = APPOINTMENT_STATUS_META[props.status]
  return meta ? { bg: meta.bg, color: meta.color } : { bg: 'var(--pp-neutral-bg)', color: '#857b6e' }
})

const label = computed(() => props.label || APPOINTMENT_STATUS_META[props.status]?.label || props.status)
</script>

<style scoped>
.pp-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 12px;
  border-radius: var(--pp-radius-pill);
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-medium);
  white-space: nowrap;
}

.pp-status__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
</style>
