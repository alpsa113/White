// contexts/LiveDetectionContext.tsx — 각 카메라 카드(VideoWithOverlay)가 자신의 현재 프레임
// 탐지 상태(사람 등장 여부)를 보고하는 공용 저장소. 미니맵의 실시간 점멸 표시 및 사람이 새로
// 나타날 때의 알림음 재생에 사용됩니다.
// 서버에 더 이상 실시간 tracking 프로세스가 없으므로(사전 분석 + 정적 타임라인만 존재),
// "지금 이 순간 사람이 보이는가"는 클라이언트에서 각 <video>의 currentTime을 기준으로 계산합니다.
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { API_BASE_URL } from "../api/client";

type PersonActiveMap = Record<string, boolean>;

interface LiveDetectionContextValue {
  personActiveByCamera: PersonActiveMap;
  setCameraPersonActive: (cameraId: string, active: boolean) => void;
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

export function LiveDetectionProvider({ children }: { children: ReactNode }) {
  const [personActiveByCamera, setPersonActiveByCamera] = useState<PersonActiveMap>({});
  const lastRef = useRef<PersonActiveMap>({});

  const setCameraPersonActive = useCallback((cameraId: string, active: boolean) => {
    if (lastRef.current[cameraId] === active) return; // 값이 바뀔 때만 리렌더
    const justAppeared = active && !lastRef.current[cameraId];
    lastRef.current = { ...lastRef.current, [cameraId]: active };
    setPersonActiveByCamera((prev) => ({ ...prev, [cameraId]: active }));
    if (justAppeared) playAlertSound();
  }, []);

  const value = useMemo(
    () => ({ personActiveByCamera, setCameraPersonActive }),
    [personActiveByCamera, setCameraPersonActive]
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
