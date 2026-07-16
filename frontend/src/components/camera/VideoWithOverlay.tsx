// components/camera/VideoWithOverlay.tsx — 사전 분석된 원본 영상(<video>) + 탐지 박스를 그리는
// <canvas> 오버레이. 백엔드가 더 이상 MJPEG를 실시간 재인코딩하지 않고, 영상 파일을 그대로
// Range 요청으로 서빙하므로 브라우저가 직접 디코딩합니다(끊김 없음). 탐지 결과는 업로드 시점에
// 한 번 분석되어 타임라인(t=ms, dets[])으로 캐시되며, video.currentTime에 가장 가까운 항목을
// 매 프레임 찾아 캔버스에 그립니다.
//
// EO/TIR 두 채널의 <video>를 항상 동시에 마운트해두고(둘 다 자체 페이스로 끊김 없이 계속 재생),
// 채널 버튼은 둘 중 어느 쪽을 보여줄지만 CSS로 토글합니다. 예전에는 활성 채널이 바뀔 때마다
// <video src>를 새로 로드했는데, 그러면 재생 위치가 0으로 리셋되고(브라우저의 media load
// algorithm) 서버의 실시간 알림 페이서(video_analyzer.py, 채널마다 독립적으로 자체 시계로 도는
// 스레드)와 화면 타이밍이 어긋났습니다. 두 영상을 항상 함께 재생해두면 애초에 리로드 자체가
// 없으므로 이 문제가 구조적으로 사라집니다.
import { forwardRef, useEffect, useMemo, useRef, useState, type CSSProperties, type MutableRefObject } from "react";
import { getPacerPosition, videoUrl } from "../../api/client";
import { useAnalysisStatus, useDetectionsTimeline } from "../../api/hooks";
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
  eoAvailable: boolean;
  tirAvailable: boolean;
  style?: CSSProperties;
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

const LAYER_STYLE: CSSProperties = { position: "absolute", inset: 0 };
// 서버의 실시간 알림 페이서(services/video_analyzer.py) 위치와 주기적으로 다시 맞춰, "알림이 뜬
// 순간"과 "화면 장면"이 서서히 어긋나지 않도록 합니다. 로딩 직후(버퍼링 등으로 초반 드리프트가
// 특히 크게 생기기 쉬운 구간)에도 오래 어긋난 채로 두지 않도록 주기를 짧게 잡았습니다.
const PACER_RESYNC_MS = 5_000;
// 재생 중 자잘한 오차로 계속 튀지 않도록, 이 이상 어긋났을 때만 다시 seek합니다.
const PACER_DRIFT_TOLERANCE_SEC = 0.75;

interface ChannelLayerProps {
  camera: Camera;
  channel: Channel;
  active: boolean;
  onVideoRef: (channel: Channel, el: HTMLVideoElement | null) => void;
}

/** 채널 하나(EO 또는 TIR)의 <video>+<canvas>. active가 아니어도 마운트된 채 계속 재생되며,
 * 화면에는 CSS(display)로만 나타나거나 숨겨집니다 — 그래서 채널을 전환해도 재생 위치가
 * 절대 리셋되지 않습니다. */
function ChannelLayer({ camera, channel, active, onVideoRef }: ChannelLayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const timelineRef = useRef<TimelineEntry[]>([]);
  const rafRef = useRef<number | null>(null);
  const [videoSize, setVideoSize] = useState<{ w: number; h: number } | null>(null);

  const { data: analysisStatus } = useAnalysisStatus(camera.id, channel);
  const status = analysisStatus?.status ?? "idle";
  const ready = status === "ready";
  // 탐지 대상 없는 정적 배경 컷(services/video_analyzer.py의 is_image_path) — <video> 대신
  // <img>로 표시하고, 탐지 타임라인 조회/박스 그리기를 모두 건너뜁니다.
  const isImage = analysisStatus?.kind === "image";

  const { data: timeline = [] } = useDetectionsTimeline(camera.id, channel, ready && !isImage);
  timelineRef.current = timeline;

  const setVideoRef = (el: HTMLVideoElement | null) => {
    videoRef.current = el;
    onVideoRef(channel, el);
  };

  // 화면에 보이는 채널만 캔버스에 박스를 그립니다(숨겨진 채널은 재생만 계속하고 그리기는 생략).
  useEffect(() => {
    if (!ready || !active || isImage) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const tick = () => {
      const tMs = video.currentTime * 1000;
      const entry = findNearestEntry(timelineRef.current, tMs);
      const dets = entry?.dets ?? [];

      if (canvas.width !== video.videoWidth && video.videoWidth > 0) canvas.width = video.videoWidth;
      if (canvas.height !== video.videoHeight && video.videoHeight > 0) canvas.height = video.videoHeight;
      if (canvas.width > 0 && canvas.height > 0) drawDetections(canvas, dets);

      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [ready, active, isImage, camera.id, channel]);

  // 서버 페이서가 지금 타임라인의 어느 지점을 흘려보내고 있는지 물어 <video>를 그 위치로
  // seek합니다 — 화면에 보이지 않는(비활성) 채널도 다음에 전환했을 때 이미 맞아있도록 계속
  // 동기화합니다. 브라우저의 duration 추정치로 독립적으로 계산하지 않고 서버 값을 그대로
  // 신뢰하므로, EO/TIR의 실제 영상 길이가 살짝 달라도 각자 정확한 위치로 맞춰집니다.
  useEffect(() => {
    if (!ready || isImage) return;
    let cancelled = false;

    const sync = async (force: boolean) => {
      const video = videoRef.current;
      if (!video) return;
      try {
        const { elapsed_ms } = await getPacerPosition(camera.id, channel);
        if (cancelled) return;
        const target = elapsed_ms / 1000;
        const drift = Math.abs(video.currentTime - target);
        if (force || drift > PACER_DRIFT_TOLERANCE_SEC) {
          video.currentTime = target;
        }
      } catch {
        // 페이서가 아직 시작되지 않았으면(분석 직후) 자연 재생에 맡기고 다음 주기에 다시 시도합니다.
      }
    };

    sync(true);
    const id = setInterval(() => sync(false), PACER_RESYNC_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ready, isImage, camera.id, channel]);

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
  const layerStyle: CSSProperties = { ...LAYER_STYLE, display: active ? "block" : "none" };

  if (status === "idle") {
    return active ? <div className="camera-placeholder" style={LAYER_STYLE}>매핑된 영상 없음</div> : null;
  }

  if (status === "error") {
    return active ? (
      <div className="camera-placeholder camera-analysis-error" style={LAYER_STYLE}>
        영상 분석 실패{analysisStatus?.error ? `: ${analysisStatus.error}` : ""}
      </div>
    ) : null;
  }

  if (status === "analyzing") {
    if (!active) return null;
    const pct = Math.round((analysisStatus?.progress ?? 0) * 100);
    return (
      <div className="camera-placeholder camera-analysis-loading" style={LAYER_STYLE}>
        <div>분석 중... {pct}%</div>
        <div className="camera-analysis-progress-track">
          <div className="camera-analysis-progress-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  if (isImage) {
    return (
      <div className="video-overlay-wrap" style={layerStyle}>
        <img src={src} alt={`${camera.name} ${channel.toUpperCase()}`} />
      </div>
    );
  }

  return (
    <div className="video-overlay-wrap" style={layerStyle}>
      <video
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

export const VideoWithOverlay = forwardRef<HTMLVideoElement, VideoWithOverlayProps>(
  function VideoWithOverlay({ camera, channel, eoAvailable, tirAvailable, style }, forwardedRef) {
    const videoRefs = useRef<Partial<Record<Channel, HTMLVideoElement | null>>>({});

    const syncForwardedRef = (el: HTMLVideoElement | null) => {
      if (typeof forwardedRef === "function") forwardedRef(el);
      else if (forwardedRef) (forwardedRef as MutableRefObject<HTMLVideoElement | null>).current = el;
    };

    const handleVideoRef = (ch: Channel, el: HTMLVideoElement | null) => {
      videoRefs.current[ch] = el;
      if (ch === channel) syncForwardedRef(el);
    };

    // 활성 채널이 바뀌면(마운트/언마운트 없이 display만 토글되므로) 부모가 들고 있는 ref도
    // 새로 활성화된 <video>를 가리키도록 다시 맞춰줍니다.
    useEffect(() => {
      syncForwardedRef(videoRefs.current[channel] ?? null);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [channel]);

    if (!eoAvailable && !tirAvailable) {
      return <div className="camera-placeholder">매핑된 영상 없음</div>;
    }

    return (
      <div className="video-overlay-wrap" style={{ position: "relative", ...style }}>
        {eoAvailable && (
          <ChannelLayer camera={camera} channel="eo" active={channel === "eo"} onVideoRef={handleVideoRef} />
        )}
        {tirAvailable && (
          <ChannelLayer camera={camera} channel="tir" active={channel === "tir"} onVideoRef={handleVideoRef} />
        )}
      </div>
    );
  }
);
