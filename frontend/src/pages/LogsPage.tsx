// pages/LogsPage.tsx — views/logs.py 이식. 조회/편집 두 탭(편집은 admin 전용).
import { useMemo, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useLogs } from "../api/hooks";
import { LogViewTab } from "../components/logs/LogViewTab";
import { LogManageTab } from "../components/logs/LogManageTab";
import { fmtDt } from "../utils/formatters";

export default function LogsPage() {
  const { isAdmin } = useAuth();
  const { data: logs = [], isLoading } = useLogs();
  const [tab, setTab] = useState<"view" | "manage">("view");

  const sortedLogs = useMemo(
    () =>
      [...logs].sort((a, b) => {
        const av = `${fmtDt(a)}`;
        const bv = `${fmtDt(b)}`;
        if (av !== bv) return av < bv ? 1 : -1;
        return b.id - a.id;
      }),
    [logs]
  );

  if (isLoading) {
    return (
      <div className="page">
        <div className="info-banner">불러오는 중...</div>
      </div>
    );
  }

  if (sortedLogs.length === 0) {
    return (
      <div className="page">
        <div className="info-banner">현재 기록된 탐지 데이터가 없습니다.</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="log-tabs">
        <button className={`log-tab-btn${tab === "view" ? " active" : ""}`} onClick={() => setTab("view")}>
          로그 및 클립 조회
        </button>
        {isAdmin && (
          <button className={`log-tab-btn${tab === "manage" ? " active" : ""}`} onClick={() => setTab("manage")}>
            로그 편집 및 삭제
          </button>
        )}
      </div>

      {tab === "view" && <LogViewTab logs={sortedLogs} />}
      {tab === "manage" && isAdmin && <LogManageTab logs={sortedLogs} />}
    </div>
  );
}
