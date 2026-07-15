// components/map/MiniMap.tsx — 관제 지도(초소 마커 + 사람 탐지 시 점멸). ui/outposts/viewer.py + marker_overlay.py 이식.
// 점멸은 사람 탐지 알림(토스트)이 오면 켜지고, 사용자가 × 버튼으로 끄기 전까지는 화면상 사람이
// 사라져도 자동으로 꺼지지 않습니다(LiveDetectionContext의 personAlertActiveByCamera).
import { outpostMapImageUrl } from "../../api/client";
import { useMapImageVersion } from "../../api/hooks";
import { useLiveDetection } from "../../context/LiveDetectionContext";
import type { Outpost } from "../../types";

const DEFAULT_COLOR = "#58a6ff";
const BLINK_COLOR = "#f85149";

interface MiniMapProps {
  outposts: Outpost[];
  selectedIds: Set<string>;
  visibleIds: Set<string>;
  onToggleSelect: (id: string) => void;
}

export function MiniMap({ outposts, selectedIds, visibleIds, onToggleSelect }: MiniMapProps) {
  const { personAlertActiveByCamera, dismissCameraPersonLight } = useLiveDetection();
  const { data: mapImageVersion } = useMapImageVersion();

  if (outposts.length === 0) {
    return (
      <div className="info-banner">
        등록된 초소가 없습니다 — '설정' 페이지에서 지도를 클릭해 초소를 추가하세요.
      </div>
    );
  }

  return (
    <div className="map-wrap">
      <img src={outpostMapImageUrl(mapImageVersion?.version)} alt="초소 지도" />
      {outposts.map((o, i) => {
        const isBlinking = Boolean(personAlertActiveByCamera[o.id]);
        const selected = selectedIds.has(o.id);
        const checked = visibleIds.has(o.id);
        const color = isBlinking ? BLINK_COLOR : DEFAULT_COLOR;
        const left = `${o.x_ratio * 100}%`;
        const top = `${o.y_ratio * 100}%`;

        return (
          <div key={o.id}>
            <button
              className={`map-marker${isBlinking ? " blinking" : ""}`}
              style={{ left, top, backgroundColor: color }}
              title={selected ? `${o.info || o.id} — 클릭하여 선택 해제` : `${o.info || o.id} — 클릭하여 CCTV 화면 보기로 선택`}
              onClick={() => onToggleSelect(o.id)}
            >
              {i + 1}
            </button>

            {checked && (
              <div
                className="map-check-badge"
                style={{ left, top: `calc(${top} - 4.2cqw)` }}
                aria-hidden
              >
                <svg viewBox="-1 -1 2 2" style={{ width: "100%", height: "100%", overflow: "visible" }}>
                  <polyline
                    points="-0.7,0 -0.15,0.55 0.85,-0.65"
                    fill="none"
                    stroke="white"
                    strokeWidth={0.46}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <polyline
                    points="-0.7,0 -0.15,0.55 0.85,-0.65"
                    fill="none"
                    stroke="#22c55e"
                    strokeWidth={0.3}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
            )}

            {isBlinking && (
              <button
                className="map-stop-icon"
                style={{ left: `calc(${left} + 4.5cqw)`, top: `calc(${top} - 4.5cqw)` }}
                title={`${o.info || o.id} — 점멸 끄기`}
                onClick={() => dismissCameraPersonLight(o.id)}
              >
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
