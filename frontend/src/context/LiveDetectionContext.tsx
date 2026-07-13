// contexts/LiveDetectionContext.tsx — 사람 탐지 알림(토스트) 기반의 공용 저장소.
// 미니맵의 마커 점멸 및 사람이 새로 나타날 때의 알림음 재생에 사용됩니다.
// 마커 점멸은 실시간 화면 상태가 아니라 "서버가 쿨다운을 적용해 이미 걸러준 탐지 이벤트"를
// 기준으로 켜지며, 사용자가 X 버튼으로 직접 끄기 전까지는 자동으로 꺼지지 않습니다.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { API_BASE_URL } from "../api/client";
import { useCameras, useRecentToasts } from "../api/hooks";
import { isPersonClass } from "../utils/formatters";
import type { ToastEvent } from "../types";

type ActiveMap = Record<string, boolean>;

/** 카메라(초소) 카드 우상단에 표시할 알림 — 초소별로 최대 이만큼만 쌓아둡니다. */
export const MAX_CAMERA_ALERTS = 5;

interface LiveDetectionContextValue {
  /** 초소별 미니맵 마커 점멸 여부 — 사람 탐지 알림이 오면 켜지고, 사용자가 끌 때까지 유지됩니다. */
  personAlertActiveByCamera: ActiveMap;
  dismissCameraPersonLight: (cameraId: string) => void;
  alertsByCamera: Record<string, ToastEvent[]>;
  closedCameraAlerts: Record<string, boolean>;
  dismissCameraAlerts: (camera: string) => void;
}

const LiveDetectionContext = createContext<LiveDetectionContextValue | null>(null);

// 알림음(WAV)은 1회만 받아 브라우저에 캐시해두고, 사람이 새로 나타날 때마다 재생합니다.
let alertAudioUrlPromise: Promise<string> | null = null;

function getAlertAudioUrl(): Promise<string> {
  if (!alertAudioUrlPromise) {
    alertAudioUrlPromise = fetch(`${API_BASE_URL}/api/alert-sound`)
      .then((res) => res.blob())
      .then((blob) => URL.createObjectURL(blob));
  }
  return alertAudioUrlPromise;
}

function playAlertSound() {
  getAlertAudioUrl()
    .then((url) => new Audio(url).play())
    .catch(() => {
      /* 브라우저 자동재생 정책 등으로 실패해도 무시(사용자가 한 번이라도 페이지와
         상호작용했다면 대부분 재생됩니다) */
    });
}

// 모듈 스코프 변수 — Provider가 재마운트돼도 유지되고, 브라우저를 새로 열 때만 초기화됩니다
// (그래야 페이지를 나갔다 돌아올 때 그동안 쌓인 이벤트가 카드마다 한꺼번에 쏟아지지 않습니다).
let cameraAlertBaselineId: number | null = null;

export function LiveDetectionProvider({ children }: { children: ReactNode }) {
  const [personAlertActiveByCamera, setPersonAlertActiveByCamera] = useState<ActiveMap>({});

  const dismissCameraPersonLight = useCallback((cameraId: string) => {
    setPersonAlertActiveByCamera((prev) => (prev[cameraId] ? { ...prev, [cameraId]: false } : prev));
  }, []);

  // ── 카메라 카드 우상단 알림 박스 — 초소별로 최근 알림을 유지하다가, 그 초소에 다음
  // 알림이 발생하면 갱신됩니다(토스트처럼 일정 시간 후 자동으로 사라지지 않음).
  const { data: toastEvents } = useRecentToasts(20);
  // 토스트는 카메라 "이름"(예: "CCTV1 (...)")으로 오지만, 마커는 카메라 "id"(=초소 id)로
  // 관리되므로 여기서 이름→id로 변환합니다.
  const { data: cameras } = useCameras();
  const cameraIdByName = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of cameras ?? []) map[c.name] = c.id;
    return map;
  }, [cameras]);
  const [alertsByCamera, setAlertsByCamera] = useState<Record<string, ToastEvent[]>>({});
  const [closedCameraAlerts, setClosedCameraAlerts] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!toastEvents) return;
    if (cameraAlertBaselineId === null) {
      cameraAlertBaselineId = toastEvents.reduce((max, e) => Math.max(max, e.id), 0);
      return;
    }
    const fresh = toastEvents.filter((e) => e.id > (cameraAlertBaselineId as number));
    if (fresh.length === 0) return;
    cameraAlertBaselineId = Math.max(cameraAlertBaselineId, ...fresh.map((e) => e.id));

    setAlertsByCamera((prev) => {
      const next = { ...prev };
      for (const e of fresh) {
        next[e.camera] = [e, ...(next[e.camera] ?? [])].slice(0, MAX_CAMERA_ALERTS);
      }
      return next;
    });
    // 닫아둔 초소라도 새 알림이 오면 다시 노출합니다.
    setClosedCameraAlerts((prev) => {
      const cameras = new Set(fresh.map((e) => e.camera));
      const next = { ...prev };
      let changed = false;
      for (const camera of cameras) {
        if (next[camera]) {
          next[camera] = false;
          changed = true;
        }
      }
      return changed ? next : prev;
    });

    // 사람이 새로 탐지된 초소는 (사용자가 꺼뒀더라도) 마커 점멸을 다시 켜고 알림음도 재생합니다.
    // 화면상 사람이 사라져도 이 점멸은 저절로 꺼지지 않고, 사용자가 X 버튼을 눌러야 꺼집니다.
    const personCameraIds = new Set<string>();
    for (const e of fresh) {
      if (isPersonClass(e.class_name)) personCameraIds.add(cameraIdByName[e.camera] ?? e.camera);
    }
    if (personCameraIds.size > 0) {
      playAlertSound();
      setPersonAlertActiveByCamera((prev) => {
        const next = { ...prev };
        for (const id of personCameraIds) next[id] = true;
        return next;
      });
    }
  }, [toastEvents, cameraIdByName]);

  const dismissCameraAlerts = useCallback((camera: string) => {
    setClosedCameraAlerts((prev) => ({ ...prev, [camera]: true }));
  }, []);

  const value = useMemo(
    () => ({
      personAlertActiveByCamera,
      dismissCameraPersonLight,
      alertsByCamera,
      closedCameraAlerts,
      dismissCameraAlerts,
    }),
    [personAlertActiveByCamera, dismissCameraPersonLight, alertsByCamera, closedCameraAlerts, dismissCameraAlerts]
  );

  return <LiveDetectionContext.Provider value={value}>{children}</LiveDetectionContext.Provider>;
}

export function useLiveDetection(): LiveDetectionContextValue {
  const ctx = useContext(LiveDetectionContext);
  if (!ctx) {
    throw new Error("useLiveDetection must be used within a LiveDetectionProvider");
  }
  return ctx;
}
