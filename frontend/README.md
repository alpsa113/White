# GOP 관제 콘솔 — React 프론트엔드

Streamlit 앱을 대체하는 React + TypeScript 프론트엔드입니다. 비디오는 브라우저가 원본 영상을
네이티브로 재생하고, 사전 분석된 탐지 timeline을 canvas overlay로 동기화해 표시합니다.
나머지 상태는 FastAPI 백엔드의 REST API를 `@tanstack/react-query`로 폴링/호출합니다.

## 실행 방법

```bash
cd frontend
npm install
cp .env.example .env   # 필요 시 VITE_API_BASE_URL 수정 (기본값: http://127.0.0.1:8000)
npm run dev
```

기본적으로 http://localhost:5173 에서 뜹니다. FastAPI 백엔드가 `VITE_API_BASE_URL`에 떠 있어야
로그인/카메라/로그 등 모든 화면이 정상 동작합니다.

## 빌드 / 타입체크

```bash
npm run build   # tsc --noEmit 후 vite build
npm run lint    # tsc --noEmit 만 실행
```

## 폴더 구조

```
src/
  api/         REST fetch 클라이언트(client.ts) + react-query 훅(hooks.ts)
  components/  재사용 UI 조각 (camera/, map/, detections/, logs/, outposts/, Sidebar, HeaderClock, ProtectedRoute)
  context/     AuthContext (localStorage 기반 로그인 상태)
  pages/       라우트 4개: LoginPage, DashboardPage, LogsPage, SettingsPage
  styles/      theme.css(색상 변수) + global.css(레이아웃/컴포넌트 스타일)
  types.ts     REST 계약과 1:1로 맞춘 도메인 타입
public/
  assets/      로그인 배경, 사이드바 로고/야경, 초소 지도 프리셋 이미지 (Streamlit assets/ 복사본)
  icons/       탐지 클래스 아이콘 (person/boar/deer/small_object)
```

## 알아둘 점

- 인증은 토큰 없이 `POST /api/auth/login` 성공 응답(`{username, role}`)을 그대로
  `localStorage`에 저장하는 방식입니다(기존 Streamlit 세션과 동일한 무인증 설계).
- `admin` 역할만 로그 편집 탭, 데모 모드 토글, 초소 지도 편집(마커 추가/삭제)을 사용할 수
  있습니다. `user` 역할은 조회 전용 화면을 봅니다.
- 영상은 브라우저 업로드가 아니라 백엔드 `config.py`의 `DEMO_VIDEOS`에 지정된 로컬 경로를
  마커 생성 순서대로 자동 매핑하는 방식입니다.
- 영상은 `/api/cameras/{camera_id}/video`에서 Range 요청으로 서빙하고, 탐지 결과는
  `/api/cameras/{camera_id}/detections-timeline`에서 받아 `<canvas>`에 그립니다.
