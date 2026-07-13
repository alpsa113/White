// components/Sidebar.tsx — 좌측 네비게이션(로고/야경 배경 + 실시간 감시·감지 기록·설정, 하단 계정/로그아웃).
// ui/layout.py의 render_sidebar()를 이식했습니다.
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function Sidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `btn btn-block${isActive ? " btn-primary" : ""}`;

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <img src="/assets/sidebar_logo.png" alt="HEIMDALL" />
      </div>

      <nav className="sidebar-nav">
        <NavLink to="/dashboard" className={navClass}>
          실시간 감시
        </NavLink>
        <NavLink to="/logs" className={navClass}>
          감지 기록
        </NavLink>
        <NavLink to="/settings" className={navClass}>
          설정
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-account">
          {user?.username ?? ""} · {user?.role === "admin" ? "관리자" : "병사"}
        </div>
        <button className="btn btn-block" onClick={handleLogout}>
          로그아웃
        </button>
      </div>
    </aside>
  );
}
