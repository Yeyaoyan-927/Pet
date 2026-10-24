<!--
  手绘扁平插画（犬 / 猫 / 爪印），内联 SVG，颜色取设计令牌。
  用于欢迎区、空状态与错误页，避免依赖外部图片。
-->

<template>
  <div class="pp-illustration" :style="{ width: `${size}px`, height: `${size}px` }">
    <!-- 手绘扁平圆润风格：线条柔和、无锐角、暖色填充 -->
    <svg v-if="type === 'dog'" viewBox="0 0 120 120" fill="none">
      <ellipse cx="60" cy="104" rx="34" ry="6" fill="#F5F0E8" />
      <path d="M28 62c-8-4-12-14-8-20 4-6 14-4 18 4" fill="#EFDCC6" stroke="#E0C9AC" stroke-width="2.5" stroke-linejoin="round" />
      <path d="M92 62c8-4 12-14 8-20-4-6-14-4-18 4" fill="#EFDCC6" stroke="#E0C9AC" stroke-width="2.5" stroke-linejoin="round" />
      <path d="M60 30c20 0 32 14 32 32 0 20-14 32-32 32S28 82 28 62c0-18 12-32 32-32z" fill="#F7E7D3" stroke="#E5D0B4" stroke-width="2.5" />
      <ellipse cx="46" cy="58" rx="4.2" ry="5" fill="#5A5148" />
      <ellipse cx="74" cy="58" rx="4.2" ry="5" fill="#5A5148" />
      <circle cx="47.4" cy="56.4" r="1.4" fill="#fff" />
      <circle cx="75.4" cy="56.4" r="1.4" fill="#fff" />
      <ellipse cx="60" cy="72" rx="7" ry="5.2" fill="#5A5148" />
      <path d="M60 77v4" stroke="#5A5148" stroke-width="2.4" stroke-linecap="round" />
      <path d="M53 83c2.6 2.4 12 2.4 14 0" stroke="#5A5148" stroke-width="2.4" stroke-linecap="round" />
      <ellipse cx="36" cy="74" rx="6" ry="4" fill="#F2B8A6" opacity=".65" />
      <ellipse cx="84" cy="74" rx="6" ry="4" fill="#F2B8A6" opacity=".65" />
    </svg>

    <svg v-else-if="type === 'cat'" viewBox="0 0 120 120" fill="none">
      <ellipse cx="60" cy="104" rx="34" ry="6" fill="#F5F0E8" />
      <path d="M30 44l4-22 18 12z" fill="#F0E7F7" stroke="#DFD2EE" stroke-width="2.5" stroke-linejoin="round" />
      <path d="M90 44l-4-22-18 12z" fill="#F0E7F7" stroke="#DFD2EE" stroke-width="2.5" stroke-linejoin="round" />
      <path d="M60 30c20 0 32 14 32 32 0 20-14 30-32 30S28 82 28 62c0-18 12-32 32-32z" fill="#F8F2FC" stroke="#E2D6EF" stroke-width="2.5" />
      <path d="M42 58c3-3 9-3 12 0" stroke="#5A5148" stroke-width="2.6" stroke-linecap="round" />
      <path d="M66 58c3-3 9-3 12 0" stroke="#5A5148" stroke-width="2.6" stroke-linecap="round" />
      <path d="M60 72l-4 3h8z" fill="#F2A65A" />
      <path d="M60 75v3" stroke="#5A5148" stroke-width="2.2" stroke-linecap="round" />
      <path d="M54 82c2.4 2.2 9.6 2.2 12 0" stroke="#5A5148" stroke-width="2.2" stroke-linecap="round" />
      <path d="M26 62h-12M24 70l-11 4M94 62h12M96 70l11 4" stroke="#DFD2EE" stroke-width="2.4" stroke-linecap="round" />
    </svg>

    <svg v-else viewBox="0 0 120 120" fill="none">
      <ellipse cx="60" cy="104" rx="34" ry="6" fill="#F5F0E8" />
      <circle cx="60" cy="64" r="30" fill="#EAF2FB" stroke="#D3E3F5" stroke-width="2.5" />
      <ellipse cx="48" cy="60" rx="4" ry="4.8" fill="#5A5148" />
      <ellipse cx="72" cy="60" rx="4" ry="4.8" fill="#5A5148" />
      <path d="M54 76c3 3 9 3 12 0" stroke="#5A5148" stroke-width="2.4" stroke-linecap="round" />
      <g fill="#8FBDE8" opacity=".8">
        <ellipse cx="60" cy="30" rx="6" ry="7.6" />
        <ellipse cx="48" cy="22" rx="3" ry="4" />
        <ellipse cx="56" cy="17" rx="3" ry="4" />
        <ellipse cx="64" cy="17" rx="3" ry="4" />
        <ellipse cx="72" cy="22" rx="3" ry="4" />
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ type?: 'dog' | 'cat' | 'paw'; size?: number }>(), {
  type: 'dog',
  size: 120
})
</script>

<style scoped>
.pp-illustration {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.pp-illustration svg {
  width: 100%;
  height: 100%;
}
</style>
