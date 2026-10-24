<!--
  侧边栏菜单：三段式渲染「顶部固定项 → 可折叠分组 → 底部固定项」。
  固定项由路由 meta.pinned 声明（消息中心置顶、AI 入口沉底），组件不认具体标题；
  折叠状态按角色存 localStorage，固定项不参与折叠。
-->

<template>
  <nav class="pp-menu" :class="{ 'pp-menu--collapsed': collapsed }">
    <template v-for="row in rows" :key="row.key">
      <div v-if="row.kind === 'divider'" class="pp-menu__divider" />

      <!-- 分组标题：可点击折叠，整行热区 + 柔和悬浮反馈 -->
      <button
        v-else-if="row.kind === 'group'"
        type="button"
        class="pp-menu__group"
        :class="{ 'is-closed': row.closed }"
        @click="toggleGroup(row.name!)"
      >
        <span class="pp-menu__group-name">{{ row.name }}</span>
        <span class="pp-menu__group-count">{{ row.count }}</span>
        <el-icon class="pp-menu__caret" :size="12"><ArrowRight /></el-icon>
      </button>

      <router-link
        v-else
        :to="row.item!.path"
        class="pp-menu__item"
        :class="{ 'is-active': isActive(row.item!.path) }"
        @click="emit('navigate')"
      >
        <el-icon class="pp-menu__icon" :size="18">
          <component :is="row.item!.icon" />
        </el-icon>
        <span v-if="!collapsed" class="pp-menu__text">{{ row.item!.title }}</span>
        <span v-if="!collapsed && row.item!.badge" class="pp-menu__badge">{{ row.item!.badge }}</span>
      </router-link>
    </template>
  </nav>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import { layoutRoutes } from '@/router'
import { useUserStore } from '@/stores/user'
import type { UserRole } from '@/types'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ navigate: [] }>()

const route = useRoute()
const userStore = useUserStore()

const STORAGE_KEY = 'pawpilot_menu_closed_groups'

interface MenuEntry {
  path: string
  title: string
  icon: string
  badge?: number
}

/**
 * 菜单渲染成「行」的序列，而不是直接渲染分组：
 * 顶部固定项 → 分组（可折叠）→ 底部固定项。
 *
 * 为什么要有固定项（V8.1）：
 * - 消息中心是**跨模块的高频入口**，埋进分组会被折叠藏起来，所以钉在最顶；
 * - 首页 / 门店看板是各角色的「落地页」，紧跟在消息中心之后；
 * - AI 助手是**入口而非普通功能**，固定在最底部，任何分组折叠都不影响它。
 * 固定项由路由 `meta.pinned`（'top' | 'bottom'）声明，组件不写死任何标题。
 */
type Row =
  | { kind: 'divider'; key: string }
  | { kind: 'group'; key: string; name: string; count: number; closed: boolean }
  | { kind: 'item'; key: string; item: MenuEntry }

/** 按角色动态生成可见条目：meta.roles 命中当前角色且未隐藏 */
function visibleEntries(): { top: MenuEntry[]; bottom: MenuEntry[]; groups: { name: string; items: MenuEntry[] }[] } {
  const top: (MenuEntry & { order: number })[] = []
  const bottom: (MenuEntry & { order: number })[] = []
  const map = new Map<string, MenuEntry[]>()

  for (const r of layoutRoutes) {
    const meta = r.meta || {}
    if (meta.hidden || !meta.title) continue
    const roles = meta.roles as UserRole[] | undefined
    if (roles && roles.length && !roles.includes(userStore.role)) continue

    const path = `/${r.path}`.replace(/\/+/g, '/')
    const entry: MenuEntry = {
      path,
      title: String(meta.title),
      icon: String(meta.icon || 'Menu'),
      badge: path === '/user/messages' && userStore.unread ? userStore.unread : undefined
    }
    const order = Number(meta.pinnedOrder ?? 100)

    if (meta.pinned === 'top') {
      top.push({ ...entry, order })
      continue
    }
    if (meta.pinned === 'bottom') {
      bottom.push({ ...entry, order })
      continue
    }
    const group = String(meta.group || '其他')
    if (!map.has(group)) map.set(group, [])
    map.get(group)!.push(entry)
  }

  const strip = (list: (MenuEntry & { order: number })[]): MenuEntry[] =>
    list.sort((a, b) => a.order - b.order).map(({ order: _order, ...rest }) => rest)

  return {
    top: strip(top),
    bottom: strip(bottom),
    groups: [...map.entries()].map(([name, items]) => ({ name, items }))
  }
}

const layout = computed(visibleEntries)

/** 折叠状态持久化：按角色分别记忆，宠主收起「宠物之家」不会影响店员 */
const closedGroups = ref<Record<string, string[]>>(loadClosed())

function storageKey() {
  return `${STORAGE_KEY}_${userStore.role}`
}

function loadClosed(): Record<string, string[]> {
  try {
    const raw = localStorage.getItem(storageKey())
    return raw ? { [userStore.role]: JSON.parse(raw) as string[] } : {}
  } catch {
    return {}
  }
}

function currentClosed(): string[] {
  return closedGroups.value[userStore.role] || []
}

function isClosed(name: string) {
  return currentClosed().includes(name)
}

function toggleGroup(name: string) {
  const list = [...currentClosed()]
  const idx = list.indexOf(name)
  if (idx >= 0) list.splice(idx, 1)
  else list.push(name)
  closedGroups.value = { ...closedGroups.value, [userStore.role]: list }
  localStorage.setItem(storageKey(), JSON.stringify(list))
}

/** 组装渲染行：顶部固定项 → 分隔线 → 分组 → 分隔线 → 底部固定项 */
const rows = computed<Row[]>(() => {
  const { top, bottom, groups } = layout.value
  const out: Row[] = []

  for (const item of top) out.push({ kind: 'item', key: `top-${item.path}`, item })

  if (top.length && groups.length) out.push({ kind: 'divider', key: 'divider-top' })

  for (const group of groups) {
    const closed = isClosed(group.name)
    // 侧边栏收起成图标时没有分组标题的位置，退化为分隔线
    if (props.collapsed) out.push({ kind: 'divider', key: `divider-${group.name}` })
    else out.push({ kind: 'group', key: `group-${group.name}`, name: group.name, count: group.items.length, closed })

    if (closed) continue
    for (const item of group.items) {
      out.push({ kind: 'item', key: `item-${item.path}`, item })
    }
  }

  if (bottom.length && (top.length || groups.length)) out.push({ kind: 'divider', key: 'divider-bottom' })
  for (const item of bottom) out.push({ kind: 'item', key: `bottom-${item.path}`, item })

  return out
})

// 当前路由命中被折叠的分组时自动展开：刷新页面不会「找不到自己在哪」
watch(
  () => route.path,
  (path) => {
    const hit = layout.value.groups.find((g) =>
      g.items.some((i) => path === i.path || path.startsWith(`${i.path}/`))
    )
    if (hit && isClosed(hit.name)) toggleGroup(hit.name)
  },
  { immediate: true }
)

function isActive(path: string) {
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>

<style scoped>
.pp-menu {
  padding: var(--pp-space-3) var(--pp-space-2) var(--pp-space-5);
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

/* 底部固定项：整列内容不足时也贴在底部，滚到底才出现 */
.pp-menu > .pp-menu__item:last-child {
  margin-bottom: 0;
}

/* 分组标题：可点击折叠，整行热区 + 柔和悬浮反馈 */
.pp-menu__group {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  width: 100%;
  padding: var(--pp-space-2) var(--pp-space-3);
  margin-top: var(--pp-space-2);
  border: none;
  border-radius: var(--pp-radius-sm);
  background: transparent;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  text-align: left;
}

.pp-menu__group:hover {
  background: var(--pp-bg-cream);
  color: var(--pp-text-regular);
}

.pp-menu__group-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pp-menu__group-count {
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: var(--pp-radius-pill);
  background: var(--pp-bg-cream);
  color: var(--pp-text-secondary);
  font-size: 10px;
  font-family: var(--pp-font-num);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.pp-menu__group:hover .pp-menu__group-count {
  background: var(--pp-primary-lighter);
  color: var(--pp-primary-dark);
}

.pp-menu__caret {
  flex: none;
  transition: transform var(--pp-dur) var(--pp-ease);
  transform: rotate(90deg);
}

.pp-menu__group.is-closed .pp-menu__caret {
  transform: rotate(0deg);
}

.pp-menu__divider {
  height: 1px;
  margin: var(--pp-space-2) var(--pp-space-3);
  background: var(--pp-border-light);
}

.pp-menu__item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  height: 44px;
  padding: 0 var(--pp-space-3);
  margin-bottom: 2px;
  border-radius: var(--pp-radius-sm);
  color: var(--pp-text-regular);
  font-size: var(--pp-fs-base);
  transition: all var(--pp-dur-fast) var(--pp-ease);
  text-decoration: none;
}

.pp-menu--collapsed .pp-menu__item {
  justify-content: center;
  padding: 0;
}

.pp-menu__item:hover {
  background: var(--pp-bg-cream);
  color: var(--pp-primary-dark);
}

.pp-menu__item.is-active {
  background: var(--pp-primary-lighter);
  color: var(--pp-primary-dark);
  font-weight: var(--pp-fw-medium);
}

.pp-menu__item.is-active .pp-menu__icon {
  color: var(--pp-primary);
}

.pp-menu__icon {
  flex: none;
  color: var(--pp-text-secondary);
}

.pp-menu__text {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pp-menu__badge {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--pp-radius-pill);
  background: var(--pp-danger);
  color: #fff;
  font-size: var(--pp-fs-xs);
  font-family: var(--pp-font-num);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>
