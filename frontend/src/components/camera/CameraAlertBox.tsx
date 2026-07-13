// components/camera/CameraAlertBox.tsx — 카메라 카드 우상단에 얹는 초소별 알림 박스.
// 이전의 전역 토스트(AnimalToastHost)를 "실시간 감시" 페이지에서는 대체합니다: 일정 시간 후
// 자동으로 사라지지 않고, 해당 초소에 다음 알림이 발생하기 전까지 유지됩니다.
import { useEffect, useState } from "react";
import { useLiveDetection } from "../../context/LiveDetectionContext";
import { fmtElapsed } from "../../utils/formatters";

const CLASS_ICONS: Record<string, string> = {
  사람: "🚶",
  멧돼지: "🐗",
  고라니: "🦌",
  소형동물: "🐾",
};

interface CameraAlertBoxProps {
  cameraName: string;
}

export function CameraAlertBox({ cameraName }: CameraAlertBoxProps) {
  const { alertsByCamera, closedCameraAlerts, dismissCameraAlerts } = useLiveDetection();
  const [expanded, setExpanded] = useState(false);
  // 시간 표시("N초 전")를 계속 갱신하기 위한 리렌더 트리거.
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const alerts = alertsByCamera[cameraName] ?? [];
  if (alerts.length === 0 || closedCameraAlerts[cameraName]) return null;

  const [latest, ...rest] = alerts;

  return (
    <div className="camera-alert-box">
      <button
        type="button"
        className="camera-alert-close"
        title="알림 닫기"
        onClick={(e) => {
          e.stopPropagation();
          dismissCameraAlerts(cameraName);
        }}
      >
        ×
      </button>

      <div
        className="camera-alert-row camera-alert-latest"
        role={rest.length > 0 ? "button" : undefined}
        onClick={() => rest.length > 0 && setExpanded((v) => !v)}
      >
        <span className="camera-alert-icon">{CLASS_ICONS[latest.class_name] ?? "⚠️"}</span>
        <div className="camera-alert-text">
          <div className="camera-alert-title">{latest.class_name} 탐지</div>
          <div className="camera-alert-time">{fmtElapsed(latest.ts)}</div>
        </div>
        {rest.length > 0 && <span className="camera-alert-chevron">{expanded ? "▲" : "▼"}</span>}
      </div>

      {expanded && rest.length > 0 && (
        <div className="camera-alert-list">
          {rest.map((a) => (
            <div key={a.id} className="camera-alert-row">
              <span className="camera-alert-icon">{CLASS_ICONS[a.class_name] ?? "⚠️"}</span>
              <div className="camera-alert-text">
                <div className="camera-alert-title">{a.class_name} 탐지</div>
                <div className="camera-alert-time">{fmtElapsed(a.ts)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
