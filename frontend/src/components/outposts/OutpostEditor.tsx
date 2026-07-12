// components/outposts/OutpostEditor.tsx — 설정 페이지: 초소 위치 지도(클릭 마킹) + 정보/영상 매핑 편집기.
// ui/outposts/editor.py 이식. admin은 편집(클릭 추가/정보 수정/영상 업로드/삭제), user는 조회만.
import { useState, type MouseEvent } from "react";
import { outpostMapImageUrl } from "../../api/client";
import {
  useCreateOutpost,
  useDeleteOutpost,
  useOutposts,
  useUpdateOutpost,
  useUploadOutpostVideo,
} from "../../api/hooks";
import { useAuth } from "../../context/AuthContext";
import type { Channel, Outpost } from "../../types";

function VideoPopover({ outpost, index }: { outpost: Outpost; index: number }) {
  const [open, setOpen] = useState(false);
  const uploadMutation = useUploadOutpostVideo();

  const handleFile = (channel: Channel, file: File | undefined) => {
    if (!file) return;
    uploadMutation.mutate({ id: outpost.id, channel, file });
  };

  return (
    <div className="video-popover">
      <button className="btn btn-sm btn-icon" onClick={() => setOpen((v) => !v)} title="영상 매핑">
        🎬
      </button>
      {open && (
        <div className="video-popover-panel">
          <div className="vp-row">
            <div className="vp-status">
              EO(가시광): {outpost.video_eo_name ? `✅ ${outpost.video_eo_name}` : "⚠️ 매핑된 영상 없음"}
            </div>
            <input
              type="file"
              accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska"
              onChange={(e) => handleFile("eo", e.target.files?.[0])}
            />
          </div>
          <div className="vp-row">
            <div className="vp-status">
              TIR(열화상): {outpost.video_tir_name ? `✅ ${outpost.video_tir_name}` : "⚠️ 매핑된 영상 없음"}
            </div>
            <input
              type="file"
              accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska"
              onChange={(e) => handleFile("tir", e.target.files?.[0])}
            />
          </div>
          <button className="btn btn-sm btn-block" onClick={() => setOpen(false)}>
            닫기
          </button>
        </div>
      )}
    </div>
  );
}

export function OutpostEditor() {
  const { isAdmin } = useAuth();
  const { data: outposts = [] } = useOutposts();
  const createMutation = useCreateOutpost();
  const updateMutation = useUpdateOutpost();
  const deleteMutation = useDeleteOutpost();

  const handleMapClick = (e: MouseEvent<HTMLImageElement>) => {
    if (!isAdmin) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x_ratio = (e.clientX - rect.left) / rect.width;
    const y_ratio = (e.clientY - rect.top) / rect.height;
    createMutation.mutate({ x_ratio, y_ratio });
  };

  return (
    <div>
      <h3>초소 위치 상황판</h3>
      {!isAdmin && <p className="camera-caption">현재 등록된 초소 위치와 정보를 조회할 수 있습니다 (조회 전용).</p>}

      <div className="settings-body">
        <div className="settings-map-col">
          <strong>{isAdmin ? "지도 미리보기 (클릭하여 마커 추가)" : "지도 미리보기 (조회 전용)"}</strong>
          <div className="map-wrap" style={{ marginTop: "0.4rem" }}>
            <img
              src={outpostMapImageUrl()}
              alt="초소 지도"
              onClick={handleMapClick}
              style={{ cursor: isAdmin ? "crosshair" : "default" }}
            />
            {outposts.map((o, i) => (
              <div
                key={o.id}
                className="map-editor-marker"
                style={{ left: `${o.x_ratio * 100}%`, top: `${o.y_ratio * 100}%` }}
              >
                {i + 1}
              </div>
            ))}
          </div>
        </div>

        <div className="settings-list-col">
          <strong>{isAdmin ? "초소 정보 · 영상 매핑" : "초소 정보"}</strong>
          {outposts.length === 0 ? (
            <p className="camera-caption">
              등록된 초소가 없습니다{isAdmin ? " — 왼쪽 지도를 클릭해 추가하세요." : "."}
            </p>
          ) : (
            outposts.map((o, i) => (
              <div className="outpost-row" key={o.id}>
                <div className="op-name">CCTV{i + 1}</div>
                <div className="op-info">
                  <input
                    type="text"
                    defaultValue={o.info}
                    disabled={!isAdmin}
                    placeholder={!isAdmin ? "(정보 없음)" : "초소 정보"}
                    onBlur={(e) => {
                      if (isAdmin && e.target.value !== o.info) {
                        updateMutation.mutate({ id: o.id, patch: { info: e.target.value } });
                      }
                    }}
                  />
                </div>
                {isAdmin && (
                  <>
                    <VideoPopover outpost={o} index={i} />
                    <button
                      className="btn btn-sm btn-icon btn-danger"
                      title={`CCTV${i + 1} — 마커 삭제`}
                      onClick={() => deleteMutation.mutate(o.id)}
                    >
                      🗑
                    </button>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
