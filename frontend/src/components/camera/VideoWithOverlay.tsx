// components/camera/VideoWithOverlay.tsx — 사전 분석된 원본 영상(<video>) + 탐지 박스를 그리는
// <canvas> 오버레이. 백엔드가 더 이상 MJPEG를 실시간 재인코딩하지 않고, 영상 파일을 그대로
// Range 요청으로 서빙하므로 브라우저가 직접 디코딩합니다(끊김 없음). 탐지 결과는 업로드 시점에
// 한 번 분석되어 타임라인(t=ms, dets[])으로 캐시되며, video.currentTime에 가장 가까운 항목을
// 매 프레임 찾아 캔버스에 그립니다.
import { forwardRef, useEffect, useMemo, useRef, useState, type CSSProperties, type MutableRefObject } from "react";
import { videoUrl } from "../../api/client";
import { useAnalysisStatus, useDetectionsTimeline } from "../../api/hooks";
import { isPersonClass } from "../../utils/formatters";
import type { Camera, Channel, TimelineDetection, TimelineEntry } from "../../types";

const CLASS_COLORS: Record<string, string> = {
  사람: "#f85149",
  멧돼지: "#e3a008",
  고라니: "#3fb950",
  소형동물: "#a371f7",
};
const DEFAULT_BOX_COLOR = "#58a6ff";

interface VideoWithOverlayProps {
  camera: Camera;
  channel: Channel;
  style?: CSSProperties;
  onPersonActiveChange?: (active: boolean) => void;
}

/** 타임라인에서 tMs(ms)에 가장 가까운 항목을 찾습니다(정렬된 배열 이진 탐색). */
function findNearestEntry(timeline: TimelineEntry[], tMs: number): TimelineEntry | undefined {
  if (timeline.length === 0) return undefined;
  let lo = 0;
  let hi = timeline.length - 1;
  if (tMs <= timeline[0].t) return timeline[0];
  if (tMs >= timeline[hi].t) return timeline[hi];
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (timeline[mid].t < tMs) lo = mid + 1;
    else hi = mid;
  }
  const after = timeline[lo];
  const before = timeline[Math.max(0, lo - 1)];
  return tMs - before.t <= after.t - tMs ? before : after;
}

function drawDetections(canvas: HTMLCanvasElement, dets: TimelineDetection[]) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const det of dets) {
    const color = CLASS_COLORS[det.class_name] ?? DEFAULT_BOX_COLOR;
    const { x1, y1, x2, y2 } = det.box;
    const w = x2 - x1;
    const h = y2 - y1;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(2, canvas.width / 400);
    ctx.strokeRect(x1, y1, w, h);

    const label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%`;
    ctx.font = `${Math.max(14, canvas.width / 60)}px sans-serif`;
    const textMetrics = ctx.measureText(label);
    const textHeight = Math.max(14, canvas.width / 60) * 1.4;
    ctx.fillStyle = color;
    ctx.fillRect(x1, Math.max(0, y1 - textHeight), textMetrics.width + 8, textHeight);
    ctx.fillStyle = "#0d1117";
    ctx.fillText(label, x1 + 4, Math.max(textHeight - 4, y1 - 4));
  }
}

export const VideoWithOverlay = forwardRef<HTMLVideoElement, VideoWithOverlayProps>(
  function VideoWithOverlay({ camera, channel, style, onPersonActiveChange }, forwardedRef) {
    const videoRef = useRef<HTMLVideoElement | null>(null);
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const timelineRef = useRef<TimelineEntry[]>([]);
    const wasPersonActiveRef = useRef(false);
    const rafRef = useRef<number | null>(null);
    const [videoSize, setVideoSize] = useState<{ w: number; h: number } | null>(null);

    const { data: analysisStatus } = useAnalysisStatus(camera.id, channel);
    const status = analysisStatus?.status ?? "idle";
    const ready = status === "ready";

    const { data: timeline = [] } = useDetectionsTimeline(camera.id, channel, ready);
    timelineRef.current = timeline;

    // forwardedRef와 내부 videoRef를 함께 채워 부모(CameraCard)가 play()/pause()를 직접 호출할 수 있게 함.
    const setVideoRef = (el: HTMLVideoElement | null) => {
      videoRef.current = el;
      if (typeof forwardedRef === "function") forwardedRef(el);
      else if (forwardedRef) (forwardedRef as MutableRefObject<HTMLVideoElement | null>).current = el;
    };

    // 매 프레임: 캔버스 갱신 + 현재 탐지의 사람 여부를 상위로 보고.
    useEffect(() => {
      if (!ready) return;
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas) return;

      const tick = () => {
        const entry = findNearestEntry(timelineRef.current, video.currentTime * 1000);
        const dets = entry?.dets ?? [];

        if (canvas.width !== video.videoWidth && video.videoWidth > 0) canvas.width = video.videoWidth;
        if (canvas.height !== video.videoHeight && video.videoHeight > 0) canvas.height = video.videoHeight;
        if (canvas.width > 0 && canvas.height > 0) drawDetections(canvas, dets);

        const personActive = dets.some((d) => isPersonClass(d.class_name));
        if (personActive !== wasPersonActiveRef.current) {
          wasPersonActiveRef.current = personActive;
          onPersonActiveChange?.(personActive);
        }

        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
      return () => {
        if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ready, camera.id, channel]);

    const handleLoadedMetadata = () => {
      const v = videoRef.current;
      if (!v) return;
      setVideoSize({ w: v.videoWidth, h: v.videoHeight });
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = v.videoWidth;
        canvas.height = v.videoHeight;
      }
    };

    const src = useMemo(() => videoUrl(camera.id, channel), [camera.id, channel]);

    if (status === "idle") {
      return <div className="camera-placeholder">매핑된 영상 없음</div>;
    }

    if (status === "error") {
      return (
        <div className="camera-placeholder camera-analysis-error">
          영상 분석 실패{analysisStatus?.error ? `: ${analysisStatus.error}` : ""}
        </div>
      );
    }

    if (status === "analyzing") {
      const pct = Math.round((analysisStatus?.progress ?? 0) * 100);
      return (
        <div className="camera-placeholder camera-analysis-loading">
          <div>분석 중... {pct}%</div>
          <div className="camera-analysis-progress-track">
            <div className="camera-analysis-progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
      );
    }

    return (
      <div className="video-overlay-wrap" style={style}>
        <video
          key={`${camera.id}-${channel}`}
          ref={setVideoRef}
          src={src}
          autoPlay
          muted
          loop
          playsInline
          controls={false}
          onLoadedMetadata={handleLoadedMetadata}
        />
        <canvas ref={canvasRef} width={videoSize?.w ?? 0} height={videoSize?.h ?? 0} />
      </div>
    );
  }
);
