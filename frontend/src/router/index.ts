/**
 * 路由表 + 权限守卫 + 菜单元信息。
 *
 * - `layoutRoutes` 的顺序**就是菜单顺序**；
 * - `meta.group` 决定归属分组，`meta.pinned`（top/bottom）决定是否脱离分组固定显示；
 * - `meta.roles` 控制哪些角色可见，越权访问由守卫重定向到 403。
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'
import type { UserRole } from '@/types'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    icon?: string
    group?: string
    roles?: UserRole[]
    breadcrumb?: string[]
    public?: boolean
    hidden?: boolean
  }
}

export const layoutRoutes: RouteRecordRaw[] = [
  /* ---------------- 宠主端 ---------------- */
  {
    path: 'user/home',
    name: 'UserHome',
    component: () => import('@/views/user/Home.vue'),
    meta: { title: '我的首页', icon: 'HomeFilled', group: '洗护预约', pinned: 'top', pinnedOrder: 2, roles: ['customer'], breadcrumb: ['宠主服务', '我的首页'] }
  },
  {
    path: 'user/pets',
    name: 'UserPets',
    component: () => import('@/views/user/Pets.vue'),
    meta: { title: '宠物档案', icon: 'Star', group: '洗护预约', roles: ['customer'], breadcrumb: ['宠主服务', '宠物档案'] }
  },
  {
    path: 'user/pets/edit/:id?',
    name: 'UserPetEdit',
    component: () => import('@/views/user/PetEdit.vue'),
    // 宠主维护自己的档案，店员/店长从「客户档案」进入维护客户档案
    meta: { title: '档案编辑', roles: ['customer', 'staff', 'manager'], hidden: true, breadcrumb: ['宠物档案', '档案编辑'] }
  },
  {
    path: 'user/appointment/create',
    name: 'UserAppointmentCreate',
    component: () => import('@/views/user/AppointmentCreate.vue'),
    meta: { title: '发起预约', icon: 'Calendar', group: '洗护预约', roles: ['customer'], breadcrumb: ['宠主服务', '发起预约'] }
  },
  {
    path: 'user/appointments',
    name: 'UserAppointments',
    component: () => import('@/views/user/Appointments.vue'),
    meta: { title: '我的预约', icon: 'Tickets', group: '洗护预约', roles: ['customer'], breadcrumb: ['宠主服务', '我的预约'] }
  },
  {
    path: 'user/messages',
    name: 'UserMessages',
    component: () => import('@/views/user/Messages.vue'),
    // 消息中心对三种角色都开放（店员/店长同样接收门店通知）
    meta: { title: '消息中心', icon: 'Bell', group: '洗护预约', pinned: 'top', pinnedOrder: 1, breadcrumb: ['消息中心', '消息列表'] }
  },
  {
    path: 'user/boarding',
    name: 'UserBoarding',
    component: () => import('@/views/user/Boarding.vue'),
    meta: { title: '宠物寄养', icon: 'HomeFilled', group: '宠物之家', roles: ['customer'], breadcrumb: ['宠主服务', '宠物寄养'] }
  },
  {
    path: 'user/boarding/create',
    name: 'UserBoardingCreate',
    component: () => import('@/views/user/BoardingCreate.vue'),
    meta: { title: '新建寄养', roles: ['customer'], hidden: true, breadcrumb: ['宠物寄养', '新建寄养'] }
  },
  {
    path: 'user/boarding/:id',
    name: 'UserBoardingDetail',
    component: () => import('@/views/user/BoardingDetail.vue'),
    meta: { title: '寄养详情', roles: ['customer'], hidden: true, breadcrumb: ['宠物寄养', '寄养详情'] }
  },
  {
    path: 'user/goods',
    name: 'UserGoods',
    component: () => import('@/views/user/Goods.vue'),
    meta: { title: '宠物用品', icon: 'ShoppingBag', group: '宠物之家', roles: ['customer'], breadcrumb: ['宠主服务', '宠物用品'] }
  },
  {
    path: 'user/goods/orders',
    name: 'UserGoodsOrders',
    component: () => import('@/views/user/GoodsOrders.vue'),
    meta: { title: '用品订单', roles: ['customer'], hidden: true, breadcrumb: ['宠物用品', '我的订单'] }
  },
  {
    path: 'user/camera',
    name: 'UserCamera',
    component: () => import('@/views/user/Camera.vue'),
    meta: { title: '宠物实景', icon: 'VideoCamera', group: '宠物之家', roles: ['customer'], breadcrumb: ['宠主服务', '宠物实景'] }
  },
  {
    path: 'user/chat',
    name: 'UserChat',
    // 三角色共用同一对话组件，差异由后端 capabilities 下发的工具画像决定
    component: () => import('@/views/chat/index.vue'),
    meta: { title: 'AI 洗护助手', icon: 'MagicStick', group: '洗护预约', pinned: 'bottom', roles: ['customer'], breadcrumb: ['宠主服务', 'AI 洗护助手'] }
  },
  /* ---------------- 店员 / 店长端 ---------------- */
  {
    path: 'staff/home',
    name: 'StaffHome',
    component: () => import('@/views/staff/Home.vue'),
    meta: { title: '门店看板', icon: 'DataBoard', group: '洗护预约', pinned: 'top', pinnedOrder: 2, roles: ['staff', 'manager'], breadcrumb: ['门店运营', '门店看板'] }
  },
  {
    path: 'staff/appointments',
    name: 'StaffAppointments',
    component: () => import('@/views/staff/Appointments.vue'),
    meta: { title: '预约管理', icon: 'Calendar', group: '洗护预约', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '预约管理'] }
  },
  {
    path: 'staff/risk',
    name: 'StaffRisk',
    component: () => import('@/views/staff/Risk.vue'),
    meta: { title: '风险复核', icon: 'WarnTriangleFilled', group: '洗护预约', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '风险复核'] }
  },
  {
    path: 'staff/pets',
    name: 'StaffPets',
    component: () => import('@/views/staff/Pets.vue'),
    meta: { title: '客户档案', icon: 'UserFilled', group: '宠物之家', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '客户档案'] }
  },
  {
    path: 'staff/wash-records',
    name: 'StaffWashRecords',
    component: () => import('@/views/staff/WashRecords.vue'),
    meta: { title: '洗护记录', icon: 'Sunny', group: '宠物之家', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '洗护记录'] }
  },
  {
    path: 'schedule',
    name: 'Schedule',
    component: () => import('@/views/schedule/index.vue'),
    meta: { title: '门店排期', icon: 'Grid', group: '洗护预约', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '门店排期'] }
  },
  {
    path: 'staff/boarding',
    name: 'StaffBoarding',
    component: () => import('@/views/staff/Boarding.vue'),
    meta: { title: '寄养管理', icon: 'Van', group: '宠物之家', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '寄养管理'] }
  },
  {
    path: 'staff/rooms',
    name: 'StaffRooms',
    component: () => import('@/views/staff/Rooms.vue'),
    meta: { title: '宠舍管理', icon: 'House', group: '宠物之家', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '宠舍管理'] }
  },
  {
    path: 'staff/goods',
    name: 'StaffGoods',
    component: () => import('@/views/staff/Goods.vue'),
    meta: { title: '用品管理', icon: 'ShoppingBag', group: '宠物之家', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '用品管理'] }
  },
  {
    path: 'staff/camera',
    name: 'StaffCamera',
    component: () => import('@/views/staff/Camera.vue'),
    meta: { title: '实景采集', icon: 'VideoCamera', group: '宠物之家', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '实景采集'] }
  },
  {
    // 菜单顺序即本数组顺序：AI 助手作为入口放在「门店运营」板块最后
    path: 'staff/chat',
    name: 'StaffChat',
    component: () => import('@/views/chat/index.vue'),
    meta: { title: '运营助理', icon: 'MagicStick', group: '洗护预约', pinned: 'bottom', roles: ['staff', 'manager'], breadcrumb: ['门店运营', '运营助理'] }
  },

  /* ---------------- 数据统计 ---------------- */
  {
    path: 'report/summary',
    name: 'ReportSummary',
    component: () => import('@/views/report/Summary.vue'),
    meta: { title: '经营报表', icon: 'TrendCharts', group: '数据统计', roles: ['staff', 'manager'], breadcrumb: ['数据统计', '经营报表'] }
  },
  {
    path: 'report/boarding',
    name: 'ReportBoarding',
    component: () => import('@/views/report/Boarding.vue'),
    meta: { title: '寄养看板', icon: 'House', group: '数据统计', roles: ['manager'], breadcrumb: ['数据统计', '寄养看板'] }
  },
  {
    path: 'report/goods',
    name: 'ReportGoods',
    component: () => import('@/views/report/Goods.vue'),
    meta: { title: '用品看板', icon: 'ShoppingBag', group: '数据统计', roles: ['manager'], breadcrumb: ['数据统计', '用品看板'] }
  },
  {
    path: 'report/export',
    name: 'ReportExport',
    component: () => import('@/views/report/Export.vue'),
    meta: { title: '数据导出', icon: 'Download', group: '数据统计', roles: ['manager'], breadcrumb: ['数据统计', '数据导出'] }
  },
  {
    path: 'report/audit',
    name: 'ReportAudit',
    component: () => import('@/views/report/Audit.vue'),
    meta: { title: '审计日志', icon: 'Document', group: '数据统计', roles: ['manager'], breadcrumb: ['数据统计', '审计日志'] }
  },
  /* ---------------- 系统管理 ---------------- */
  {
    path: 'staff/knowledge',
    name: 'StaffKnowledge',
    component: () => import('@/views/staff/Knowledge.vue'),
    meta: { title: 'RAG 知识库', icon: 'Collection', group: '系统管理', roles: ['staff', 'manager'], breadcrumb: ['系统管理', 'RAG 知识库'] }
  },
  {
    path: 'staff/settings',
    name: 'StaffSettings',
    component: () => import('@/views/staff/Settings.vue'),
    meta: { title: '门店配置', icon: 'Setting', group: '系统管理', roles: ['manager'], breadcrumb: ['系统管理', '门店配置'] }
  },
  {
    path: 'staff/users',
    name: 'StaffUsers',
    component: () => import('@/views/staff/Users.vue'),
    meta: { title: '员工账号', icon: 'User', group: '系统管理', roles: ['manager'], breadcrumb: ['系统管理', '员工账号'] }
  },

]

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', public: true }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: layoutRoutes
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/error/403.vue'),
    meta: { title: '无权访问', public: true, hidden: true }
  },
  {
    // 兼容旧链接：店长的对话入口已并入「运营助理」，不再单列菜单（同一页面 + 同一套工具画像）
    path: '/manager/chat',
    redirect: '/staff/chat'
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/404.vue'),
    meta: { title: '页面不存在', public: true, hidden: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

const APP_TITLE = 'PawPilot · 宠物洗护门店智能预约与档案助手'

router.beforeEach(async (to) => {
  const store = useUserStore()
  document.title = to.meta.title ? `${to.meta.title} · ${APP_TITLE}` : APP_TITLE

  if (to.meta.public) {
    // 已登录用户访问登录页 → 直接进角色首页
    if (to.path === '/login' && store.isLogin && store.userInfo) {
      return { path: store.homePath }
    }
    return true
  }

  if (!store.isLogin) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!store.userInfo) {
    try {
      await store.fetchMe()
    } catch {
      store.reset()
      return { path: '/login' }
    }
  }

  const roles = to.meta.roles
  if (roles && roles.length && !roles.includes(store.role)) {
    // 角色不匹配：送达统一的 403 页并携带来源，便于用户返回自己的首页
    return { path: '/403', query: { from: to.fullPath } }
  }

  // 访问根路径时按角色分流
  if (to.path === '/') return { path: store.homePath }
  return true
})

export default router
