# GOP 통합 감시 시스템 — 프로젝트 구조 가이드

## 1. 한눈에 보는 전체 구조

```
project/
├── app.py                    # 메인 엔트리포인트 (Streamlit 실행 시작점, 로그인 게이트 + 페이지 라우팅)
├── config.py                 # 전역 설정값 (계정, 사용자 유형 매핑, 클래스 색상, 임계값, 클립 길이 등)
├── state.py                  # session_state 초기화
├── requirements.txt          # 프로젝트 의존성 목록 (pip install -r requirements.txt)
├── backend.py                # FastAPI 추론 서버 (별도 프로세스로 실행)
├── db_rds.py                 # AWS RDS(MySQL) 연동
├── s3_storage.py              # AWS S3 이미지/클립 저장 연동
│
├── services/                  # 화면 없는 "로직" — DB/S3/추론/재생/클립 녹화/초소 관리
│   ├── detection.py            # 백엔드 API 호출, 박스 그리기, 데모 데이터 생성
│   ├── tracking.py               # 프레임 1장의 사람/동물 트래킹 → 로그/알람 연결
│   ├── playback.py                # 다중 카메라 재생 루프 (프레임 진행, 반복 재생)
│   ├── clip_recorder.py            # 탐지 전후 짧은 클립(mp4) 녹화·인코딩·S3 업로드
│   ├── alerts.py                    # 탐지 로그 생성/갱신, DB 동기화
│   ├── camera_registry.py            # 초소 마커 → 카메라 목록 변환, 정리
│   ├── log_management.py              # 로그 편집/삭제 저장 처리
│   ├── audio_alert.py                  # 사람 탐지 시 알림음 생성
│   └── outposts.py                      # 초소(지도 마커) CRUD — 카메라 개수/이름의 단일 출처
│
├── ui/                         # Streamlit 화면(위젯) 렌더링 전담
│   ├── styles.py                 # 여러 화면이 공통으로 쓰는 CSS/인라인 스타일 문자열
│   ├── layout.py                  # 사이드바(브랜드명/페이지 전환/상태뱃지/시계/최근 탐지/로그아웃)
│   ├── log_tabs.py                  # 로그 조회 탭 + 편집 탭
│   ├── camera/                        # 카메라 카드 관련 UI 전용 하위 패키지
│   │   ├── card.py                      # 카드 레이아웃 + 업로드/재생 상태 전환
│   │   ├── zoom.py                        # 마우스 휠/드래그 확대·이동 (순수 JS, 독립)
│   │   ├── grid.py                          # 그리드 배치
│   │   ├── spotlight.py                       # Zoom 발표자 화면 스타일 집중 보기
│   │   └── toolbar.py                           # 대시보드 헤더(구역 선택) 위젯 조립
│   └── outposts/                      # 초소(지도 마커) 관련 UI 전용 하위 패키지
│       ├── editor.py                    # 설정 페이지: 지도 업로드 + 클릭 마킹 + 초소정보 편집
│       └── viewer.py                     # 대시보드 "관제 지도" 탭: 지도 + 점멸 마커 + CCTV 요약
│
├── views/                       # 페이지 단위 조립 (ui + services 호출만)
│   ├── login.py                    # 페이지0: 로그인 (ID + 사용자 유형 + PW)
│   ├── dashboard.py                 # 페이지1: 관제 대시보드 ("카메라 화면"/"관제 지도" 탭)
│   ├── logs.py                       # 페이지2: 탐지 데이터 로그 (role에 따라 편집 탭 노출 여부 결정)
│   └── settings.py                    # 페이지3: 설정 (admin 전용, 초소 마킹 포함)
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

`services/`는 `ui/`나 `views/`를 절대 import하지 않습니다. `services/playback.py`가
`services/clip_recorder.py`를 가져다 쓰는 방향으로만 흐르고, 반대 방향 import는
없습니다. `ui/camera/` 안에서도 `card.py`가 `zoom.py`를 가져다 쓰는 방향으로만
흐르고, `ui/outposts/`의 `editor.py`·`viewer.py`는 서로 직접 참조하지 않고
`services/outposts.py`를 공용 상태 출처로만 공유합니다.

이 시스템은 **페이지 전환/상태뱃지/시계/로그아웃을 모두 사이드바에서 처리합니다.**
CCTV 화면이 메인 영역 최상단에 바로 붙을 수 있도록 한 설계이며, 관제 화면
특성상 페이지는 로그인 이후 항상 세 개(실시간 감시/관리자 로그/설정)로
고정되어 있습니다.

---

## 2. 로그인과 권한 모델

로그인 화면(`views/login.py`)은 ID, **사용자 유형**(관리자/사용자) 드롭다운,
PW 세 가지를 입력받습니다. ID/PW가 맞아도 선택한 사용자 유형이 계정의 실제
role과 다르면 로그인이 거부됩니다 (`config.USER_TYPE_OPTIONS`).

| 페이지 | 관리자(admin) | 사용자(user) |
|---|---|---|
| 실시간 감시 (카메라 화면 / 관제 지도 탭) | ✅ | ✅ |
| 관리자 로그 — 로그 조회 및 이미지 | ✅ | ✅ |
| 관리자 로그 — 로그 편집 및 삭제 | ✅ | ❌ (탭 자체가 보이지 않음) |
| 설정 (초소 마킹 포함) | ✅ | ❌ (버튼 자체가 보이지 않고, `app.py`가 이중으로 차단) |

로그인 직후 랜딩 페이지도 role에 따라 다릅니다(`config.DEFAULT_LANDING_PAGE`):
관리자는 카메라를 만들기 위해 먼저 **설정** 페이지로, 사용자는 곧바로
**실시간 감시**로 진입합니다.

---

## 3. 초소(카메라) 설정 — services/outposts.py, ui/outposts/

과거에는 대시보드에서 "카메라 개수" +/- 스텝퍼로 카메라 수를 정했지만,
이제는 **설정 페이지에서 지도 위에 클릭으로 마킹한 초소 개수**가 곧 카메라
개수입니다 (스텝퍼는 제거되었습니다).

1. 관리자가 설정 페이지에서 지도 이미지를 업로드합니다 (`ui/outposts/editor.py`).
2. `streamlit-image-coordinates`로 지도를 클릭하면 그 위치에 마커(초소)가
   추가됩니다. 좌표는 원본 이미지 기준 0~1 비율(x_ratio/y_ratio)로 저장되어
   (`services/outposts.py`), 화면 크기가 달라져도 항상 같은 상대 위치에
   마커가 그려집니다.
3. 마커 옆 표에서 "초소 정보"·"영상 소스"를 직접 입력하고 저장할 수 있고,
   개별/전체 삭제도 가능합니다.
4. `services/camera_registry.get_active_cameras()`가 이 초소 목록을
   `{"id", "name"}` 카메라 딕셔너리로 변환해 나머지 시스템(재생 루프, 트래킹,
   그리드/스포트라이트)에 기존과 동일하게 공급합니다. 아직 초소를 하나도
   마킹하지 않은 초기 상태에서는 기본 카메라 1개로 폴백합니다.

카메라 클래스를 추가/변경할 때 함께 맞춰야 할 5곳(§4의 "탐지 클래스 목록"
항목)은 초소 설정과 무관하며 그대로 적용됩니다.

현재 초소/지도 이미지는 **세션(session_state) 메모리에만 보관**됩니다 — 기존
카메라 개수 설정도 세션 한정이었던 것과 동일한 수준이며, 영구 저장이
필요해지면 `db_rds.py`에 전용 테이블을 추가하고 `services/outposts.py`의
CRUD 함수만 DB 연동으로 바꿔주면 됩니다.

---

## 4. 실시간 감시 페이지의 두 탭

`views/dashboard.py`는 "카메라 화면"과 "관제 지도" 두 탭으로 구성됩니다
(별도 페이지가 아니라 탭인 이유: §5 참고).

- **카메라 화면** 탭 — 기존과 동일한 그리드/스포트라이트. 업로드, 확대,
  일시정지 등 실제 조작은 모두 이 탭에서만 이루어집니다.
- **관제 지도** 탭 — 오른쪽 지도 위의 마커를 클릭해 왼쪽에서 볼 카메라를
  고릅니다 (`ui/outposts/viewer.py`). **마커는 다중 선택이 가능합니다** —
  1개를 선택하면 카메라 1개짜리 화면, 여러 개를 선택하면 '카메라 화면' 탭의
  그리드와 동일한 배치 규칙(`services.camera_registry.compute_grid_columns`)
  으로 여러 화면이 함께 표시됩니다. 아무것도 선택하지 않은 초기 상태에는
  전체 카메라를 보여줍니다. 선택된 마커에는 초록색 테두리가 표시됩니다.

  이 선택 상태(`session_state._map_selected_cam_ids`)는 **오직 "관제 지도"
  탭 안에서만** 의미가 있습니다 — '카메라 화면' 탭의 구역 선택이나 그리드/
  스포트라이트 모드에는 전혀 영향을 주지 않습니다(두 탭의 상태는 완전히
  독립적입니다). Streamlit은 서버 코드로 현재 활성 탭을 강제 전환하는 기능도
  제공하지 않으므로, 애초에 다른 탭으로 자동 이동시키는 것도 불가능합니다.

  사람이 탐지된 카메라의 마커는 점멸하고, 그 옆에는 별도의 작은 "⏹" 정지
  아이콘이 함께 붙습니다 — 마커 본체를 클릭하면 선택만 토글되고 점멸은
  유지되며, 점멸을 멈추려면 반드시 이 "⏹" 아이콘을 클릭해야 합니다. 정지
  상태는 추적이 끊기면 자동 해제되어 다음 탐지부터 다시 점멸합니다.

왼쪽 CCTV 요약이 `ui/camera/card.py`의 인터랙티브 카드를 재사용하지 않는
이유: Streamlit은 `st.tabs()`의 모든 탭 내용을 매 스크립트 실행마다 함께
그리므로(화면에 보이지 않는 탭도 코드가 실행됨), 같은 위젯 key를 가진 카드를
두 탭에 동시에 두면 key 충돌로 오류가 납니다. 그래서 "관제 지도" 탭은
`st.image()` 기반의 순수 표시 전용 요약만 사용합니다.

---

## 5. 파일별 상세 설명

### 5.1 최상위

| 파일 | 역할 |
|---|---|
| `app.py` | `streamlit run`으로 실행되는 유일한 진입점. 페이지 설정 → `state.init_session_state()` → 로그인 게이트(`views.login`) → `ui.layout.render_sidebar()` → role별 접근 제한(이중 방어) → 카메라 목록 계산 → 현재 선택된 페이지의 `render()` 호출 → `services.playback.run_playback_loop()`. 재생 루프는 **어떤 페이지를 보고 있든** 항상 마지막에 호출되어, 로그/설정 페이지에 있어도 탐지가 끊기지 않습니다. |
| `config.py` | `build_camera_list()`(초소 미설정 시 초기 폴백 카메라 생성), 클래스별 색상(`COLORS`), 계정 정보(`USERS`), 로그인 사용자 유형 매핑(`USER_TYPE_OPTIONS`), role별 랜딩 페이지(`DEFAULT_LANDING_PAGE`), 백엔드 API 주소(`API_BASE_URL`), 트래킹 튜닝 값 등 전역 상수. |
| `state.py` | 앱이 (재)실행될 때마다 `st.session_state`에 필요한 키들의 기본값을 채워 넣습니다 (초소/지도 이미지 상태 포함). |
| `requirements.txt` | `pip install -r requirements.txt`로 한 번에 설치할 패키지 목록. |
| `backend.py` | YOLO 모델을 메모리에 올려두는 FastAPI 서버. `/detect`(단일 프레임 추론), `/health`(상태 체크), `/stream`(화면 표시 전용 MJPEG 스트리밍) 세 엔드포인트를 제공합니다. Streamlit과는 별개 프로세스로 실행됩니다. |
| `db_rds.py` | AWS RDS(MySQL) 연동. 테이블 생성, 로그 조회/추가/수정/삭제, 클래스명 ↔ class_id 매핑(`CLASS_ID_MAP`), 스냅샷→클립 교체(`update_snapshot_uri`). |
| `s3_storage.py` | AWS S3 연동. 탐지 스냅샷/클립 업로드·다운로드·삭제, 조회용 임시 URL 발급. |

### 5.2 `services/` — 화면 없는 로직

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `detection.py` | `run_detection()` | 백엔드에 이미지를 보내고 탐지 결과를 받습니다. 데모 모드일 땐 `simulate_detections()`가 대신합니다. |
| | `draw_boxes()`, `is_person()` | 박스 그리기, 사람 클래스 판별. |
| `tracking.py` | `process_frame()` | 프레임 1장의 탐지 결과를 사람/동물 트래킹 상태와 연결해, 신규 로그 생성 또는 기존 로그 갱신을 결정합니다. `person_tracks_{cid}`에 담기는 이 상태는 `ui/outposts/viewer.py`가 지도 마커 점멸 여부를 판단할 때도 그대로 재사용합니다. |
| `playback.py` | `run_playback_loop()` | 여러 카메라의 영상을 하나의 반복문 안에서 함께 재생합니다. |
| | `reset_cam_state()` | 카메라 채널의 업로드/재생/클립 관련 리소스를 완전 정리. 초소 삭제 시(`services/outposts.py`)도 동일하게 호출됩니다. |
| `clip_recorder.py` | `push_frame_buffer()` / `start_pending_clips()` / `append_pending_clips()` | 탐지 전후 짧은 클립(mp4) 버퍼링·인코딩·S3 업로드. |
| `alerts.py` | `create_detection_alert()`, `update_detection_alert()` | 로그 생성/갱신, DB 동기화, 스냅샷 S3 업로드. |
| `camera_registry.py` | `get_active_cameras()` | `services/outposts.py`의 초소 목록을 카메라 목록으로 변환하고, 삭제된 카메라의 리소스를 정리합니다. |
| | `compute_grid_columns()`, `get_valid_area_options()` | 그리드 열 수 계산, 구역 선택 드롭다운 옵션 준비. |
| `log_management.py` | `save_log_edits()` | 로그 편집 탭 저장 처리 — 원본과 비교해 실제로 변경된 행만 반영합니다. |
| `audio_alert.py` | `play_alert_sound()` | 사람 탐지 시 재생할 비프음을 즉석에서 생성. |
| `outposts.py` | `add_marker()` / `update_marker()` / `remove_markers()` / `reset_all()` | 초소(지도 마커) CRUD — 카메라 개수/이름의 단일 출처. |
| | `to_camera_list()` | 초소 목록을 `{"id","name"}` 카메라 딕셔너리 리스트로 변환. |

### 5.3 `ui/` — Streamlit 화면 렌더링

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `styles.py` | (상수 모음) | 버튼 줄바꿈 방지 CSS, 브랜드명/상태뱃지/시계 인라인 스타일 등 여러 화면이 공유하는 순수 CSS 문자열. |
| `layout.py` | `render_sidebar()` | 브랜드명, 페이지 전환 버튼(role별 노출 범위 상이), RDS·S3 상태뱃지, 실시간 시계 + 최근 사람 탐지 배너, 계정 정보/로그아웃을 사이드바에 조립. |
| `log_tabs.py` | `render_view_tab()`, `render_manage_tab()` | 로그 조회(표+이미지/클립 뷰어)와 편집(data_editor) 탭. 편집 탭 호출 여부는 `views/logs.py`가 role을 보고 결정합니다. |

#### `ui/camera/` — 카메라 카드 전용 하위 패키지

| 파일 | 역할 |
|---|---|
| `card.py` | 카드 레이아웃(제목/⚙️ 팝오버/업로드) + 상태 전환(대기 → 재생 중 → 정지). `render_camera_card()`가 유일한 공개 진입점입니다. |
| `zoom.py` | 집중 보기에서만 켜지는 마우스 휠 확대·드래그 이동. |
| `grid.py` | `render_camera_grid()` — 카드를 몇 개, 몇 열로 배치할지만 결정. |
| `spotlight.py` | `render_camera_spotlight()` — 특정 카메라를 좌측에 크게, 나머지를 우측 스크롤 영역에 썸네일로 배치. |
| `toolbar.py` | 대시보드 사이드바 컨트롤(구역 선택)을 조립. `render_dashboard_header()`가 유일한 공개 진입점입니다. 과거 있었던 "카메라 개수" 스텝퍼는 초소 마킹으로 대체되어 제거되었습니다. |

#### `ui/outposts/` — 초소(지도 마커) 전용 하위 패키지

| 파일 | 역할 |
|---|---|
| `editor.py` | 설정 페이지: 지도 이미지 업로드 + `streamlit-image-coordinates` 클릭 마킹 + 초소정보/영상소스 표 편집(저장/전체초기화/개별삭제). `render_outpost_editor()`가 유일한 공개 진입점입니다. |
| `viewer.py` | 대시보드 "관제 지도" 탭: 왼쪽 CCTV 요약 + 오른쪽 지도·점멸 마커. `render_outpost_map()`이 유일한 공개 진입점입니다. |

### 5.4 `views/` — 페이지 조립

| 파일 | 설명 |
|---|---|
| `login.py` | 로그인 화면. ID + 사용자 유형(관리자/사용자) + PW를 모두 확인해야 인증에 성공합니다. |
| `dashboard.py` | 관제 대시보드. "카메라 화면"/"관제 지도" 탭을 조립합니다(§4 참고). **로직을 거의 담지 않습니다.** |
| `logs.py` | 탐지 데이터 로그 — 최신순 정렬 후 조회 탭(공통)과 편집 탭(admin 전용)을 배치합니다. |
| `settings.py` | 설정 — 초소 위치 설정(`ui.outposts.editor`)이 최상단에 위치하고, 그 아래 데모 모드/RDS·S3 상태가 이어집니다. admin 전용 페이지입니다. |

> **왜 폴더명이 `pages`가 아니라 `views`인가?**
> Streamlit은 `app.py`와 같은 위치에 `pages/` 폴더가 있으면 자동으로 사이드바
> 네비게이션을 만듭니다. 이 폴더의 파일들은 `render()` 함수만 있는 모듈이라
> 그 자동 동작과 충돌하므로, `views`로 이름을 바꿨습니다.

### 5.5 `utils/`

| 파일 | 설명 |
|---|---|
| `formatters.py` | `fmt_dt()` — DB/메모리 레코드의 필드 차이(created_at vs date+time)를 화면 표시용 문자열로 통일하는 순수 함수. |

---

## 6. 실행 방법

### 6.1 사전 준비

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> GUI 없는 서버(EC2 등)에 배포할 경우 `requirements.txt`의 `opencv-python`을
> `opencv-python-headless`로 바꿔서 설치하는 것을 권장합니다.
>
> `imageio-ffmpeg`는 플랫폼별 ffmpeg 실행파일을 패키지 안에 내장하고 있어
> 별도로 ffmpeg를 설치할 필요가 없습니다.
>
> `streamlit-image-coordinates`는 설정 페이지의 지도 클릭 마킹 기능에
> 필요합니다.

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

### 6.2 백엔드(FastAPI) 실행 — 터미널 1

```bash
export MODEL_PATH=weights/best.pt        # Windows(PowerShell): $env:MODEL_PATH="weights/best.pt"
uvicorn backend:app --reload --port 8000
```

`http://127.0.0.1:8000/health`에서 `{"status": "ok", "model_loaded": true}`가
뜨면 정상입니다. `CONF_THRESHOLD`, `NMS_THRESHOLD` 환경변수로 임계값 조정
가능합니다.

### 6.3 프론트엔드(Streamlit) 실행 — 터미널 2

```bash
streamlit run app.py
```

백엔드 주소가 기본값(`127.0.0.1:8000`)과 다르면 `API_BASE_URL` 환경변수로
지정합니다. **브라우저가 이 주소로 직접 접속**하므로(화면 표시용 `/stream`
때문), 백엔드와 브라우저가 서로 다른 컴퓨터에 있는 환경에서는 브라우저
기준으로 실제 도달 가능한 주소를 지정해야 합니다.

### 6.4 실행 순서 요약

```
1) pip install -r requirements.txt (최초 1회)
2) (선택) .streamlit/secrets.toml 설정 — RDS/S3
3) 터미널 1:  uvicorn backend:app --reload --port 8000
4) 터미널 2:  streamlit run app.py
5) 브라우저에서 http://localhost:8501 접속 → 로그인(계정: config.USERS 참고)
6) (admin) 설정 페이지에서 지도 업로드 + 초소 마킹 → 카메라 자동 생성
```

데모 계정은 `config.USERS`에 있습니다 (`admin`/`admin1234`, `user`/`user1234`).
로그인 화면에서 ID/PW와 함께 "사용자 유형"도 계정에 맞게 선택해야 합니다.

상단 네비게이션의 **"설정"** 페이지(admin 전용)에서 **"데모 모드"**를 켜두면
백엔드 없이도 무작위 탐지 데이터로 화면 동작을 확인할 수 있습니다.

---

## 7. 자주 헷갈릴 수 있는 부분

- **`services/tracking.py`와 `services/playback.py`를 나눈 이유**: `tracking.py`는
  "탐지 결과 1개를 로그/알람으로 어떻게 연결할지"만, `playback.py`는 "영상 파일에서
  언제 어느 프레임을 읽을지"만 담당합니다. 재생 속도나 반복 재생 로직을 고치고
  싶으면 `playback.py`만, 트래킹/중복 알람 방지 로직을 고치고 싶으면 `tracking.py`만
  보면 됩니다.
- **`services/clip_recorder.py`를 `playback.py`에서 분리한 이유**: 클립 버퍼링·인코딩·
  S3 업로드는 "언제 프레임을 읽을지"와는 다른 관심사라 별도 파일로 뺐습니다.
- **화면 표시가 두 갈래로 나뉘는 이유**: 데모 모드가 아니고 영상이 재생 중이면
  `ui/camera/card.py`가 백엔드의 `/stream`(MJPEG)을 직접 가리켜 브라우저가
  Streamlit의 rerun 주기와 무관하게 매끄럽게 프레임을 받도록 합니다. 이때도
  탐지·로그·알람·클립 녹화는 여전히 Streamlit 쪽(`services/playback.py`)이
  독립적으로 수행합니다.
- **`backend.py`의 `model_lock`**: `/detect`와 `/stream`이 같은 백엔드 프로세스
  안에서 동시에 모델을 호출할 수 있어, 한 번에 하나씩만 추론하도록 락을
  걸어뒀습니다.
- **데모 모드 제거 시 수정할 곳**: `services/detection.py`의 `simulate_detections()`와
  `run_detection()` 안의 분기, `state.py`의 관련 두 줄, `views/settings.py`의
  데모 모드 UI 블록.
- **`conf_thresh`/`nms_thresh`의 단일 출처**: `backend.py`에서만 정의되고, 매 추론마다
  API 응답(`conf_thresh_used`)을 통해서만 전달됩니다.
- **위젯 key와 상태 key를 분리하는 이유**: `views/settings.py` 등의 체크박스/슬라이더는
  특정 조건에서만 그려집니다. Streamlit은 그려지지 않는 위젯의 key를 session_state에서
  삭제하므로, 다른 파일에서도 참조하는 실제 상태 key(`simulate` 등)는 위젯 전용
  key(`_xxx_widget`)와 분리하고 `on_change` 콜백으로 값을 복사합니다.
- **탐지 클래스 목록**: 사람 / 멧돼지 / 고라니 / 소형동물 4종. 클래스를 추가/변경할 때는
  `config.py`(색상), `db_rds.py`(`CLASS_ID_MAP` 및 기본 `class_map`),
  `services/detection.py`(데모 모드 동물 풀), `ui/log_tabs.py`(편집 탭 드롭다운),
  `DB_create.sql`(초기 데이터) — 5곳을 함께 맞춰야 합니다.
- **카메라 개수/이름의 단일 출처**: 더 이상 고정 리스트나 +/- 스텝퍼가 아니라,
  설정 페이지에서 지도에 마킹한 초소 개수로 자동 결정됩니다(§3). 관련 상태 관리는
  전부 `services/outposts.py`에 있고, `services/camera_registry.py`가 이를
  나머지 시스템이 쓰는 카메라 목록 형태로 변환합니다.
- **지도 마커 클릭 = 다중 선택 토글, 점멸 정지는 별도 아이콘**: `ui/outposts/viewer.py`는
  마커(점멸 여부 무관)를 클릭하면 왼쪽 패널에 표시할 카메라 선택을 토글합니다
  (여러 개 동시 선택 가능, 선택 개수에 맞춰 그리드로 배치). 이 선택 상태는
  "관제 지도" 탭 전용이며 '카메라 화면' 탭의 구역 선택과는 완전히 분리되어
  있습니다. `services/tracking.py`가 관리하는 `person_tracks_{cid}`(카메라별
  현재 추적 중인 사람 트랙)를 그대로 재사용해 점멸 여부를 판단합니다 — 별도의
  점멸 전용 상태를 새로 만들지 않고 기존 트래킹 상태에 얹은 구조이므로,
  트래킹 로직이 바뀌면 점멸 조건도 자동으로 같이 바뀝니다. 점멸을 멈추는
  것은 마커 본체가 아니라 옆의 작은 "⏹" 아이콘의 역할입니다(`blink_stopped_{cid}`).
- **"관제 지도" 탭이 카메라 카드를 재사용하지 않는 이유**: §4 참고 — Streamlit
  탭은 보이지 않는 탭의 코드도 함께 실행하므로, 인터랙티브 카드를 두 탭에
  중복 배치하면 위젯 key 충돌이 발생합니다.
- **영상 반복 재생**: 업로드한 영상이 끝에 도달하면 `services/playback.py`가
  자동으로 처음으로 되돌려 계속 재생합니다(24시간 CCTV 시뮬레이션). 현재
  일시정지/재개 버튼은 테스트 중 로그가 계속 쌓이는 것을 막기 위한 임시
  기능으로, `ui/camera/card.py`에 `TODO(임시/테스트용)` 주석으로 표시되어
  있습니다 — 실제 배포 전 제거를 검토하세요.
- **탐지 전후 클립 저장**: 새로운 사람/동물이 탐지되면, 탐지 시점 기준 앞뒤로
  `CLIP_PRE_SECONDS`/`CLIP_POST_SECONDS`(기본 각 3초)를 mp4로 녹화해 S3에
  올리고 로그의 스냅샷 경로를 그 클립으로 교체합니다. S3가 설정되어 있지
  않으면 클립을 만들지 않고 기존처럼 스냅샷 이미지만 남습니다.
