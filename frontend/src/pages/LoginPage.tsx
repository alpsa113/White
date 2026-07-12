// pages/LoginPage.tsx — views/login.py 이식. 배경 이미지 + ID/유형/PW 입력 + 로그인 버튼.
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useLogin } from "../api/hooks";
import { ApiError } from "../api/client";
import type { Role } from "../types";

const USER_TYPE_OPTIONS: Record<string, Role> = { 관리자: "admin", 병사: "user" };

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [typeLabel, setTypeLabel] = useState("관리자");
  const [error, setError] = useState<string | null>(null);
  const { login: setAuthUser } = useAuth();
  const loginMutation = useLogin();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const role = USER_TYPE_OPTIONS[typeLabel];
    try {
      const user = await loginMutation.mutateAsync({ username, password, role });
      setAuthUser(user);
      navigate(user.role === "admin" ? "/settings" : "/dashboard", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("ID, 비밀번호 또는 사용자 유형이 올바르지 않습니다.");
      } else {
        setError("로그인 요청에 실패했습니다. 서버 연결을 확인하세요.");
      }
    }
  };

  return (
    <div className="login-page">
      <form className="login-panel" onSubmit={handleSubmit}>
        <div className="login-title">HEIMDALL 관제 콘솔</div>

        <div>
          <label htmlFor="login-id">ID</label>
          <input
            id="login-id"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </div>

        <div>
          <label htmlFor="login-type">사용자 유형</label>
          <select id="login-type" value={typeLabel} onChange={(e) => setTypeLabel(e.target.value)}>
            {Object.keys(USER_TYPE_OPTIONS).map((label) => (
              <option key={label} value={label}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="login-pw">PW</label>
          <input
            id="login-pw"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>

        {error && <div className="login-error">{error}</div>}

        <button type="submit" className="btn btn-primary btn-block" disabled={loginMutation.isPending}>
          {loginMutation.isPending ? "로그인 중..." : "로그인"}
        </button>
      </form>
    </div>
  );
}
