// components/outposts/OutpostEditor.tsx — 설정 페이지: 초소 위치 지도(클릭 마킹) + 정보 편집기.
// ui/outposts/editor.py 이식. admin은 편집(클릭 추가/정보 수정/삭제), user는 조회만.
// 영상은 로컬 경로로 지정되므로 업로드 UI는 없습니다.
import { type MouseEvent } from "react";
import { outpostMapImageUrl } from "../../api/client";
import { useCreateOutpost, useDeleteOutpost, useOutposts, useUpdateOutpost } from "../../api/hooks";
import { useAuth } from "../../context/AuthContext";

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
          <strong>{isAdmin ? "지도 미리보기 (클릭하여 초소 추가)" : "지도 미리보기 (조회 전용)"}</strong>
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
          <strong>초소 정보</strong>
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
                  <button
                    className="btn btn-sm btn-icon btn-danger"
                    title={`CCTV${i + 1} — 마커 삭제`}
                    onClick={() => deleteMutation.mutate(o.id)}
                  >
                    🗑
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
