// components/map/MiniMap.tsx — 관제 지도(초소 마커 + 사람 탐지 시 점멸). ui/outposts/viewer.py + marker_overlay.py 이식.
// 점멸 여부는 더 이상 서버의 실시간 tracking 프로세스가 아니라, 각 카메라 카드(VideoWithOverlay)가
// 자신의 <video> currentTime 기준으로 계산해 LiveDetectionContext에 보고한 값을 사용합니다.
import { outpostMapImageUrl } from "../../api/client";
import { useLiveDetection } from "../../context/LiveDetectionContext";
import type { Outpost } from "../../types";

const DEFAULT_COLOR = "#58a6ff";
const BLINK_COLOR = "#f85149";

interface MiniMapProps {
  outposts: Outpost[];
  selectedIds: Set<string>;
  visibleIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onStopBlink: (id: string) => void;
  stoppedBlink: Set<string>;
}

export function MiniMap({
  outposts,
  selectedIds,
  visibleIds,
  onToggleSelect,
  onStopBlink,
  stoppedBlink,
}: MiniMapProps) {
  const { personActiveByCamera } = useLiveDetection();

  if (outposts.length === 0) {
    return (
      <div className="info-banner">
        등록된 초소가 없습니다 — '설정' 페이지에서 지도를 클릭해 초소를 추가하세요.
      </div>
    );
  }

  return (
    <div className="map-wrap">
      <img src={outpostMapImageUrl()} alt="초소 지도" />
      {outposts.map((o, i) => {
        const isBlinking = Boolean(personActiveByCamera[o.id]) && !stoppedBlink.has(o.id);
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
                title={`${o.info || o.id} — 점멸 정지`}
                onClick={() => onStopBlink(o.id)}
              >
                ⏹
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
