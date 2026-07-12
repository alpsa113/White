// pages/SettingsPage.tsx — views/settings.py 이식. 초소 지도 편집기 + 시스템 상태.
import { OutpostEditor } from "../components/outposts/OutpostEditor";
import { useSystemStatus } from "../api/hooks";

export default function SettingsPage() {
  const { data: status } = useSystemStatus();

  return (
    <div className="page">
      <OutpostEditor />

      <hr className="divider" />
      <h3>시스템 설정</h3>

      <strong>시스템 상태</strong>
      <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
        {status?.rds === "ok" ? (
          <div className="success-banner">🟢 RDS 연결됨 - 로그가 영구 저장됩니다.</div>
        ) : (
          <div className="warning-banner">🟡 메모리 모드 - RDS 미연결 (로그는 재시작 시 사라짐).</div>
        )}
        {status?.s3 === "ok" ? (
          <div className="success-banner">🟢 S3 연결됨 - 탐지 스냅샷 이미지가 영구 저장됩니다.</div>
        ) : (
          <div className="warning-banner">🟡 S3 미연결 - 스냅샷은 메모리에만 보관되며 재시작 시 사라짐.</div>
        )}
      </div>
    </div>
  );
}
