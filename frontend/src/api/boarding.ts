/**
 * 寄养接口：房型、报价、下单、状态流转、照护日志、接送任务、看板与房型维护。
 * 金额后端以「分」返回，这里只做类型透传，展示层再转元。
 */

import http from './request'
import type {
  BoardingCareLog,
  BoardingDashboard,
  BoardingEarlyPickup,
  BoardingEligibility,
  BoardingMeta,
  BoardingOrder,
  BoardingPickupTask,
  BoardingQuote,
  BoardingRoom,
  PageData
} from '@/types'

/** 宠舍新增/编辑入参：facilities 是逗号分隔字符串（出参才是数组），两者别复用同一类型 */
export interface BoardingRoomPayload {
  id?: number
  room_no: string
  room_type: string
  name: string
  species_limit: string
  weight_limit?: number
  ratio_percent: number
  capacity: number
  facilities?: string
  remark?: string
}

export interface BoardingOrderQuery {
  status?: string
  pet_id?: number
  page?: number
  size?: number
}

/** 照护日志入参（abnormal 前端为布尔，后端落库为 0/1） */
export interface BoardingCareLogPayload {
  log_date?: string
  eating?: string
  drinking?: string
  stool?: string
  spirit?: string
  activity?: string
  abnormal?: boolean
  abnormal_note?: string
  photos?: string[]
  sop_checked?: string[]
}

export interface BoardingCreatePayload {
  pet_id: number
  room_id: number
  check_in_date: string
  check_out_date: string
  feeding_plan?: string
  food_note?: string
  dropoff_method?: string
  pickup_back_method?: string
  shipping_address?: string
  shipping_slot?: string
  emergency_contact?: string
  emergency_phone?: string
  medical_authorized?: boolean
  terms_confirmed: boolean
  care_items?: { item_type: string; content: string; frequency?: string; need_staff?: boolean }[]
  remark?: string
  idempotent_key?: string
}

export const boardingApi = {
  /** 字典与门店定价规则 */
  meta: () => http.get<never, BoardingMeta>('/boarding/meta'),

  /** 房型列表（传宠物与日期可拿到可订状态与预估日费） */
  /** 寄养资格预检：下单前先问一次，拿到「能不能订 + 原因 + 补救信息」 */
  eligibility: (petId: number, checkIn: string) =>
    http.get<never, BoardingEligibility>('/boarding/eligibility', {
      params: { pet_id: petId, check_in: checkIn }
    }),
  rooms: (params?: { pet_id?: number; check_in?: string; check_out?: string }) =>
    http.get<never, BoardingRoom[]>('/boarding/rooms', { params }),

  /** 费用预估（不落库） */
  quote: (params: {
    pet_id: number
    room_id: number
    check_in_date: string
    check_out_date: string
    feeding_plan?: string
    dropoff_method?: string
    pickup_back_method?: string
  }) => http.get<never, BoardingQuote>('/boarding/quote', { params }),

  createOrder: (data: BoardingCreatePayload) =>
    http.post<never, BoardingOrder>('/boarding/orders', data),

  orders: (params: BoardingOrderQuery) =>
    http.get<never, PageData<BoardingOrder>>('/boarding/orders', { params }),

  orderDetail: (id: number) => http.get<never, BoardingOrder>(`/boarding/orders/${id}`),

  cancelOrder: (id: number, reason: string) =>
    http.post<never, { id: number; status: string }>(`/boarding/orders/${id}/cancel`, {
      target_status: 'cancelled',
      reason
    }),

  extendOrder: (id: number, check_out_date: string) =>
    http.post<never, BoardingOrder>(`/boarding/orders/${id}/extend`, { check_out_date }),

  changeStatus: (
    id: number,
    data: { target_status: string; reason?: string; checkin_note?: string; checkout_note?: string }
  ) => http.post<never, { id: number; status: string; status_label: string; settle_note?: string }>(
    `/boarding/orders/${id}/status`,
    data
  ),

  careLogs: (id: number) => http.get<never, BoardingCareLog[]>(`/boarding/orders/${id}/care-logs`),

  addCareLog: (id: number, data: BoardingCareLogPayload) =>
    http.post<never, BoardingCareLog>(`/boarding/orders/${id}/care-logs`, data),

  pickupTasks: (params?: { status?: string }) =>
    http.get<never, BoardingPickupTask[]>('/boarding/pickup-tasks', { params }),

  advancePickup: (taskId: number, data?: { target_status?: string; sign_off_by?: string }) =>
    http.post<never, BoardingPickupTask>(`/boarding/pickup-tasks/${taskId}/advance`, data || {}),

  dashboard: (params: { start: string; end: string }) =>
    http.get<never, BoardingDashboard>('/boarding/dashboard', { params }),

  upsertRoom: (data: BoardingRoomPayload) =>
    http.post<never, BoardingRoom>('/boarding/rooms', data),

  deleteRoom: (roomId: number) => http.delete<never, { id: number }>(`/boarding/rooms/${roomId}`),

  updateRoomStatus: (roomId: number, status: string) =>
    http.patch<never, BoardingRoom>(`/boarding/rooms/${roomId}/status`, { status }),

  // ---- 提前接回：宠主申请 → 门店审核 ----
  applyEarlyPickup: (orderId: number, data: { expect_pickup_date: string; reason?: string }) =>
    http.post<never, BoardingEarlyPickup>(`/boarding/orders/${orderId}/early-pickup`, data),

  earlyPickups: (status?: string) =>
    http.get<never, BoardingEarlyPickup[]>('/boarding/early-pickups', {
      params: status ? { status } : undefined
    }),

  reviewEarlyPickup: (reqId: number, data: { approve: boolean; note?: string }) =>
    http.post<never, BoardingEarlyPickup>(`/boarding/early-pickups/${reqId}/review`, data)
}
