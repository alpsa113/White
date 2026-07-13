// components/logs/LogViewTab.tsx — 조회 탭: 정렬/필터 가능한 표 + 선택 행 스냅샷/클립 뷰어.
// ui/log_tabs.py render_view_tab() 이식.
import { useMemo, useState } from "react";
import { logSnapshotUrl } from "../../api/client";
import { fmtDt, fmtPercent, isPersonClass } from "../../utils/formatters";
import type { LogEntry } from "../../types";

type SortKey = "id" | "camera" | "created_at" | "class_name" | "score";

interface LogViewTabProps {
  logs: LogEntry[];
}

export function LogViewTab({ logs }: LogViewTabProps) {
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDesc, setSortDesc] = useState(true);
  const [cameraFilter, setCameraFilter] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const cameraOptions = useMemo(() => Array.from(new Set(logs.map((l) => l.camera))).sort(), [logs]);
  const classOptions = useMemo(() => Array.from(new Set(logs.map((l) => l.class_name))).sort(), [logs]);

  const filtered = useMemo(() => {
    return logs.filter(
      (l) => (!cameraFilter || l.camera === cameraFilter) && (!classFilter || l.class_name === classFilter)
    );
  }, [logs, cameraFilter, classFilter]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      let av: string | number = a[sortKey] as string | number;
      let bv: string | number = b[sortKey] as string | number;
      if (sortKey === "created_at") {
        av = fmtDt(a);
        bv = fmtDt(b);
      }
      if (av < bv) return sortDesc ? 1 : -1;
      if (av > bv) return sortDesc ? -1 : 1;
      return 0;
    });
    return copy;
  }, [filtered, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDesc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const selected = sorted.find((l) => l.id === selectedId) ?? null;

  return (
    <div>
      <div className="log-filters">
        <select value={cameraFilter} onChange={(e) => setCameraFilter(e.target.value)}>
          <option value="">전체 카메라</option>
          {cameraOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={classFilter} onChange={(e) => setClassFilter(e.target.value)}>
          <option value="">전체 클래스</option>
          {classOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div className="log-view-body">
        <div className="log-table-col">
          <table className="log-table">
            <thead>
              <tr>
                <th onClick={() => toggleSort("id")}>탐지 ID</th>
                <th onClick={() => toggleSort("camera")}>카메라</th>
                <th onClick={() => toggleSort("created_at")}>탐지 일시</th>
                <th onClick={() => toggleSort("class_name")}>클래스명</th>
                <th onClick={() => toggleSort("score")}>신뢰도 (Score)</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((l) => (
                <tr
                  key={l.id}
                  className={l.id === selectedId ? "selected" : ""}
                  onClick={() => setSelectedId(l.id)}
                >
                  <td>{l.id}</td>
                  <td>{l.camera}</td>
                  <td>{fmtDt(l)}</td>
                  <td className={isPersonClass(l.class_name) ? "person-cell" : ""}>{l.class_name}</td>
                  <td>{fmtPercent(l.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="log-img-col">
          {!selected ? (
            <div className="info-banner">왼쪽 표에서 행을 클릭하면 해당 객체의 탐지 이미지가 표시됩니다.</div>
          ) : (
            <div>
              <div>
                <strong>카메라: {selected.camera}</strong> &nbsp;|&nbsp; 클래스: <code>{selected.class_name}</code>{" "}
                &nbsp;|&nbsp; Score: <strong>{fmtPercent(selected.score)}</strong>
              </div>
              <div className="camera-caption">탐지시각: {fmtDt(selected)}</div>
              <hr className="divider" />
              {selected.content_type === "video/mp4" ? (
                <video src={logSnapshotUrl(selected.id)} controls style={{ width: "100%", borderRadius: 4 }} />
              ) : (
                <img
                  src={logSnapshotUrl(selected.id)}
                  alt="탐지 순간 캡처"
                  style={{ width: "100%", borderRadius: 4 }}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
