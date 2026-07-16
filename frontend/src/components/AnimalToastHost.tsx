// components/AnimalToastHost.tsx — 동물 탐지 시 우상단에 잠깐 떴다 사라지는 토스트.
// Streamlit 버전의 st.toast를 이식한 것으로, App.tsx 최상단(라우트 밖)에 마운트해 페이지를
// 이동해도 계속 폴링/표시되도록 합니다.
import { useEffect, useRef, useState } from "react";
import { useRecentToasts } from "../api/hooks";
import { fmtElapsed } from "../utils/formatters";
import type { ToastEvent } from "../types";

const CLASS_ICONS: Record<string, string> = {
  사람: "🚶",
  멧돼지: "🐗",
  고라니: "🦌",
  소형동물: "🐾",
};

const TOAST_VISIBLE_MS = 3500;

export function AnimalToastHost() {
  const { data: events } = useRecentToasts(20);
  const [visible, setVisible] = useState<ToastEvent[]>([]);
  // 이 컴포넌트는 "실시간 감시" 페이지가 아닐 때만 마운트됩니다. 마운트 시점 이전에 쌓인
  // 이벤트는 이미 실시간 감시 페이지의 카메라 카드 알림으로 확인했을 것이므로 무시하고,
  // 마운트된 "이후" 새로 들어오는 탐지만 토스트로 띄웁니다.
  const baselineIdRef = useRef<number | null>(null);
  // 카메라 카드 알림 박스처럼 "N초 전" 표시를 계속 갱신하기 위한 리렌더 트리거.
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!events) return;
    if (baselineIdRef.current === null) {
      baselineIdRef.current = events.reduce((max, e) => Math.max(max, e.id), 0);
      return;
    }
    const fresh = events.filter((e) => e.id > (baselineIdRef.current as number));
    if (fresh.length === 0) return;
    baselineIdRef.current = Math.max(baselineIdRef.current, ...fresh.map((e) => e.id));

    setVisible((prev) => [...prev, ...fresh]);
    fresh.forEach((e) => {
      setTimeout(() => {
        setVisible((prev) => prev.filter((t) => t.id !== e.id));
      }, TOAST_VISIBLE_MS);
    });
  }, [events]);

  if (visible.length === 0) return null;

  return (
    <div className="animal-toast-stack">
      {visible.map((t) => {
        const icon = CLASS_ICONS[t.class_name];
        return (
          <div key={t.id} className="animal-toast">
            {icon ? <span className="animal-toast-icon">{icon}</span> : null}
            <div>
              <div className="animal-toast-title">{t.class_name} 탐지</div>
              <div className="animal-toast-meta">
                <span className="animal-toast-camera">{t.camera}</span>
                <span className="animal-toast-sep">|</span>
                <span className="animal-toast-time">{fmtElapsed(t.ts)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
