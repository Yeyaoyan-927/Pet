<!--
  宠物头像：圆形渐变底 + 物种 emoji + 白描边，尺寸由 size 控制。
-->
<template>
  <div class="pp-pet-avatar" :style="style">
    <span class="pp-pet-avatar__emoji">{{ emoji }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    species?: string | null
    name?: string | null
    size?: number
    ring?: boolean
  }>(),
  { species: 'dog', size: 44, ring: true }
)

const emoji = computed(() => {
  if (props.species === 'cat') return '🐱'
  if (props.species === 'other') return '🐾'
  return '🐶'
})

const bg = computed(() => {
  const palette: Record<string, string> = {
    dog: 'linear-gradient(135deg, #e8f2fb 0%, #fdf3e7 100%)',
    cat: 'linear-gradient(135deg, #f1edfa 0%, #eaf6e9 100%)',
    other: 'linear-gradient(135deg, #edf5fb 0%, #f5f0e8 100%)'
  }
  return palette[props.species || 'dog'] || palette.dog
})

const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.round(props.size * 0.5)}px`,
  background: bg.value,
  boxShadow: props.ring ? '0 0 0 2px #fff, 0 2px 8px rgba(61,58,53,.08)' : 'none'
}))
</script>

<style scoped>
.pp-pet-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  flex: none;
  user-select: none;
}

.pp-pet-avatar__emoji {
  line-height: 1;
  transform: translateY(1px);
}
</style>
