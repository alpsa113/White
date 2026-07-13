// components/AnimalToastHost.tsx — 동물 탐지 시 우상단에 잠깐 떴다 사라지는 토스트.
// Streamlit 버전의 st.toast를 이식한 것으로, App.tsx 최상단(라우트 밖)에 마운트해 페이지를
// 이동해도 계속 폴링/표시되도록 합니다.
import { useEffect, useState } from "react";
import { useRecentToasts } from "../api/hooks";
import type { ToastEvent } from "../types";

const CLASS_ICONS: Record<string, string> = {
  사람: "🚶",
  멧돼지: "🐗",
  고라니: "🦌",
  소형동물: "🐾",
};

const TOAST_VISIBLE_MS = 3500;

// 모듈 스코프 변수 — 페이지 이동으로 재마운트돼도 유지되고, 브라우저를 새로 열 때만
// 초기화됩니다(그래야 복귀 시 그동안 쌓인 이벤트가 한꺼번에 쏟아지지 않습니다).
let baselineId: number | null = null;

export function AnimalToastHost() {
  const { data: events } = useRecentToasts(20);
  const [visible, setVisible] = useState<ToastEvent[]>([]);

  useEffect(() => {
    if (!events) return;
    if (baselineId === null) {
      baselineId = events.reduce((max, e) => Math.max(max, e.id), 0);
      return;
    }
    const fresh = events.filter((e) => e.id > (baselineId as number));
    if (fresh.length === 0) return;
    baselineId = Math.max(baselineId, ...fresh.map((e) => e.id));

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
              <div className="animal-toast-camera">{t.camera}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
