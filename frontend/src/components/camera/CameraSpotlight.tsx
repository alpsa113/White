// components/camera/CameraSpotlight.tsx — 카메라 1개를 크게 보여주는 집중 보기. ui/camera/spotlight.py 이식.
import { CameraCard } from "./CameraCard";
import type { Camera, Outpost } from "../../types";

interface CameraSpotlightProps {
  cameras: Camera[];
  focusedName: string;
  outpostsById: Record<string, Outpost>;
  onBackToGrid: () => void;
}

export function CameraSpotlight({ cameras, focusedName, outpostsById, onBackToGrid }: CameraSpotlightProps) {
  const focused = cameras.find((c) => c.name === focusedName);

  if (!focused) {
    return <div className="info-banner">선택된 카메라를 찾을 수 없습니다.</div>;
  }

  return (
    <div style={{ height: "100%" }}>
      <CameraCard
        camera={focused}
        outpost={outpostsById[focused.id]}
        isGrid={false}
        onBackToGrid={onBackToGrid}
      />
    </div>
  );
}
