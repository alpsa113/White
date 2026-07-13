// components/detections/DetectionDetailModal.tsx — 탐지 이력 패널에서 항목을 클릭하면 뜨는
// 상세 보기(카메라/클래스/신뢰도/시각 + 스냅샷 이미지 또는 클립 영상). '감지 기록' 페이지의
// 조회 탭(LogViewTab)과 동일한 정보를 모달로 보여줍니다.
import { logSnapshotUrl } from "../../api/client";
import { fmtDtDot, fmtPercent } from "../../utils/formatters";
import type { Detection } from "../../types";

interface DetectionDetailModalProps {
  detection: Detection;
  onClose: () => void;
}

export function DetectionDetailModal({ detection, onClose }: DetectionDetailModalProps) {
  const isVideo = detection.content_type === "video/mp4";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <strong>
            {detection.class_name} · {detection.camera}
          </strong>
          <button className="btn btn-sm btn-icon" title="닫기" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="camera-caption">
          {fmtPercent(detection.score)} · {fmtDtDot(detection)}
        </div>
        <hr className="divider" />
        {isVideo ? (
          <video
            key={detection.id}
            src={logSnapshotUrl(detection.id)}
            controls
            autoPlay
            style={{ width: "100%", borderRadius: 4 }}
          />
        ) : (
          <img
            src={logSnapshotUrl(detection.id)}
            alt="탐지 순간 캡처"
            style={{ width: "100%", borderRadius: 4 }}
          />
        )}
      </div>
    </div>
  );
}
