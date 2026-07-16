import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AnimalToastHost } from "./components/AnimalToastHost";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Sidebar } from "./components/Sidebar";
import { useAuth } from "./context/AuthContext";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import LogsPage from "./pages/LogsPage";
import SettingsPage from "./pages/SettingsPage";

function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-content">{children}</div>
    </div>
  );
}

export default function App() {
  const { isAuthenticated, isAdmin } = useAuth();
  const homePath = isAdmin ? "/settings" : "/dashboard";
  const location = useLocation();
  const isLiveMonitoringPage = location.pathname === "/dashboard";

  // '실시간 감시'에 한 번 진입하면, 다른 페이지로 이동했다가 돌아와도 <video> 재생 위치가
  // 유지되도록 그 뒤로는 라우트 전환과 무관하게 항상 마운트해두고 CSS로만 숨깁니다(언마운트되면
  // 브라우저가 처음부터 다시 로드합니다). 방문 전까지는 불필요하게 영상을 미리 받아오지
  // 않도록 마운트를 미룹니다.
  const [dashboardMounted, setDashboardMounted] = useState(isLiveMonitoringPage);
  useEffect(() => {
    if (isLiveMonitoringPage) setDashboardMounted(true);
  }, [isLiveMonitoringPage]);

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <AppShell>
      {!isLiveMonitoringPage && <AnimalToastHost />}

      {dashboardMounted && (
        <div style={{ display: isLiveMonitoringPage ? "contents" : "none" }}>
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        </div>
      )}

      {!isLiveMonitoringPage && (
        <Routes>
          <Route path="/login" element={<Navigate to={homePath} replace />} />
          <Route
            path="/logs"
            element={
              <ProtectedRoute>
                <LogsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to={homePath} replace />} />
          <Route path="*" element={<Navigate to={homePath} replace />} />
        </Routes>
      )}
    </AppShell>
  );
}
