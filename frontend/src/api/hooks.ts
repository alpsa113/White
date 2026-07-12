// api/hooks.ts — REST 엔드포인트를 감싸는 react-query 훅 모음.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./client";
import type { Channel, LogBatchUpdate, Role } from "../types";

// ── Outposts ─────────────────────────────────────────────────────────────
export function useOutposts() {
  return useQuery({ queryKey: ["outposts"], queryFn: api.getOutposts });
}

export function useCreateOutpost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ x_ratio, y_ratio }: { x_ratio: number; y_ratio: number }) =>
      api.createOutpost(x_ratio, y_ratio),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outposts"] }),
  });
}

export function useUpdateOutpost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { info?: string; source?: string } }) =>
      api.updateOutpost(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outposts"] }),
  });
}

export function useDeleteOutpost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteOutpost(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outposts"] }),
  });
}

export function useUploadOutpostVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, channel, file }: { id: string; channel: Channel; file: File }) =>
      api.uploadOutpostVideo(id, channel, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["outposts"] }),
  });
}

// ── Cameras ──────────────────────────────────────────────────────────────
export function useCameras() {
  return useQuery({ queryKey: ["cameras"], queryFn: api.getCameras });
}

export function useSetCameraChannel() {
  return useMutation({
    mutationFn: ({ id, channel }: { id: string; channel: Channel }) => api.setCameraChannel(id, channel),
  });
}

// ── 영상 분석 상태 / 타임라인 ─────────────────────────────────────────────
/** 분석 상태 폴링 — ready(또는 error)가 될 때까지 1초마다 재조회합니다. */
export function useAnalysisStatus(cameraId: string | undefined, channel: Channel) {
  return useQuery({
    queryKey: ["analysis-status", cameraId, channel],
    queryFn: () => api.getAnalysisStatus(cameraId as string, channel),
    enabled: Boolean(cameraId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "ready" || status === "error" ? false : 1000;
    },
  });
}

/** 탐지 타임라인 — 분석이 ready일 때 한 번만 조회하고 캐시합니다. */
export function useDetectionsTimeline(cameraId: string | undefined, channel: Channel, ready: boolean) {
  return useQuery({
    queryKey: ["detections-timeline", cameraId, channel],
    queryFn: () => api.getDetectionsTimeline(cameraId as string, channel),
    enabled: Boolean(cameraId) && ready,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

// ── Detections (polling) ─────────────────────────────────────────────────
export function useRecentDetections(limit = 50) {
  return useQuery({
    queryKey: ["detections-recent", limit],
    queryFn: () => api.getRecentDetections(limit),
    refetchInterval: 1500,
  });
}

export function useRecentToasts(limit = 20) {
  return useQuery({
    queryKey: ["toasts-recent", limit],
    queryFn: () => api.getRecentToasts(limit),
    refetchInterval: 1500,
  });
}

// ── Settings ─────────────────────────────────────────────────────────────
export function useSystemStatus() {
  return useQuery({
    queryKey: ["system-status"],
    queryFn: api.getSystemStatus,
    refetchInterval: 15000,
  });
}

// ── Logs ─────────────────────────────────────────────────────────────────
export function useLogs() {
  return useQuery({ queryKey: ["logs"], queryFn: api.getLogs });
}

export function useSaveLogEdits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (batch: LogBatchUpdate) => api.saveLogEdits(batch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["logs"] }),
  });
}

// ── Auth ─────────────────────────────────────────────────────────────────
export function useLogin() {
  return useMutation({
    mutationFn: ({ username, password, role }: { username: string; password: string; role: Role }) =>
      api.login(username, password, role),
  });
}
