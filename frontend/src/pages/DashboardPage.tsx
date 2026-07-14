// pages/DashboardPage.tsx — views/dashboard.py 이식. 헤더 시계 + 카메라 그리드/스포트라이트 + 우측 미니맵/탐지 이력.
import { useMemo, useState } from "react";
import { HeaderClock } from "../components/HeaderClock";
import { CameraGrid } from "../components/camera/CameraGrid";
import { CameraSpotlight } from "../components/camera/CameraSpotlight";
import { MiniMap } from "../components/map/MiniMap";
import { DetectionPanel } from "../components/detections/DetectionPanel";
import { useCameras, useOutposts } from "../api/hooks";
import { LiveDetectionProvider } from "../context/LiveDetectionContext";

const ALL_ZONES = "전체 구역";

export default function DashboardPage() {
  return (
    <LiveDetectionProvider>
      <DashboardPageInner />
    </LiveDetectionProvider>
  );
}

function DashboardPageInner() {
  const { data: cameras = [] } = useCameras();
  const { data: outposts = [] } = useOutposts();

  const [selectedCam, setSelectedCam] = useState<string>(ALL_ZONES);
  const [mapSelectedIds, setMapSelectedIds] = useState<Set<string>>(new Set());

  const outpostsById = useMemo(() => {
    const map: Record<string, (typeof outposts)[number]> = {};
    for (const o of outposts) map[o.id] = o;
    return map;
  }, [outposts]);

  const toggleMapSelect = (id: string) => {
    setMapSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleExpand = (cameraName: string) => {
    setSelectedCam(cameraName);
    setMapSelectedIds(new Set());
  };

  const handleBackToGrid = () => {
    setSelectedCam(ALL_ZONES);
    setMapSelectedIds(new Set());
  };

  const mapFilteredCameras = cameras.filter((c) => mapSelectedIds.has(c.id));

  // 표시 우선순위: 지도에서 선택된 카메라 > '전체 구역' 그리드 > 단일 집중 보기
  const visibleIds = useMemo(() => {
    if (mapSelectedIds.size > 0) {
      return new Set([...mapSelectedIds].filter((id) => cameras.some((c) => c.id === id)));
    }
    if (selectedCam === ALL_ZONES) {
      return new Set(cameras.map((c) => c.id));
    }
    const focused = cameras.find((c) => c.name === selectedCam);
    return focused ? new Set([focused.id]) : new Set<string>();
  }, [mapSelectedIds, selectedCam, cameras]);

  return (
    <div className="page">
      <HeaderClock />
      <div className="dashboard-body">
        <div className="dashboard-main">
          {mapSelectedIds.size > 0 ? (
            <CameraGrid
              cameras={mapFilteredCameras.length > 0 ? mapFilteredCameras : cameras}
              outpostsById={outpostsById}
              focused
              onExpand={handleExpand}
              onBackToGrid={() => setMapSelectedIds(new Set())}
            />
          ) : selectedCam === ALL_ZONES ? (
            <CameraGrid cameras={cameras} outpostsById={outpostsById} onExpand={handleExpand} />
          ) : (
            <CameraSpotlight
              cameras={cameras}
              focusedName={selectedCam}
              outpostsById={outpostsById}
              onBackToGrid={handleBackToGrid}
            />
          )}
        </div>

        <div className="dashboard-panel">
          <div>
            <strong>초소 위치</strong>
            <div className="camera-caption">사람 탐지 시 해당 초소가 빨간색으로 점멸</div>
            <MiniMap
              outposts={outposts}
              selectedIds={mapSelectedIds}
              visibleIds={visibleIds}
              onToggleSelect={toggleMapSelect}
            />
          </div>
          <DetectionPanel />
        </div>
      </div>
    </div>
  );
}
