// pages/DashboardPage.tsx — views/dashboard.py 이식. 헤더 시계 + 카메라 그리드(전체/필터링) + 우측 미니맵/탐지 이력.
import { useMemo, useState } from "react";
import { HeaderClock } from "../components/HeaderClock";
import { CameraGrid } from "../components/camera/CameraGrid";
import { MiniMap } from "../components/map/MiniMap";
import { DetectionPanel } from "../components/detections/DetectionPanel";
import { useCameras, useOutposts } from "../api/hooks";
import { LiveDetectionProvider } from "../context/LiveDetectionContext";

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

  // 지도 마커 선택과 카드 확대(⤡) 버튼 모두 이 집합을 채워 CameraGrid를 필터링합니다.
  // 둘 다 항상 같은 CameraGrid 트리를 재사용하게 해서(컴포넌트 타입이 바뀌지 않음) 확대해도
  // <video>가 재마운트되지 않고 재생 위치가 그대로 이어집니다.
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
    const cam = cameras.find((c) => c.name === cameraName);
    if (cam) setMapSelectedIds(new Set([cam.id]));
  };

  const mapFilteredCameras = cameras.filter((c) => mapSelectedIds.has(c.id));

  // 표시 우선순위: 필터(지도 선택 또는 확대) 적용 중 > '전체 구역' 그리드
  const visibleIds = useMemo(() => {
    if (mapSelectedIds.size > 0) {
      return new Set([...mapSelectedIds].filter((id) => cameras.some((c) => c.id === id)));
    }
    return new Set(cameras.map((c) => c.id));
  }, [mapSelectedIds, cameras]);

  return (
    <div className="page">
      <HeaderClock />
      <div className="dashboard-body">
        <div className="dashboard-main">
          <CameraGrid
            cameras={mapSelectedIds.size > 0 && mapFilteredCameras.length > 0 ? mapFilteredCameras : cameras}
            outpostsById={outpostsById}
            focused={mapSelectedIds.size > 0}
            onExpand={handleExpand}
            onBackToGrid={() => setMapSelectedIds(new Set())}
          />
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
