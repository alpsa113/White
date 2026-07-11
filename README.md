# GOP 통합 감시 시스템

CCTV 영상(EO/TIR)에서 사람·동물을 실시간으로 탐지해 알림·로그·클립으로
남기는 Streamlit 기반 관제 시스템입니다. 화면(Streamlit)과 모델 추론
(FastAPI + YOLO)은 별도 프로세스로 분리되어 있고, 로그는 AWS RDS(MySQL),
스냅샷/클립은 AWS S3에 저장합니다(미설정 시 메모리 전용 모드로 동작).

- **관제 대시보드**: 카메라 그리드/스포트라이트, EO/TIR 채널 전환, 초소 미니맵
- **감지 기록**: 탐지 로그 조회 및 편집(관리자)
- **설정**: 초소(카메라) 위치·영상 매핑 관리, 데모 모드, 시스템 상태

---

## 1. 디렉토리 구조

```
project/
├── app.py                    # 메인 엔트리포인트 (streamlit run 대상)
├── config.py                 # 전역 설정값 (계정, 클래스 색상, 임계값, 클립/메모리 튜닝 등)
├── state.py                  # session_state 초기화
├── backend.py                # FastAPI 추론 서버 (별도 프로세스, uvicorn으로 실행)
├── db_rds.py                 # AWS RDS(MySQL) 연동
├── s3_storage.py              # AWS S3 이미지/클립 저장 연동
├── requirements.txt           # 의존성 목록
│
├── assets/gop_preset_map.png   # 초소 지도 이미지 (config.PRESET_MAP_IMAGE_PATH)
│
├── services/                  # 화면과 무관한 로직 (탐지/트래킹/재생/DB/S3/클립/초소 관리)
├── ui/                        # Streamlit 화면(위젯) 렌더링 전담
│   ├── camera/                  # 카메라 카드/그리드/스포트라이트/줌/툴바
│   └── outposts/                 # 초소(지도 마커) 편집·조회 화면
├── views/                     # 페이지 단위 조립 (ui + services 호출만)
└── utils/formatters.py        # 화면 표시용 포맷 함수
```

**의존 방향**: `views → ui → services → db_rds.py / s3_storage.py` 순으로만
import합니다. `services`/`ui`는 `views`를 참조하지 않습니다.

---

## 2. 파일별 역할

### 루트

| 파일 | 역할 |
|---|---|
| `app.py` | 페이지 설정 → 세션 초기화 → 로그인 게이트 → 사이드바 → 현재 페이지 렌더 → 재생 루프 실행. |
| `config.py` | 계정(`USERS`), 클래스 색상(`COLORS`), 탐지/클립 튜닝값, 카메라 상한 등 전역 설정. |
| `state.py` | 앱 (재)시작 시 `st.session_state` 기본값 초기화, DB/S3 연결 확인. |
| `backend.py` | YOLO 추론 서버. `/detect`(단건 추론), `/health`, `/stream`(MJPEG 실시간 스트리밍). |
| `db_rds.py` | RDS 테이블 생성/조회/삽입/수정/삭제, 클래스명↔class_id 매핑. |
| `s3_storage.py` | S3 스냅샷/클립 업로드·다운로드·삭제, 임시 접근 URL 발급. |

### `services/` — 화면 없는 로직

| 파일 | 역할 |
|---|---|
| `detection.py` | 백엔드 API 호출(`run_detection`), 박스 그리기, 데모 모드 시뮬레이션. |
| `tracking.py` | 프레임 단위 탐지 결과를 사람/동물 트랙에 연결해 신규/갱신 알람 판단. |
| `playback.py` | 카메라별 EO/TIR 재생 루프, 미디어 반영(`start_camera_media`), 채널 상태 정리. |
| `clip_recorder.py` | 탐지 전후 클립(mp4) 버퍼링·인코딩·S3 업로드. |
| `alerts.py` | 탐지 로그 생성/갱신, DB 동기화, 스냅샷 S3 업로드. |
| `camera_registry.py` | 초소 목록 → 카메라 목록 변환, 채널 자동 재생 반영, 정리. |
| `outposts.py` | 초소(마커) CRUD, EO/TIR 영상 매핑. |
| `log_management.py` | 로그 편집 탭 저장 처리(변경분만 반영). |
| `audio_alert.py` | 사람 탐지 시 알림음 재생. |

### `ui/` — 화면 렌더링

| 파일 | 역할 |
|---|---|
| `styles.py` | 화면 전반의 CSS 스니펫/템플릿 모음(레이아웃 고정, 카드, 지도 마커 등). 페이지별 CSS는 여기 모아두고 각 파일은 import해서 씁니다. |
| `layout.py` | 사이드바(네비게이션·계정 영역) 렌더링. |
| `log_tabs.py` | 감지 기록의 조회 탭 + 편집 탭. |
| `camera/card.py` | 카메라 카드(툴바+영상+EO/TIR 전환+확대). |
| `camera/grid.py` / `spotlight.py` | 그리드 배치 / 확대 보기(카메라+지도 2행, 나머지 카메라 목록). |
| `camera/zoom.py` / `toolbar.py` | 확대·이동(JS), 헤더 시계 + 카메라 자동 전환 소비. |
| `outposts/editor.py` | 설정 페이지: 지도 클릭 마킹 + 초소 정보/영상 매핑 편집. |
| `outposts/viewer.py` / `marker_overlay.py` | 관제 지도(마커+점멸) 렌더링 및 선택 상태 공용 로직. |

### `views/` — 페이지 조립

| 파일 | 역할 |
|---|---|
| `login.py` | 로그인(ID + 사용자 유형 + PW). |
| `dashboard.py` | 관제 대시보드(그리드/스포트라이트/미니맵/탐지 이력). |
| `logs.py` | 감지 기록(조회 탭 공통, 편집 탭은 관리자 전용). |
| `settings.py` | 설정(초소 관리, 데모 모드, 시스템 상태). |

---

## 3. 실행 방법

### 3.1 사전 준비

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

필요 라이브러리(`requirements.txt`):
- 백엔드: `fastapi`, `uvicorn`, `ultralytics`, `python-multipart`
- 프론트엔드: `streamlit`, `pandas`, `numpy`, `opencv-python`(헤드리스 서버는 `opencv-python-headless`)
- 지도 클릭 마킹: `streamlit-image-coordinates`
- 클립 인코딩: `imageio`, `imageio-ffmpeg`(ffmpeg 별도 설치 불필요)
- 공통: `pillow`, `requests`
- AWS 연동: `sqlalchemy`, `pymysql`, `boto3`

필요 파일:
- YOLO 가중치 파일 (`MODEL_PATH` 환경변수로 경로 지정, 기본값 `weights/best.pt`)
- `.streamlit/secrets.toml` — RDS/S3 자격증명(미설정 시 메모리 전용 모드로 자동 대체):

```toml
[connections.gop_db]
url = "mysql+pymysql://<user>:<password>@<host>:3306/<db_name>"

[s3]
region = "ap-northeast-2"
bucket = "your-bucket-name"
access_key_id = "..."
secret_access_key = "..."
```

### 3.2 서버 실행 (터미널 2개 필요)

```bash
# 터미널 1 — 추론 백엔드
export MODEL_PATH=weights/best.pt        # PowerShell: $env:MODEL_PATH="weights/best.pt"
uvicorn backend:app --reload --port 8000

# 터미널 2 — Streamlit 프론트엔드
streamlit run app.py
```

- `http://127.0.0.1:8000/health` → `{"status": "ok", "model_loaded": true}` 확인.
- 백엔드 주소가 기본값과 다르면 `API_BASE_URL` 환경변수로 지정.
- 브라우저가 `API_BASE_URL`로 직접 접속하므로(화면 표시용 `/stream`), 백엔드와
  브라우저가 다른 컴퓨터에 있다면 브라우저 기준으로 도달 가능한 주소를 지정해야 합니다.

### 3.3 사용 순서

1. `http://localhost:8501` 접속 → 로그인 (`config.USERS`: `admin`/`admin1234`, `user`/`user1234`)
2. (관리자) **설정** 페이지에서 지도를 클릭해 초소 마커 등록 → 초소별 EO/TIR 영상 매핑
3. **관제 대시보드**에서 EO 영상이 자동 재생 시작, 카드의 EO/TIR 버튼으로 채널 전환
4. 사이드바 **설정 → 데모 모드**를 끄면 실제 모델 추론(백엔드 `/stream`) 사용, 켜면 무작위 탐지로 화면 동작만 확인

---

## 4. 주요 튜닝 값 (`config.py`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DETECT_EVERY_SECONDS` | 0.75 | 추론 호출 최소 간격(초). 값이 클수록 부하는 줄지만 박스 갱신이 뜸해짐. |
| `CLIP_PRE_SECONDS` / `CLIP_POST_SECONDS` | 3.0 / 3.0 | 탐지 전후 클립 길이(초). |
| `CLIP_STORAGE_MAX_WIDTH` | 480 | 클립/버퍼 저장 프레임의 최대 가로 해상도(메모리 절감용, 화면 표시엔 영향 없음). |
| `MAX_PENDING_CLIPS_PER_CAMERA` | 2 | 카메라 1대당 동시 대기 클립 개수 상한. 초과하면 해당 탐지는 클립 없이 로그만 남음. |
| `MAX_CAMERAS` | 16 | 카메라 개수 상한(실제 개수는 초소 마커 개수로 결정). |