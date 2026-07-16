// ── 공용 도메인 타입 ──────────────────────────────────────────────────────

export type Role = "admin" | "user";

export interface AuthUser {
  username: string;
  role: Role;
}

export type Channel = "eo" | "tir";

export interface Outpost {
  id: string;
  x_ratio: number;
  y_ratio: number;
  info: string;
  source?: string;
  video_eo_name?: string | null;
  video_tir_name?: string | null;
  active_channel?: Channel;
}

export interface Camera {
  id: string;
  name: string;
}

// ── 영상 분석(사전 분석 + 타임라인 오버레이) ──────────────────────────────
export type AnalysisStatusValue = "idle" | "analyzing" | "ready" | "error";

export interface AnalysisStatus {
  status: AnalysisStatusValue;
  progress: number;
  error?: string;
  /** "image"면 탐지 대상 없는 정적 배경 컷 — <video> 대신 <img>로 표시하고 분석/타임라인을 건너뜁니다. */
  kind?: "video" | "image";
}

export interface DetectionBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface TimelineDetection {
  class_name: string;
  confidence: number;
  box: DetectionBox;
}

/** 타임라인 항목 하나 — t는 영상 기준 ms. */
export interface TimelineEntry {
  t: number;
  dets: TimelineDetection[];
}

export interface Detection {
  id: number;
  camera: string;
  class_name: string;
  score: number;
  created_at: string;
  uri?: string;
  content_type?: string;
}

export interface ToastEvent {
  id: number;
  camera: string;
  class_name: string;
  ts: number;
}

export interface SystemStatus {
  rds: "ok" | "error";
  s3: "ok" | "error";
}

export interface LogEntry {
  id: number;
  job_id?: string;
  camera: string;
  status: string;
  remarks?: string;
  frame_index?: number;
  created_at: string;
  input_type?: string;
  class_name: string;
  score: number;
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  uri?: string;
  content_type?: string;
}

export interface LogUpdate {
  id: number;
  class_name?: string;
  score?: number;
  camera?: string;
  status?: string;
  remarks?: string;
}

export interface LogBatchUpdate {
  updates: LogUpdate[];
  deletes: number[];
}
