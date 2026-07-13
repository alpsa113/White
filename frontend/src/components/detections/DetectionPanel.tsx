// components/detections/DetectionPanel.tsx — 우측 탐지 이력 패널(최대 50개, 사람 클래스 강조).
// ui/camera/detection_panel.py 이식.
// 웹페이지를 새로 열었을 때(최초 로딩) 시점의 최신 id를 기준선으로 삼아, 그 이후 새로 발생한
// 탐지만 표시합니다(RDS에 쌓인 과거 이력은 '감지 기록' 페이지에서만 노출).
// 항목을 클릭하면 '감지 기록' 조회 탭과 동일한 상세 정보 + 스냅샷/클립을 모달로 보여줍니다.
import { useState } from "react";
import { useRecentDetections } from "../../api/hooks";
import { fmtDtDot, fmtPercent, isPersonClass } from "../../utils/formatters";
import { DetectionDetailModal } from "./DetectionDetailModal";
import type { Detection } from "../../types";

const CLASS_ICON_FILES: Record<string, string> = {
  사람: "person.png",
  멧돼지: "boar.png",
  고라니: "deer.png",
  소형동물: "small_object.png",
};

// 모듈 스코프 변수 — 컴포넌트가 페이지 이동으로 언마운트/재마운트되어도 유지되고,
// 브라우저를 새로고침하거나 새 탭에서 열 때(모듈이 처음부터 다시 로드될 때)만 초기화됩니다.
let baselineId: number | null = null;

export function DetectionPanel() {
  const { data: detections } = useRecentDetections(50);
  const [selected, setSelected] = useState<Detection | null>(null);

  if (baselineId === null && detections) {
    baselineId = detections.reduce((max, d) => Math.max(max, d.id), 0);
  }

  const items = baselineId === null ? [] : (detections ?? []).filter((d) => d.id > (baselineId as number));

  return (
    <div className="detection-panel">
      <div className="detection-panel-title">탐지 이력</div>
      <div className="detection-panel-list">
        {items.length === 0 ? (
          <div className="camera-caption">새로운 탐지 이력이 없습니다.</div>
        ) : (
          items.map((d) => {
            const person = isPersonClass(d.class_name);
            const iconFile = CLASS_ICON_FILES[d.class_name];
            return (
              <button
                key={d.id}
                type="button"
                className={`detection-card${person ? " person" : ""}`}
                onClick={() => setSelected(d)}
              >
                {iconFile ? (
                  <img className="det-icon" src={`/icons/${iconFile}`} alt={d.class_name} />
                ) : (
                  <div className="det-icon" />
                )}
                <div className="det-body">
                  <div className="det-row1">
                    <div className="det-class">{d.class_name}</div>
                    <div className="det-cam">{d.camera}</div>
                  </div>
                  <div className="det-meta">
                    {fmtPercent(d.score)} · {fmtDtDot(d)}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      {selected && <DetectionDetailModal detection={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
