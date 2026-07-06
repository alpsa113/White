# GOP 통합 감시 시스템 — 프로젝트 구조 가이드

## 1. 한눈에 보는 전체 구조

```
project/
├── app.py                    # 메인 엔트리포인트 (Streamlit 실행 시작점)
├── config.py                 # 전역 설정값 (카메라 이름 목록/생성 함수, 임계값, 색상 등)
├── state.py                  # session_state 초기화
├── requirements.txt          # 프로젝트 의존성 목록 (pip install -r requirements.txt)
├── backend.py                # FastAPI 추론 서버 (별도 프로세스로 실행)
├── db_rds.py                 # AWS RDS(MySQL) 연동
├── s3_storage.py              # AWS S3 이미지 저장 연동
│
├── services/                  # 화면 없는 "로직" — DB/S3/추론/재생 제어
│   ├── detection.py            # 백엔드 API 호출, 박스 그리기, 데모 데이터 생성
│   ├── tracking.py               # 프레임 1장의 사람/동물 트래킹 → 로그/알람 연결
│   ├── playback.py                # 영상 재생 제어 (프레임 진행, 반복 재생, 리소스 정리)
│   ├── alerts.py                    # 탐지 로그 생성/갱신, DB 동기화
│   ├── camera_registry.py            # 대시보드 카메라 목록의 순서/개수/정리 관리
│   └── log_management.py              # 로그 편집/삭제 저장 처리
│
├── ui/                         # Streamlit 화면(위젯) 렌더링 전담
│   ├── layout.py                 # 상단 네비게이션(브랜드명/페이지 전환/상태뱃지/실시간 시계)
│   ├── alert_panel.py              # 우측 사람 탐지 경보 패널
│   ├── log_tabs.py                   # 로그 조회 탭 + 편집 탭
│   ├── dialogs.py                      # 사람 탐지 팝업 + 팝업 트리거 처리
│   └── camera/                          # 카메라 카드 관련 UI 전용 하위 패키지
│       ├── card.py                        # 카드 레이아웃 + 업로드/재생 상태 전환
│       ├── zoom.py                          # 마우스 휠/드래그 확대·이동 (순수 JS, 독립)
│       ├── grid.py                            # 그리드/집중보기 배치
│       ├── reorder.py                           # 드래그 순서 변경 위젯
│       └── toolbar.py                             # 대시보드 헤더 위젯 조립
│
├── views/                       # 페이지 단위 조립 (ui + services 호출만)
│   ├── dashboard.py               # 페이지1: 관제 대시보드
│   ├── logs.py                     # 페이지2: 탐지 데이터 로그
│   └── settings.py                  # 페이지3: 설정
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

`services/`는 `ui/`나 `views/`를 절대 import하지 않습니다. `ui/camera/` 안에서도
`card.py`가 `zoom.py`·`grid.py`·`reorder.py`를 가져다 쓰는 방향으로만 흐르고,
반대 방향 import는 없습니다.

이 시스템은 **사이드바를 사용하지 않습니다.** 관제 화면 특성상 모든 조작을
상단 네비게이션과 세 페이지(대시보드/로그/설정) 안에서 끝낼 수 있도록
설계되어 있습니다.

---

## 2. 파일별 상세 설명

### 2.1 최상위

| 파일 | 역할 |
|---|---|
| `app.py` | `streamlit run`으로 실행되는 유일한 진입점. 페이지 설정 → `state.init_session_state()` → `ui.layout.render_topnav()` → 현재 선택된 페이지의 `render()` 호출. |
| `config.py` | 카메라 이름 목록(`CAMERA_NAMES`)과 `build_camera_list()`, 클래스별 색상(`COLORS`), 백엔드 API 주소, 트래킹 튜닝 값(`DETECT_EVERY_SECONDS` 등) 등 전역 상수. |
| `state.py` | 앱이 (재)실행될 때마다 `st.session_state`에 필요한 키들의 기본값을 채워 넣습니다. |
| `requirements.txt` | `pip install -r requirements.txt`로 한 번에 설치할 패키지 목록. |
| `backend.py` | YOLO 모델을 메모리에 올려두고 `/detect`로 탐지 결과를 반환하는 FastAPI 서버. Streamlit과는 별개 프로세스로 실행됩니다. |
| `db_rds.py` | AWS RDS(MySQL) 연동. 테이블 생성, 로그 조회/추가/수정/삭제, 클래스명 ↔ class_id 매핑(`CLASS_ID_MAP`). |
| `s3_storage.py` | AWS S3 연동. 탐지 스냅샷 업로드/다운로드/삭제, 조회용 임시 URL 발급. |

### 2.2 `services/` — 화면 없는 로직

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `detection.py` | `run_detection()` | 백엔드에 이미지를 보내고 탐지 결과를 받습니다. 데모 모드일 땐 `simulate_detections()`가 대신합니다. |
| | `draw_boxes()`, `is_person()` | 박스 그리기, 사람 클래스 판별. |
| `tracking.py` | `process_frame()` | 프레임 1장의 탐지 결과를 사람/동물 트래킹 상태와 연결해, 신규 로그 생성 또는 기존 로그 갱신을 결정합니다. **영상 재생 자체(파일 읽기 등)는 다루지 않습니다** — 그건 `playback.py`의 몫입니다. |
| `playback.py` | `advance_one_frame()` | 재생 중인 영상에서 실제 경과 시간만큼 프레임을 진행시킵니다. 영상이 끝나면 처음으로 되돌아가 반복 재생합니다(24시간 CCTV 시뮬레이션). 탐지가 필요한 시점에만 `tracking.process_frame()`을 호출합니다. |
| | `reset_cam_state()` | 카메라 채널의 업로드/재생 리소스를 완전 정리. |
| `alerts.py` | `create_detection_alert()`, `update_detection_alert()` | 로그 생성/갱신, DB 동기화, 경보 패널/팝업 트리거. |
| `camera_registry.py` | `get_active_cameras()` | `grid_count`에 맞춰 카메라 목록을 만들고, 저장된 순서를 적용하고, 사라진 카메라의 리소스를 정리합니다. |
| | `compute_grid_columns()`, `get_valid_area_options()` | 그리드 열 수 계산, 구역 선택 드롭다운 옵션 준비. |
| `log_management.py` | `save_log_edits()` | 로그 편집 탭 저장 처리. |

### 2.3 `ui/` — Streamlit 화면 렌더링

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `layout.py` | `render_topnav()` | 브랜드명, 페이지 전환 버튼 3개, RDS·S3 상태뱃지, 실시간 시계. |
| `alert_panel.py` | `render_alert_panel()` | 우측 사람 탐지 경보 패널. |
| `log_tabs.py` | `render_view_tab()`, `render_manage_tab()` | 로그 조회/편집 탭. |
| `dialogs.py` | `show_person_dialog()`, `handle_pending_popup()` | 사람 탐지 팝업과, 대기열(`popup_queue`)을 확인해 팝업을 띄우는 트리거 로직. |

#### `ui/camera/` — 카메라 카드 전용 하위 패키지

카드 UI가 무거워지는 걸 막기 위해 관심사별로 나눠뒀습니다.

| 파일 | 역할 |
|---|---|
| `card.py` | 카드 레이아웃(제목/⚙️ 팝오버/업로드) + 상태 전환(대기 → 재생 중 → 정지). `render_camera_card()`가 유일한 공개 진입점입니다. |
| `zoom.py` | 집중 보기에서만 켜지는 마우스 휠 확대·드래그 이동. 순수 HTML/JS로, `services/playback.py`가 프레임을 아무리 자주 갱신해도 이 상태는 독립적으로 유지됩니다. |
| `grid.py` | `render_camera_grid()`, `render_camera_focus()` — 카드를 몇 개, 어떤 배치로 보여줄지만 결정. |
| `reorder.py` | 카메라 이름표 드래그 정렬 위젯. |
| `toolbar.py` | 대시보드 헤더(제목+구역선택+카메라개수+순서변경)를 조립. `render_dashboard_header()`가 유일한 공개 진입점입니다. |

### 2.4 `views/` — 페이지 조립

| 파일 | 설명 |
|---|---|
| `dashboard.py` | 관제 대시보드. **로직을 거의 담지 않습니다** — 카메라 목록은 `services.camera_registry`, 헤더는 `ui.camera.toolbar`, 카드 배치는 `ui.camera.grid`, 팝업은 `ui.dialogs`에서 가져와 배치만 조립합니다. `render()`가 영상 재생 등으로 매우 자주 재실행되므로, 무거운 로직을 여기 두지 않는 것이 원칙입니다. |
| `logs.py` | 탐지 데이터 로그 — 최신순 정렬 후 조회/편집 탭 배치. |
| `settings.py` | 설정 — 데모 모드, 시계 표시 등. |

> **왜 폴더명이 `pages`가 아니라 `views`인가?**
> Streamlit은 `app.py`와 같은 위치에 `pages/` 폴더가 있으면 자동으로 사이드바
> 네비게이션을 만듭니다. 이 폴더의 파일들은 `render()` 함수만 있는 모듈이라
> 그 자동 동작과 충돌하므로, `views`로 이름을 바꿨습니다.

### 2.5 `utils/`

| 파일 | 설명 |
|---|---|
| `formatters.py` | `fmt_dt()`, `fmt_src()`, `fmt_bbox()` — DB/메모리 레코드의 필드 차이를 화면 표시용으로 통일하는 순수 함수. |

---

## 3. 실행 방법

### 3.1 사전 준비

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> GUI 없는 서버(EC2 등)에 배포할 경우 `requirements.txt`의 `opencv-python`을
> `opencv-python-headless`로 바꿔서 설치하는 것을 권장합니다.

`.streamlit/secrets.toml`에 RDS/S3 자격증명을 설정해야 DB/S3 기능이
활성화됩니다 (미설정 시에도 메모리 전용 모드로 앱은 정상 구동됩니다). 이
파일은 절대 깃허브에 커밋하지 마세요 — `.gitignore`에 등록해두는 것을
권장합니다.

```toml
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
export MODEL_PATH=weights/best.pt        # Windows(PowerShell): $env:MODEL_PATH="weights/best.pt"
uvicorn backend:app --reload --port 8000
```

`http://127.0.0.1:8000/health`에서 `{"status": "ok", "model_loaded": true}`가
뜨면 정상입니다. `CONF_THRESHOLD`, `NMS_THRESHOLD` 환경변수로 임계값 조정
가능합니다.

### 3.3 프론트엔드(Streamlit) 실행 — 터미널 2

```bash
streamlit run app.py
```

백엔드 주소가 기본값(`127.0.0.1:8000`)과 다르면 `API_BASE_URL` 환경변수로
지정합니다.

### 3.4 실행 순서 요약

```
1) pip install -r requirements.txt (최초 1회)
2) (선택) .streamlit/secrets.toml 설정 — RDS/S3
3) 터미널 1:  uvicorn backend:app --reload --port 8000
4) 터미널 2:  streamlit run app.py
5) 브라우저에서 http://localhost:8501 접속
```

상단 네비게이션의 **"⚙️ 설정"** 페이지에서 **"데모 모드"**를 켜두면 백엔드
없이도 무작위 탐지 데이터로 화면 동작을 확인할 수 있습니다.

---

## 4. 자주 헷갈릴 수 있는 부분

- **`services/tracking.py`와 `services/playback.py`를 나눈 이유**: `tracking.py`는
  "탐지 결과 1개를 로그/알람으로 어떻게 연결할지"만, `playback.py`는 "영상 파일에서
  언제 어느 프레임을 읽을지"만 담당합니다. 재생 속도나 반복 재생 로직을 고치고
  싶으면 `playback.py`만, 트래킹/중복 알람 방지 로직을 고치고 싶으면 `tracking.py`만
  보면 됩니다.
- **`ui/camera/` 하위 패키지 의존 방향**: `card.py` → `zoom.py`, `toolbar.py` →
  `reorder.py`처럼 항상 한 방향으로만 흐릅니다. `zoom.py`나 `reorder.py`가
  `card.py`를 import하는 일은 없습니다.
- **데모 모드 제거 시 수정할 곳**: `services/detection.py`의 `simulate_detections()`와
  `run_detection()` 안의 분기, `state.py`의 관련 두 줄, `views/settings.py`의
  데모 모드 UI 블록.
- **`conf_thresh`/`nms_thresh`의 단일 출처**: `backend.py`에서만 정의되고, 매 추론마다
  API 응답(`conf_thresh_used`)을 통해서만 전달됩니다.
- **위젯 key와 상태 key를 분리하는 이유**: `views/settings.py`, `ui/camera/toolbar.py` 등의
  체크박스/토글/슬라이더는 특정 조건에서만 그려집니다. Streamlit은 그려지지 않는
  위젯의 key를 session_state에서 삭제하므로, 다른 파일에서도 참조하는 실제 상태
  key(`simulate`, `grid_count` 등)는 위젯 전용 key(`_xxx_widget`)와 분리하고
  `on_change` 콜백으로 값을 복사합니다.
- **탐지 클래스 목록**: 사람 / 멧돼지 / 고라니 / 소형동물 4종. 클래스를 추가/변경할 때는
  `config.py`(색상), `db_rds.py`(`CLASS_ID_MAP` 및 기본 `class_map`),
  `services/detection.py`(데모 모드 동물 풀), `ui/log_tabs.py`(편집 탭 드롭다운),
  `DB_create.sql`(초기 데이터) — 5곳을 함께 맞춰야 합니다.
- **카메라 개수**: 고정 리스트가 아니라 대시보드의 "카메라 개수" 스텝퍼로 사용자가
  직접 조절합니다(`config.MAX_CAMERAS`까지). 관련 상태 관리는 전부
  `services/camera_registry.py`에 있습니다.
- **영상 반복 재생**: 업로드한 영상이 끝에 도달하면 `services/playback.py`가
  자동으로 처음으로 되돌려 계속 재생합니다(24시간 CCTV 시뮬레이션). 현재
  일시정지/재개 버튼은 테스트 중 로그가 계속 쌓이는 것을 막기 위한 임시
  기능으로, `ui/camera/card.py`에 `TODO(임시/테스트용)` 주석으로 표시되어
  있습니다 — 실제 배포 전 제거를 검토하세요.
