// components/logs/LogManageTab.tsx — 편집 탭(admin 전용): 클래스/상태/비고 편집, 행 삭제, 일괄 저장.
// ui/log_tabs.py render_manage_tab() 이식 — st.data_editor 대신 편집 가능한 HTML 테이블.
import { useMemo, useState } from "react";
import { useSaveLogEdits } from "../../api/hooks";
import { fmtDt } from "../../utils/formatters";
import type { LogEntry, LogUpdate } from "../../types";

const KNOWN_CLASSES = ["사람", "멧돼지", "고라니", "소형동물"];
const STATUS_OPTIONS = ["대기", "오탐", "사람탐지(경보)", "동물탐지"];

interface EditRow {
  id: number;
  created_at: string;
  camera: string;
  class_name: string;
  score: number;
  uri?: string;
  status: string;
  remarks: string;
  deleted: boolean;
  dirty: boolean;
}

function toRows(logs: LogEntry[]): EditRow[] {
  return logs.map((l) => ({
    id: l.id,
    created_at: fmtDt(l),
    camera: l.camera,
    class_name: l.class_name,
    score: Math.round(l.score * 1000) / 10,
    uri: l.uri,
    status: l.status || "대기",
    remarks: l.remarks || "",
    deleted: false,
    dirty: false,
  }));
}

interface LogManageTabProps {
  logs: LogEntry[];
}

export function LogManageTab({ logs }: LogManageTabProps) {
  const [rows, setRows] = useState<EditRow[]>(() => toRows(logs));
  const [message, setMessage] = useState<string | null>(null);
  const saveMutation = useSaveLogEdits();

  const classOptions = useMemo(
    () => Array.from(new Set([...KNOWN_CLASSES, ...rows.map((r) => r.class_name)])).sort(),
    [rows]
  );

  const updateRow = (id: number, patch: Partial<EditRow>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch, dirty: true } : r)));
  };

  const toggleDelete = (id: number) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, deleted: !r.deleted } : r)));
  };

  const handleSave = async () => {
    const updates: LogUpdate[] = rows
      .filter((r) => r.dirty && !r.deleted)
      .map((r) => ({
        id: r.id,
        class_name: r.class_name,
        camera: r.camera,
        status: r.status,
        remarks: r.remarks,
      }));
    const deletes = rows.filter((r) => r.deleted).map((r) => r.id);

    if (updates.length === 0 && deletes.length === 0) {
      setMessage("변경된 내용이 없습니다.");
      return;
    }

    try {
      await saveMutation.mutateAsync({ updates, deletes });
      const parts: string[] = [];
      if (deletes.length) parts.push(`${deletes.length}개 행 삭제`);
      if (updates.length) parts.push(`${updates.length}개 행 수정`);
      setMessage(`${parts.join(" / ")} 완료`);
      setRows((prev) => prev.filter((r) => !r.deleted).map((r) => ({ ...r, dirty: false })));
    } catch {
      setMessage("저장 중 오류가 발생했습니다.");
    }
  };

  return (
    <div>
      <p className="camera-caption">
        셀을 직접 클릭하여 수정할 수 있습니다. 삭제할 행은 우측 삭제 버튼으로 표시한 뒤 아래 "변경사항 저장"
        버튼을 누르세요.
      </p>

      {message && <div className="info-banner">{message}</div>}

      <div className="log-editor-table-wrap">
        <table className="log-table log-editor-table">
          <thead>
            <tr>
              <th>탐지 ID</th>
              <th>탐지 일시</th>
              <th>카메라</th>
              <th>클래스명</th>
              <th>신뢰도 (%)</th>
              <th>상태</th>
              <th>비고</th>
              <th>삭제</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={r.deleted ? { opacity: 0.4, textDecoration: "line-through" } : undefined}>
                <td>{r.id}</td>
                <td>{r.created_at}</td>
                <td>
                  <input
                    type="text"
                    value={r.camera}
                    disabled={r.deleted}
                    onChange={(e) => updateRow(r.id, { camera: e.target.value })}
                  />
                </td>
                <td>
                  <select
                    value={r.class_name}
                    disabled={r.deleted}
                    onChange={(e) => updateRow(r.id, { class_name: e.target.value })}
                  >
                    {classOptions.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{r.score.toFixed(1)}%</td>
                <td>
                  <select
                    value={r.status}
                    disabled={r.deleted}
                    onChange={(e) => updateRow(r.id, { status: e.target.value })}
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="text"
                    value={r.remarks}
                    disabled={r.deleted}
                    onChange={(e) => updateRow(r.id, { remarks: e.target.value })}
                  />
                </td>
                <td>
                  <button className="btn btn-sm btn-danger" onClick={() => toggleDelete(r.id)}>
                    {r.deleted ? "복원" : "삭제"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="log-editor-actions">
        <button className="btn btn-primary" onClick={handleSave} disabled={saveMutation.isPending}>
          변경사항 저장
        </button>
      </div>
    </div>
  );
}
