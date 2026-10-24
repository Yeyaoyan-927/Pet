/**
 * 实景接口：可观看列表、观看凭证、设备管理、抓拍相册、看板。
 * 宠主端播放走「单帧轮询」（/camera/frame/{token}），凭证是短期 token，不能带 Authorization 头；
 * MJPEG（/camera/stream/{token}）保留给需要连续流的调用方。
 */

import http from './request'
import type {
  CameraDeviceItem,
  CameraLiveItem,
  CameraSessionOut,
  CameraSnapshotItem,
  CameraStats
} from '@/types'

/** MJPEG 拉流地址：<img> 无法携带 Authorization，所以走短期 token 路径鉴权 */
export const cameraStreamUrl = (token: string) => `/api/v1/camera/stream/${token}`

/** 单帧轮询地址：宠主端统一走这里，真实帧 / 演示帧由后端按当前状态自适应返回 */
export const cameraFrameUrl = (token: string) => `/api/v1/camera/frame/${token}`

export const cameraApi = {
  meta: () =>
    http.get<never, { providers: Record<string, string>; device_status: Record<string, string>; rules: Record<string, number>; privacy: string }>(
      '/camera/meta'
    ),
  live: () => http.get<never, CameraLiveItem[]>('/camera/live'),
  openSession: (orderId: number) =>
    http.post<never, CameraSessionOut>('/camera/sessions', { order_id: orderId }),
  endSession: (sessionId: number) =>
    http.post<never, { id: number; duration_seconds: number }>(`/camera/sessions/${sessionId}/end`),
  devices: () => http.get<never, CameraDeviceItem[]>('/camera/devices'),
  saveDevice: (data: {
    room_id: number
    name: string
    provider_type: string
    stream_url?: string
    fps?: number
    resolution?: string
  }) => http.post<never, CameraDeviceItem>('/camera/devices', data),
  setDeviceStatus: (id: number, status: string) =>
    http.patch<never, CameraDeviceItem>(`/camera/devices/${id}/status`, { status }),
  heartbeat: (id: number) => http.post<never, { id: number; status: string }>(`/camera/devices/${id}/heartbeat`),
  snapshots: () => http.get<never, CameraSnapshotItem[]>('/camera/snapshots'),
  /** 从当前帧抓拍并落盘（实时流不落盘，抓拍才落盘） */
  capture: (token: string, note?: string) =>
    http.post<never, { id: number; image_url: string }>(`/camera/snapshots/${token}`, null, {
      params: { note }
    }),
  addSnapshot: (data: { order_id: number; image_url: string; note?: string }) =>
    http.post<never, { id: number; image_url: string }>('/camera/snapshots', data),
  stats: (params: { start: string; end: string }) =>
    http.get<never, CameraStats>('/camera/stats', { params })
}
