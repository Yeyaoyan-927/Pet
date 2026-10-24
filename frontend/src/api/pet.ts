/**
 * 宠物档案接口：列表、详情、增删改、疫苗记录。
 * 档案里的过敏史/攻击倾向会直接影响风险判别与用品推荐，编辑后建议重新评估风险。
 */

import http from './request'
import type { Pet, VaccineRecord } from '@/types'

export const petApi = {
  list: (keyword?: string) => http.get<never, Pet[]>('/pets', { params: { keyword } }),
  detail: (id: number) => http.get<never, Pet>(`/pets/${id}`),
  create: (data: Partial<Pet>) => http.post<never, Pet>('/pets', data),
  update: (id: number, data: Partial<Pet>) => http.put<never, Pet>(`/pets/${id}`, data),
  remove: (id: number) => http.delete<never, null>(`/pets/${id}`),
  vaccines: (id: number) => http.get<never, VaccineRecord[]>(`/pets/${id}/vaccines`),
  addVaccine: (id: number, data: Partial<VaccineRecord>) =>
    http.post<never, { id: number }>(`/pets/${id}/vaccines`, data)
}
