/**
 * 全局 UI 状态：侧边栏折叠、当前主题等（不入库，刷新重置）。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/** 全局 UI 状态：侧边栏折叠、抽屉菜单（中小屏）、面包屑。 */
export const useAppStore = defineStore('app', () => {
  const collapsed = ref(false)
  const drawerOpen = ref(false)
  const breadcrumb = ref<string[]>([])

  const isNarrow = computed(() => drawerOpen.value)

  function toggleCollapse() {
    collapsed.value = !collapsed.value
  }

  function setCollapsed(value: boolean) {
    collapsed.value = value
  }

  function openDrawer() {
    drawerOpen.value = true
  }

  function closeDrawer() {
    drawerOpen.value = false
  }

  function setBreadcrumb(items: string[]) {
    breadcrumb.value = items
  }

  return {
    collapsed,
    drawerOpen,
    breadcrumb,
    isNarrow,
    toggleCollapse,
    setCollapsed,
    openDrawer,
    closeDrawer,
    setBreadcrumb
  }
})
