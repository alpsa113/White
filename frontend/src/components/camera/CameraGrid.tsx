// components/camera/CameraGrid.tsx — 카메라 카드를 정사각형에 가까운 그리드로 배치. ui/camera/grid.py 이식.
import { CameraCard } from "./CameraCard";
import type { Camera, Outpost } from "../../types";

function computeGridColumns(total: number): number {
  return Math.max(1, Math.ceil(Math.sqrt(total)));
}

interface CameraGridProps {
  cameras: Camera[];
  outpostsById: Record<string, Outpost>;
  focused?: boolean;
  onExpand: (cameraName: string) => void;
  /** 지도 마커 선택으로 필터링된 그리드일 때만 전달 — 누르면 전체 구역 그리드로 돌아갑니다. */
  onBackToGrid?: () => void;
}

export function CameraGrid({ cameras, outpostsById, focused = false, onExpand, onBackToGrid }: CameraGridProps) {
  const cols = computeGridColumns(cameras.length);

  return (
    <div className="camera-grid" style={{ ["--grid-cols" as string]: cols }}>
      {cameras.map((cam) => (
        <CameraCard
          key={cam.id}
          camera={cam}
          outpost={outpostsById[cam.id]}
          isGrid
          isFocused={focused}
          onExpand={onExpand}
          onBackToGrid={focused ? onBackToGrid : undefined}
        />
      ))}
    </div>
  );
}
