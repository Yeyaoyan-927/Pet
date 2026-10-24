<!--
  根组件：只放 router-view 与全局过渡，不放业务逻辑。
-->

<template>
  <router-view v-slot="{ Component, route }">
    <transition name="pp-fade" mode="out-in">
      <component :is="Component" :key="route.path" />
    </transition>
  </router-view>
</template>

<script setup lang="ts"></script>
