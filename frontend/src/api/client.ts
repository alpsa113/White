// api/client.ts — 타입이 지정된 얇은 fetch 래퍼. 백엔드 REST API 계약(README 참고)에 맞춰 호출합니다.
import type {
  AnalysisStatus,
  AuthUser,
  Camera,
  Channel,
  LogBatchUpdate,
  LogEntry,
  Detection,
  Outpost,
  Role,
  SystemStatus,
  TimelineEntry,
  ToastEvent,
} from "../types";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* ignore non-json error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ── Auth ─────────────────────────────────────────────────────────────────
export function login(username: string, password: string, role: Role): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, role }),
  });
}

// ── Outposts ─────────────────────────────────────────────────────────────
export function getOutposts(): Promise<Outpost[]> {
  return request<Outpost[]>("/api/outposts");
}

export function createOutpost(x_ratio: number, y_ratio: number): Promise<Outpost> {
  return request<Outpost>("/api/outposts", {
    method: "POST",
    body: JSON.stringify({ x_ratio, y_ratio }),
  });
}

export function updateOutpost(id: string, patch: { info?: string; source?: string }): Promise<Outpost> {
  return request<Outpost>(`/api/outposts/${id}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

export function deleteOutpost(id: string): Promise<void> {
  return request<void>(`/api/outposts/${id}`, { method: "DELETE" });
}

export function outpostMapImageUrl(): string {
  return `${API_BASE_URL}/api/outposts/map-image`;
}

// ── Cameras ──────────────────────────────────────────────────────────────
export function getCameras(): Promise<Camera[]> {
  return request<Camera[]>("/api/cameras");
}

export function setCameraChannel(id: string, channel: Channel): Promise<void> {
  return request<void>(`/api/cameras/${id}/channel`, {
    method: "POST",
    body: JSON.stringify({ channel }),
  });
}

/** 원본 영상 파일 URL(HTTP Range 지원) — <video src="..."> 로 직접 사용. */
export function videoUrl(cameraId: string, channel: Channel): string {
  return `${API_BASE_URL}/api/cameras/${cameraId}/video?channel=${channel}`;
}

export function getAnalysisStatus(cameraId: string, channel: Channel): Promise<AnalysisStatus> {
  return request<AnalysisStatus>(`/api/cameras/${cameraId}/analysis-status?channel=${channel}`);
}

export function getDetectionsTimeline(cameraId: string, channel: Channel): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`/api/cameras/${cameraId}/detections-timeline?channel=${channel}`);
}

// ── Detections ───────────────────────────────────────────────────────────
export function getRecentDetections(limit = 50): Promise<Detection[]> {
  return request<Detection[]>(`/api/detections/recent?limit=${limit}`);
}

export function getRecentToasts(limit = 20): Promise<ToastEvent[]> {
  return request<ToastEvent[]>(`/api/toasts/recent?limit=${limit}`);
}

// ── Settings ─────────────────────────────────────────────────────────────
export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>("/api/settings/system-status");
}

// ── Logs ─────────────────────────────────────────────────────────────────
export function getLogs(): Promise<LogEntry[]> {
  return request<LogEntry[]>("/api/logs");
}

export function saveLogEdits(batch: LogBatchUpdate): Promise<void> {
  return request<void>("/api/logs", {
    method: "PUT",
    body: JSON.stringify(batch),
  });
}

export function logSnapshotUrl(id: number): string {
  return `${API_BASE_URL}/api/logs/${id}/snapshot`;
}

export { ApiError };
