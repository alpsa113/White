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

  return (
    <>
      {isAuthenticated && !isLiveMonitoringPage && <AnimalToastHost />}
      <Routes>
        <Route
          path="/login"
          element={isAuthenticated ? <Navigate to={homePath} replace /> : <LoginPage />}
        />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <AppShell>
                <DashboardPage />
              </AppShell>
            </ProtectedRoute>
          }
        />
        <Route
          path="/logs"
          element={
            <ProtectedRoute>
              <AppShell>
                <LogsPage />
              </AppShell>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute adminOnly>
              <AppShell>
                <SettingsPage />
              </AppShell>
            </ProtectedRoute>
          }
        />
        <Route path="/" element={<Navigate to={homePath} replace />} />
        <Route path="*" element={<Navigate to={homePath} replace />} />
      </Routes>
    </>
  );
}
