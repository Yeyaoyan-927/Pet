/**
 * 用品接口：商品列表/详情、购物车、订单、核销、库存、商品维护、看板。
 * 过敏校验结果在商品与购物车行上以 unsafe/conflicts 返回，前端只负责展示与拦截提交。
 */

import http from './request'
import type {
  CartLine,
  GoodsDashboard,
  GoodsOrder,
  GoodsProduct,
  PageData
} from '@/types'

export interface GoodsProductQuery {
  category?: string
  keyword?: string
  species?: string
  pet_id?: number
  sort?: string
}

export const goodsApi = {
  products: (params: GoodsProductQuery) =>
    http.get<never, { items: GoodsProduct[]; total: number; categories: Record<string, string> }>(
      '/goods/products',
      { params }
    ),
  product: (id: number, petId?: number) =>
    http.get<never, GoodsProduct>(`/goods/products/${id}`, { params: { pet_id: petId } }),
  cart: () =>
    http.get<never, { items: CartLine[]; total: number; count: number }>('/goods/cart'),
  addCart: (data: { sku_id: number; quantity: number; pet_id?: number | null }) =>
    http.post<never, { sku_id: number; quantity: number; warnings: string[] }>('/goods/cart', data),
  updateCart: (id: number, quantity: number) =>
    http.patch<never, { id: number; quantity: number }>(`/goods/cart/${id}`, { quantity }),
  removeCart: (id: number) => http.delete<never, { id: number; quantity: number }>(`/goods/cart/${id}`),
  clearCart: () => http.post<never, { removed: number }>('/goods/cart/clear'),
  createOrder: (data: {
    items?: { sku_id: number; quantity: number; pet_id?: number | null }[]
    pickup_method: string
    address?: string
    remark?: string
    pet_id?: number | null
    idempotent_key?: string
  }) => http.post<never, GoodsOrder>('/goods/orders', data),
  orders: (params: { status?: string; page?: number; size?: number }) =>
    http.get<never, PageData<GoodsOrder>>('/goods/orders', { params }),
  order: (id: number) => http.get<never, GoodsOrder>(`/goods/orders/${id}`),
  cancelOrder: (id: number, reason: string) =>
    http.post<never, { id: number; status: string }>(`/goods/orders/${id}/cancel`, {
      target_status: 'cancelled',
      reason
    }),
  changeStatus: (id: number, data: { target_status: string; reason?: string; pay_status?: string }) =>
    http.post<never, { id: number; status: string; status_label: string; pickup_code: string }>(
      `/goods/orders/${id}/status`,
      data
    ),
  verifyPickup: (pickup_code: string, pay_status = 'paid_offline') =>
    http.post<never, { id: number; order_no: string; total_amount: number }>('/goods/pickup/verify', {
      pickup_code,
      pay_status
    }),
  stock: (onlyLow = false) =>
    http.get<never, { items: { sku_id: number; product_name: string; spec_name: string; stock: number; warn_threshold: number; low_stock: boolean; price: number }[]; low_count: number }>(
      '/goods/stock',
      { params: { only_low: onlyLow } }
    ),
  updateStock: (skuId: number, stock: number, remark?: string) =>
    http.patch<never, { sku_id: number; before: number; after: number }>(
      `/goods/skus/${skuId}/stock`,
      { stock, remark }
    ),
  /** 门店侧商品维护列表（含已下架） */
  adminProducts: (keyword?: string) =>
    http.get<never, { items: GoodsProduct[]; total: number; categories: Record<string, string> }>(
      '/goods/admin/products',
      { params: { keyword } }
    ),
  saveProduct: (data: {
    id?: number
    name: string
    brand?: string
    category: string
    species: string
    stage: string
    size: string
    selling_points?: string
    allergy_tags?: string
    taboo_tags?: string
    detail?: string
    status: string
    sort_no?: number
    skus: { spec_name: string; price_cents: number; weight_g?: number; stock: number; warn_threshold?: number }[]
  }) => http.post<never, { id: number; name: string }>('/goods/products', data),
  deleteProduct: (id: number) =>
    http.delete<never, { id: number; name: string }>(`/goods/products/${id}`),
  dashboard: (params: { start: string; end: string }) =>
    http.get<never, GoodsDashboard>('/goods/dashboard', { params })
}
