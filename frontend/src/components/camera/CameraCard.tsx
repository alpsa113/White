// components/camera/CameraCard.tsx — 카메라 1대 카드(툴바 + 영상+오버레이).
// ui/camera/card.py 이식. 줌/팬은 CSS transform으로 단순화(원본은 JS 주입 방식).
// 영상은 백엔드가 사전 분석한 원본 파일을 <video>로 직접 재생합니다(끊김 없음). 탐지 박스는
// VideoWithOverlay가 캔버스에 그립니다.
// 일시정지/재개 버튼은 제거했습니다 — 서버의 탐지 기록 페이서(services/video_analyzer.py)가
// 영상 재생 상태와 무관하게 항상 자체 페이스로 돌아가서, 화면만 멈추고 로그 적재는 막지
// 못해 혼동을 줄 수 있었습니다.
import { useCallback, useEffect, useRef, useState, type MouseEvent, type WheelEvent } from "react";
import { useSetCameraChannel } from "../../api/hooks";
import { CameraAlertBox } from "./CameraAlertBox";
import { VideoWithOverlay } from "./VideoWithOverlay";
import type { Camera, Channel, Outpost } from "../../types";

interface CameraCardProps {
  camera: Camera;
  outpost?: Outpost;
  /** 그리드(다중 카드)인지 여부 — 그리드에서는 제목 클릭/확대 버튼으로 스포트라이트 전환. */
  isGrid: boolean;
  /** 지도 마커로 필터링된 그리드(집중 보기와 같은 컨트롤을 보여줌). */
  isFocused?: boolean;
  onExpand?: (cameraName: string) => void;
  onBackToGrid?: () => void;
}

export function CameraCard({
  camera,
  outpost,
  isGrid,
  isFocused = false,
  onExpand,
  onBackToGrid,
}: CameraCardProps) {
  // 서버(초소)에 저장된 마지막 채널로 초기화 — 그렇지 않으면 다른 페이지로 이동했다가
  // 돌아올 때마다(컴포넌트 재마운트) 항상 EO로 되돌아가는 문제가 있었습니다.
  const [channel, setChannelLocal] = useState<Channel>(() => outpost?.active_channel ?? "eo");
  // cameras 목록이 outposts보다 먼저 도착해 outpost가 undefined인 채로 마운트되는 경우를 대비해,
  // active_channel이 뒤늦게 도착하면 반영합니다. 단, 사용자가 이번 마운트에서 직접 채널을
  // 전환한 뒤에는(userSwitchedRef) 서버 재조회 타이밍에 따른 stale 값으로 덮어쓰지 않습니다.
  // (active_channel은 백엔드가 항상 기본값 "eo"를 채워 내려주므로, "값이 존재하는지"가 아니라
  // "사용자가 전환했는지"로 판단해야 합니다 — 그렇지 않으면 사용자가 전환한 채널이 페이지를
  // 벗어났다 돌아올 때마다 항상 최초 마운트값(EO)으로 리셋되는 버그가 있었습니다.)
  const userSwitchedRef = useRef(false);
  useEffect(() => {
    if (userSwitchedRef.current || !outpost?.active_channel) return;
    setChannelLocal(outpost.active_channel);
  }, [outpost?.active_channel]);
  const [zoom, setZoom] = useState({ scale: 1, panX: 0, panY: 0 });
  const dragRef = useRef<{ dragging: boolean; startX: number; startY: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const setChannelMutation = useSetCameraChannel();

  const showFocusedControls = !isGrid || isFocused;

  const eoAvailable = Boolean(outpost?.video_eo_name);
  const tirAvailable = Boolean(outpost?.video_tir_name);

  const handleChannelSwitch = (next: Channel) => {
    if (next === channel) return;
    userSwitchedRef.current = true;
    setChannelLocal(next);
    setChannelMutation.mutate({ id: camera.id, channel: next });
  };

  const handleTitleClick = () => {
    if (isGrid && !isFocused) onExpand?.(camera.name);
  };

  // ── 줌/팬 (마우스 휠 확대, 드래그 이동) — 원본은 컴포넌트 HTML로 스크립트를 주입해
  // 실제 DOM에 리스너를 붙였지만, React에서는 CSS transform + 상태로 단순화했습니다.
  const onWheel = useCallback((e: WheelEvent<HTMLDivElement>) => {
    if (isGrid && !isFocused) return;
    e.preventDefault();
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setZoom((prev) => {
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      const nextScale = Math.min(Math.max(prev.scale * factor, 1), 6);
      const actual = nextScale / prev.scale;
      return {
        scale: nextScale,
        panX: x - (x - prev.panX) * actual,
        panY: y - (y - prev.panY) * actual,
      };
    });
  }, [isGrid, isFocused]);

  const onMouseDown = useCallback((e: MouseEvent<HTMLDivElement>) => {
    if (isGrid && !isFocused) return;
    dragRef.current = { dragging: true, startX: e.clientX - zoom.panX, startY: e.clientY - zoom.panY };
  }, [isGrid, isFocused, zoom.panX, zoom.panY]);

  const onMouseMove = useCallback((e: MouseEvent<HTMLDivElement>) => {
    if (!dragRef.current?.dragging) return;
    setZoom((prev) => ({
      ...prev,
      panX: e.clientX - dragRef.current!.startX,
      panY: e.clientY - dragRef.current!.startY,
    }));
  }, []);

  const onMouseUp = useCallback(() => {
    if (dragRef.current) dragRef.current.dragging = false;
  }, []);

  const resetZoom = () => setZoom({ scale: 1, panX: 0, panY: 0 });

  const channelAvailable = channel === "eo" ? eoAvailable : tirAvailable;

  return (
    <div className={`camera-card${!isGrid ? " spotlight" : ""}`}>
      <div className="camera-topbar">
        {isGrid && !isFocused ? (
          <button className="camera-title" onClick={handleTitleClick}>
            {camera.name}
          </button>
        ) : (
          <div className="camera-title">{camera.name}</div>
        )}

        <div className="camera-controls">
          <div className="channel-toggle">
            <button
              className={`btn btn-sm${channel === "eo" ? " btn-primary" : ""}`}
              disabled={!eoAvailable}
              title={eoAvailable ? "EO(가시광) 영상으로 전환" : undefined}
              onClick={() => handleChannelSwitch("eo")}
            >
              EO
            </button>
            <button
              className={`btn btn-sm${channel === "tir" ? " btn-primary" : ""}`}
              disabled={!tirAvailable}
              title={tirAvailable ? "TIR(열화상) 영상으로 전환" : undefined}
              onClick={() => handleChannelSwitch("tir")}
            >
              TIR
            </button>
          </div>

          <div className="view-toggle">
            {isGrid && !isFocused && (
              <button className="btn btn-sm btn-icon" title="화면 확대" onClick={handleTitleClick}>
                ⤡
              </button>
            )}
            {showFocusedControls && (
              <>
                {onBackToGrid && (
                  <button className="btn btn-sm btn-icon" title="전체 그리드로 돌아가기" onClick={onBackToGrid}>
                    🗗
                  </button>
                )}
                <button className="btn btn-sm btn-icon" title="원본으로 돌아가기" onClick={resetZoom}>
                  ↺
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      <div
        className="camera-img-wrap"
        ref={wrapRef}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        style={{ cursor: showFocusedControls ? "grab" : "default" }}
      >
        <CameraAlertBox cameraName={camera.name} />
        {channelAvailable ? (
          <VideoWithOverlay
            ref={videoRef}
            camera={camera}
            channel={channel}
            style={{
              transformOrigin: "0 0",
              transform: `translate(${zoom.panX}px, ${zoom.panY}px) scale(${zoom.scale})`,
            }}
          />
        ) : (
          <div className="camera-placeholder">매핑된 영상 없음</div>
        )}
      </div>
    </div>
  );
}
