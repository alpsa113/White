# GOP 통합 감시 시스템

CCTV 영상(EO/TIR)에서 사람·멧돼지·고라니·소형동물을 탐지해 실시간 알림·로그·클립으로 남기는
관제 시스템입니다. **FastAPI 백엔드 + React 프론트엔드**로 구성되어 있고, 로그는 AWS
RDS(MySQL), 스냅샷/클립은 AWS S3에 저장합니다(미설정 시 메모리 전용 모드로 자동 대체).

영상은 실시간 스트림이 아니라 이미 존재하는 파일을 반복 재생하는 방식이라, 지정되는 순간
백그라운드에서 한 번 미리 분석해 캐싱해두고 그 결과를 재생 속도에 맞춰 흘려보내는 2단계
파이프라인을 씁니다. 이 설계의 배경과 근거는 [PIPELINE_DESIGN.md](PIPELINE_DESIGN.md)를
참고하세요.

- **실시간 감시**: 카메라 그리드/확대 보기, EO/TIR 채널 전환, 초소 미니맵(마커 클릭 선택), 탐지 이력 패널(클릭 시 상세/클립 보기), 사람 탐지 시 마커 점멸 + 알림음, 동물 탐지 시 토스트
- **감지 기록**: 탐지 로그 조회(스냅샷/클립 재생) 및 편집·삭제(관리자)
- **설정**: 초소(카메라 위치) 지도 마킹, EO/TIR 영상 업로드, 시스템 상태(RDS/S3 연결)

---

## 1. 디렉토리 구조

```
gop_detection_0711_react_test/
├── backend.py              # FastAPI 앱 진입점(uvicorn 실행 대상), 서버 시작/종료 훅
├── config.py                # 전역 설정값(계정, 클래스 색상, 클립/트래킹 튜닝값 등)
├── state_store.py           # 프로세스 전역 인메모리 상태(초소/로그 캐시/토스트)
├── db_rds.py                 # AWS RDS(MySQL) 연동 — 테이블 생성/조회/삽입/수정/삭제
├── s3_storage.py              # AWS S3 스냅샷/클립 업로드·다운로드·삭제, presigned URL
├── requirements.txt           # 백엔드 의존성 목록
│
├── routers/                  # FastAPI 라우터(REST 엔드포인트)
│   ├── auth.py                  # 로그인
│   ├── outposts.py               # 초소(지도 마커) CRUD, EO/TIR 영상 업로드
│   ├── cameras.py                # 카메라 목록/채널 전환, 영상 파일 서빙, 분석 상태/타임라인
│   ├── tracking.py               # 최근 탐지 이력/토스트 폴링
│   ├── settings.py               # 시스템 상태(RDS/S3 연결)
│   └── logs.py                   # 로그 조회/편집/삭제, 스냅샷·클립 서빙
│
├── services/                 # 화면과 무관한 백엔드 로직
│   ├── model_runtime.py          # YOLO 로컬 추론
│   ├── detection.py               # 추론 호출 + 박스 그리기
│   ├── tracking.py                # 프레임별 탐지를 트랙에 연결해 신규/갱신 알람 판단
│   ├── video_analyzer.py          # 영상 사전 분석 + 실시간 페이스 재생 + 클립 추출(2단계 파이프라인 핵심)
│   ├── alerts.py                  # 탐지 로그 생성/갱신, DB 동기화
│   ├── outposts.py                 # 초소(마커) CRUD, EO/TIR 영상 매핑
│   ├── camera_registry.py          # 초소 목록 → 카메라 목록 변환
│   ├── log_management.py           # 로그 편집 저장 처리
│   └── audio_alert.py              # 알림음 WAV 생성
│
├── assets/gop_preset_map.png  # 초소 지도 이미지
├── weights/                   # YOLO 가중치 파일(MODEL_PATH로 경로 지정)
├── videos/                    # 시연용 로컬 영상(config.DEMO_VIDEOS가 참조)
├── uploads/outpost_videos/    # 관리자가 업로드한 EO/TIR 영상(서버 기동 시 정리됨)
│
└── frontend/                  # React + Vite 프론트엔드
    └── src/
        ├── api/                  # REST 클라이언트(client.ts) + react-query 훅(hooks.ts)
        ├── context/               # 인증/실시간 탐지 상태 Context
        ├── pages/                 # LoginPage / DashboardPage / LogsPage / SettingsPage
        └── components/            # camera/ detections/ logs/ map/ outposts/ 등
```

**의존 방향**: `routers → services → db_rds.py / s3_storage.py` 순으로 import합니다.
`services`는 `routers`를 참조하지 않습니다.

---

## 2. 실행 방법

### 2.1 백엔드

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

필요 파일:
- YOLO 가중치 파일(`MODEL_PATH` 환경변수로 경로 지정, 기본값 `weights/best.pt`)
- 프로젝트 루트의 `.env` — RDS/S3 자격증명(미설정 시 메모리 전용 모드로 자동 대체):

```env
RDS_DIALECT=mysql+pymysql
RDS_HOST=...
RDS_PORT=3306
RDS_DATABASE=...
RDS_USERNAME=...
RDS_PASSWORD=...

S3_BUCKET=...
S3_REGION=ap-northeast-2
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...

MODEL_PATH=weights/best.pt
CONF_THRESHOLD=0.7
NMS_THRESHOLD=0.7
```

실행:

```bash
uvicorn backend:app --reload --port 8000
```

`http://127.0.0.1:8000/health` → `{"status": "ok", "model_loaded": true}` 확인.

### 2.2 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

백엔드 주소가 기본값(`http://127.0.0.1:8000`)과 다르면 `frontend/.env`에
`VITE_API_BASE_URL`을 지정하세요.

### 2.3 사용 순서

1. 로그인(`config.USERS`: `admin`/`admin1234`, `user`/`user1234`) — 관리자는 설정 페이지로,
   병사는 실시간 감시 페이지로 이동합니다.
2. (관리자) **설정** 페이지에서 지도를 클릭해 초소 마커를 등록하면, `config.DEMO_VIDEOS`가
   채워져 있을 경우 순서대로 영상이 자동 배정됩니다(직접 업로드도 가능).
3. **실시간 감시** 페이지에서 영상이 자동 재생되고, 카드의 EO/TIR 버튼으로 채널을 전환할 수
   있습니다. 사람 탐지 시 미니맵 마커가 점멸하고 알림음이 울리며, 동물 탐지는 우상단 토스트로
   표시됩니다.
4. **감지 기록** 페이지에서 과거 로그를 조회(스냅샷/클립 재생)하거나, 관리자는 편집·삭제할 수
   있습니다.

---

## 3. 주요 튜닝 값 (`config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PERSON_GAP_TOLERANCE` | 10 | 사람/동물이 프레임에서 사라져도 같은 트랙으로 유지할 프레임 수. |
| `ANIMAL_TOAST_COOLDOWN` | 10 | 동일 동물 클래스 토스트 알림 억제 간격(초). |
| `CLIP_PRE_SECONDS` / `CLIP_POST_SECONDS` | 3.0 / 3.0 | 클립 시작/종료 전후 여유 시간(초). |
| `MAX_CLIP_SECONDS` | 60.0 | 트랙이 비정상적으로 길게 지속될 때 클립 길이 안전 상한. |
| `CLIP_EXTRACTION_WORKERS` | 2 | 클립 추출 동시 실행 개수(초과분은 큐에서 순서대로 처리). |
| `DEMO_VIDEOS` | (4개) | 시연용 사전 등록 영상 — 마커를 찍는 순서대로 로컬 영상 경로가 자동 배정됨. |
