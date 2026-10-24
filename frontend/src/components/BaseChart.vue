<!--
  ECharts 封装：统一主题、容器自适应（ResizeObserver）、option 变化时增量更新。
  页面只需传 option，不用关心实例生命周期。
-->
<template>
  <div ref="el" class="pp-chart" :style="{ height }"></div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ option: echarts.EChartsOption; height?: string }>(), {
  height: '300px'
})

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  chart.setOption(props.option, true)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  if (el.value) observer.observe(el.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.pp-chart {
  width: 100%;
}
</style>
