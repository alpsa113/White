# GOP 통합 감시 시스템 — 프로젝트 구조 가이드

## 1. 한눈에 보는 전체 구조

```
project/
├── app.py                    # 메인 엔트리포인트 (Streamlit 실행 시작점)
├── config.py                 # 전역 설정값 (카메라 목록, 임계값, 색상 등)
├── state.py                  # session_state 초기화
├── backend.py                # FastAPI 추론 서버 (별도 프로세스로 실행)
├── db_rds.py                 # AWS RDS(MySQL) 연동
├── s3_storage.py              # AWS S3 이미지 저장 연동
│
├── services/                  # 화면 없는 "로직" — DB/S3/추론 호출, 트래킹
│   ├── detection.py            # 백엔드 API 호출, 박스 그리기, 데모 데이터 생성
│   ├── alerts.py                # 탐지 로그 생성/갱신, DB 동기화
│   ├── video_tracking.py         # 영상 프레임 트래킹, 재생 루프
│   └── log_management.py          # 로그 편집/삭제 저장 처리
│
├── ui/                         # Streamlit 화면(위젯) 렌더링 전담
│   ├── layout.py                 # 사이드바 + 상단 네비게이션 + 실시간 시계
│   ├── camera_card.py              # 카메라 카드(그리드/집중보기) + 탐지 팝업
│   ├── alert_panel.py                # 우측 사람 탐지 경보 패널
│   └── log_tabs.py                    # 로그 조회 탭 + 편집 탭
│
├── views/                       # 페이지 단위 조립 (ui + services 호출만)
│   ├── dashboard.py               # 페이지1: 관제 대시보드
│   └── logs.py                     # 페이지2: 탐지 데이터 로그
│
└── utils/
    └── formatters.py              # 화면 표시용 순수 포맷 함수
```

**의존 방향 (이 순서를 거스르는 import는 없어야 합니다):**

```
views  →  ui  →  services  →  db_rds.py / s3_storage.py
  ↑          ↑         ↑
app.py가 최상단에서 모두를 조립
```

즉, `services/`는 `ui/`나 `views/`를 절대 import하지 않습니다. 반대로 `ui/`는
`services/`의 함수를 호출해서 화면을 그립니다. 이 규칙 덕분에 순환 참조 없이
어느 파일을 열어도 "이 파일보다 아래 계층만 참조한다"는 걸 알 수 있습니다.

---

## 2. 파일별 상세 설명

### 2.1 최상위

| 파일 | 역할 |
|---|---|
| `app.py` | `streamlit run`으로 실행되는 유일한 진입점. 페이지 설정 → `state.init_session_state()` → 사이드바/상단바 렌더링 → 현재 선택된 페이지(`views/dashboard.py` 또는 `views/logs.py`)의 `render()` 호출. 이 파일 자체엔 세부 로직이 없습니다. |
| `config.py` | 카메라 목록(`CAMERAS`), 클래스별 색상, 백엔드 API 주소, 트래킹 튜닝 값(`DETECT_INTERVAL` 등) 등 프로젝트 전역 상수. **값을 바꾸고 싶으면 이 파일 하나만 수정**하면 됩니다. |
| `state.py` | 앱이 (재)실행될 때마다 `st.session_state`에 필요한 키들의 기본값을 채워 넣습니다. DB/S3 연결 가능 여부 확인과 과거 로그를 메모리로 불러오는 것도 여기서 처리합니다. |
| `backend.py` | YOLO 모델을 메모리에 올려두고 `/detect` 엔드포인트로 이미지를 받아 탐지 결과(JSON)를 반환하는 FastAPI 서버. Streamlit과는 **별개의 프로세스**로 실행됩니다. 신뢰도 임계값(`CONF_THRESHOLD`)의 유일한 출처입니다. |
| `db_rds.py` | AWS RDS(MySQL) 연동. 테이블 생성(`init_db`), 로그 조회/추가/수정/삭제 함수 제공. |
| `s3_storage.py` | AWS S3 연동. 탐지 스냅샷 이미지 업로드/다운로드/삭제, 조회용 임시 URL 발급. |

### 2.2 `services/` — 화면 없는 로직

`st.markdown`, `st.button` 같은 화면 그리기 코드가 없는 "순수 로직" 계층입니다.
DB/S3 호출, 추론 호출, 상태 계산을 담당하며 `ui/`나 `views/`에서 함수만 호출해서 씁니다.

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `detection.py` | `run_detection()` | 백엔드(`backend.py`)에 이미지를 보내고 탐지 결과를 받아옵니다. 데모 모드일 땐 `simulate_detections()`가 대신 무작위 데이터를 만듭니다. |
| | `draw_boxes()` | 탐지된 바운딩 박스와 클래스명을 이미지 위에 그립니다. |
| | `is_person()` | 클래스명이 '사람'인지 판별합니다. |
| `alerts.py` | `create_detection_alert()` | 새로운 객체가 등장했을 때 로그 레코드를 만들고 DB에 저장합니다. 사람이면 경보 패널에 띄우고, 필요 시 팝업을 트리거합니다. |
| | `update_detection_alert()` | 영상에서 계속 추적 중인 객체의 신뢰도/프레임 수만 조용히 갱신합니다 (신규 알람 생성 안 함). |
| | `update_remark()`, `persist_log()` | 경보 패널 비고란 입력 콜백, 단일 로그 DB 동기화. |
| `video_tracking.py` | `process_frame()` | 프레임 1장을 분석하고, 사람 객체의 등장/사라짐을 추적해 신규 알람 여부를 결정합니다. |
| | `run_playback_loop()` | 여러 카메라의 영상을 번갈아 읽어 화면에 그리는 메인 재생 루프. |
| | `reset_cam_state()` | 카메라 채널 업로드/재생 상태 초기화. |
| `log_management.py` | `save_log_edits()` | 로그 편집 탭에서 '저장' 클릭 시, 수정/삭제된 행만 찾아 `session_state`·RDS·S3에 반영합니다. |

### 2.3 `ui/` — Streamlit 화면 렌더링

실제로 `st.*` 위젯을 그리는 계층입니다. 로직이 필요하면 `services/`의 함수를 호출만 합니다.

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `layout.py` | `render_sidebar()` | 좌측 사이드바 — 데모 모드 체크박스, DB 연결 상태 표시. |
| | `render_topnav()` | 상단 네비게이션 — "실시간 감시"/"관리자 로그" 전환 버튼 + 실시간 시계. |
| `camera_card.py` | `render_camera_grid()` | '전체 구역' 선택 시 2×2 카메라 그리드. |
| | `render_camera_focus()` | 특정 카메라 선택 시 확대 보기. |
| | `render_camera_card()` | 그리드/집중보기가 공통으로 쓰는 카드 1개 (업로드 + 영상 슬롯). |
| | `show_person_dialog()` | 탐지 스냅샷을 크게 보여주는 팝업. |
| `alert_panel.py` | `render_alert_panel()` | 우측 사람 탐지 경보 패널 (오탐/경보 처리 버튼 포함). |
| `log_tabs.py` | `render_view_tab()` | 로그 조회 탭 — 표 + 선택한 행의 탐지 이미지 뷰어. |
| | `render_manage_tab()` | 로그 편집 탭 — `st.data_editor`로 수정/삭제, 저장 버튼. |

### 2.4 `views/` — 페이지 조립

`ui/`와 `services/`를 가져와 페이지 하나를 완성합니다. 여기엔 세부 UI 코드가
거의 없고, "어떤 컴포넌트를 어떤 순서로 배치할지"만 있습니다.

| 파일 | 설명 |
|---|---|
| `dashboard.py` | 관제 대시보드 — 카메라 영역(좌) + 경보 패널(우) 배치, 팝업 트리거 확인, 영상 재생 루프 실행. |
| `logs.py` | 탐지 데이터 로그 — 로그를 최신순 정렬 후 조회 탭 / 편집 탭 배치. |

> **왜 폴더명이 `pages`가 아니라 `views`인가?**
> Streamlit은 `app.py`와 같은 위치에 `pages/`라는 폴더가 있으면 그 안의 `.py`
> 파일들을 자동으로 별도 페이지로 등록하고 사이드바 네비게이션을 만듭니다.
> 이 폴더의 파일들은 독립 실행용 페이지가 아니라 `render()` 함수만 있는
> 모듈이라 그 자동 동작과 충돌합니다. 그래서 `views`로 이름을 바꿨습니다.

### 2.5 `utils/`

| 파일 | 설명 |
|---|---|
| `formatters.py` | `fmt_dt()`, `fmt_src()`, `fmt_bbox()` — DB 레코드와 메모리 레코드의 필드 구조 차이(`created_at` vs `date`+`time` 등)를 화면 표시용으로 통일하는 순수 함수. Streamlit 호출이 없습니다. |

---

## 3. 실행 방법

### 3.1 사전 준비

```bash
# 가상환경 생성 및 활성화 (최초 1회)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 필요 패키지 설치
pip install fastapi uvicorn ultralytics pillow python-multipart \
            streamlit pandas sqlalchemy pymysql boto3 opencv-python requests
```

`.streamlit/secrets.toml`에 RDS 접속 정보와 S3 자격증명을 설정해야 DB/S3
기능이 활성화됩니다 (미설정 시에도 메모리 전용 모드로 앱은 정상 구동됩니다).

```toml
# .streamlit/secrets.toml 예시
[connections.gop_db]
url = "mysql+pymysql://<user>:<password>@<host>:3306/<db_name>"

[s3]
region = "ap-northeast-2"
bucket = "your-bucket-name"
access_key_id = "..."
secret_access_key = "..."
```

### 3.2 백엔드(FastAPI) 실행 — 터미널 1

```bash
# MODEL_PATH 환경변수로 학습된 가중치(.pt) 경로 지정
export MODEL_PATH=weights/best.pt        # Windows(PowerShell): $env:MODEL_PATH="weights/best.pt"

uvicorn backend:app --reload --port 8000
```

- `http://127.0.0.1:8000/health` 로 접속해 `{"status": "ok", "model_loaded": true}`가
  뜨면 정상 구동된 것입니다.
- `CONF_THRESHOLD`, `NMS_THRESHOLD` 환경변수로 신뢰도/NMS 임계값을 코드 수정 없이 조정할 수 있습니다.

### 3.3 프론트엔드(Streamlit) 실행 — 터미널 2

```bash
streamlit run app.py
```

- 기본적으로 `http://localhost:8501`에서 열립니다.
- 백엔드 주소가 기본값(`127.0.0.1:8000`)과 다르면 `API_BASE_URL` 환경변수로 지정합니다.
  ```bash
  export API_BASE_URL=http://<backend-ip>:8000
  streamlit run app.py
  ```

### 3.4 실행 순서 요약

```
1) (선택) .streamlit/secrets.toml 설정 — RDS/S3
2) 터미널 1:  uvicorn backend:app --reload --port 8000
3) 터미널 2:  streamlit run app.py
4) 브라우저에서 http://localhost:8501 접속
```

사이드바의 **"데모 모드"** 체크박스를 켜두면 백엔드 없이도 무작위 탐지
데이터로 화면 동작을 확인할 수 있습니다 (터미널 1 생략 가능).

---

## 4. 자주 헷갈릴 수 있는 부분

- **`services/`와 `ui/`를 나눈 이유**: `ui/`는 오직 화면을 그리는 코드만, `services/`는
  DB/S3/추론 호출 같은 실제 동작만 담당하도록 나눴습니다. 화면 디자인만 바꾸고
  싶다면 `ui/`만, 탐지 로직만 바꾸고 싶다면 `services/`만 보면 됩니다.
- **데모 모드 제거 시 수정할 곳**: 코드 안에 `# ← 데모 모드 전용` 주석이 달린
  부분만 지우면 됩니다 (`services/detection.py`의 `simulate_detections()` 함수와
  `run_detection()` 안의 분기, `state.py`/`ui/layout.py`의 관련 두 줄).
- **`conf_thresh`/`nms_thresh`의 단일 출처**: 이 값은 오직 `backend.py`에서만
  정의되고, 매 추론마다 API 응답(`conf_thresh_used`)을 통해서만 전달됩니다.
  프론트엔드나 DB 코드에서 이 값을 직접 하드코딩하지 않습니다.
