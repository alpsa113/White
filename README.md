# GOP 통합 감시 시스템 — 프로젝트 구조 가이드

## 1. 한눈에 보는 전체 구조

```
project/
├── app.py                    # 메인 엔트리포인트 (Streamlit 실행 시작점, 로그인 게이트 + 페이지 라우팅)
├── config.py                 # 전역 설정값 (계정, 클래스 색상, 임계값, 클립 길이/해상도, 초소 프리셋 등)
├── state.py                  # session_state 초기화
├── requirements.txt          # 프로젝트 의존성 목록 (pip install -r requirements.txt)
├── backend.py                # FastAPI 추론 서버 (별도 프로세스로 실행)
├── db_rds.py                 # AWS RDS(MySQL) 연동
├── s3_storage.py              # AWS S3 이미지/클립 저장 연동
│
├── assets/
│   └── gop_preset_map.png     # 초소 위치 프리셋 지도 이미지 (config.PRESET_MAP_IMAGE_PATH가 가리킴, 마커 좌표는 미포함)
├── scripts/
│   └── generate_preset_map.py # 위 플레이스홀더 지도를 생성한 스크립트 (실제 지도 교체 시 참고용)
│
├── services/                  # 화면 없는 "로직" — DB/S3/추론/재생/클립 녹화/초소 관리
│   ├── detection.py            # 백엔드 API 호출, 박스 그리기, 데모 데이터 생성
│   ├── tracking.py               # 프레임 1장의 사람/동물 트래킹 → 로그/알람 연결
│   ├── playback.py                # 다중 카메라 재생 루프 + 미디어 반영(start_camera_media)
│   ├── clip_recorder.py            # 탐지 전후 짧은 클립(mp4) 녹화·인코딩·S3 업로드 (§8 메모리 관리 참고)
│   ├── alerts.py                    # 탐지 로그 생성/갱신, DB 동기화 (§8 메모리 관리 참고)
│   ├── camera_registry.py            # 초소 → 카메라 목록 변환, 매핑된 영상 자동 반영, 정리
│   ├── log_management.py              # 로그 편집/삭제 저장 처리
│   ├── audio_alert.py                  # 사람 탐지 시 알림음 생성
│   └── outposts.py                      # 초소(지도 마커) CRUD, 정보 편집, EO/TIR 영상 매핑
│
├── ui/                         # Streamlit 화면(위젯) 렌더링 전담
│   ├── styles.py                 # 여러 화면이 공통으로 쓰는 CSS/인라인 스타일 문자열
│   ├── layout.py                  # 사이드바(브랜드명/페이지 전환/최근 탐지/계정 영역)
│   ├── log_tabs.py                  # 로그 조회 탭 + 편집 탭
│   ├── camera/                        # 카메라 카드 관련 UI 전용 하위 패키지
│   │   ├── card.py                      # 카드 레이아웃(영상 위 오버레이 제목 바) + 재생 상태 전환
│   │   ├── zoom.py                        # 마우스 휠/드래그 확대·이동 (순수 JS, 독립)
│   │   ├── grid.py                          # 그리드 배치
│   │   ├── spotlight.py                       # 포커스 카메라+관제 지도(1행) / 나머지 카메라(2행) 배치
│   │   └── toolbar.py                           # 헤더 날짜/시각 시계 + 구역 전환 상태 동기화
│   └── outposts/                      # 초소(지도 마커) 관련 UI 전용 하위 패키지
│       ├── marker_overlay.py            # 지도 위 마커 렌더링 + 선택 상태 공용 로직 (editor.py·viewer.py 공유)
│       ├── editor.py                    # 설정 페이지: 지도 클릭 마킹 + 초소정보/영상 매핑 편집 (admin) / 조회 (user)
│       └── viewer.py                     # 관제 지도(마커+점멸) 렌더링 — ui/camera/spotlight.py가 끼워 씀
│
├── views/                       # 페이지 단위 조립 (ui + services 호출만)
│   ├── login.py                    # 페이지0: 로그인 (ID + 사용자 유형 + PW)
│   ├── dashboard.py                 # 페이지1: 관제 대시보드 (그리드/스포트라이트 — §4 참고)
│   ├── logs.py                       # 페이지2: 감지 기록 (role에 따라 편집 탭 노출 여부 결정)
│   └── settings.py                    # 페이지3: 설정 (admin/user 공통 접근, 편집 권한만 admin — §2 참고)
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
`services/outposts.py`(상태)와 `ui/outposts/marker_overlay.py`(마커 렌더링)를
공용 출처로만 공유합니다.

이 시스템은 **페이지 전환/계정 영역을 모두 사이드바에서 처리합니다.** CCTV
화면이 메인 영역 최상단에 바로 붙을 수 있도록 한 설계이며, 관제 화면 특성상
페이지는 로그인 이후 항상 세 개(실시간 감시/감지 기록/설정)로 고정되어
있습니다. RDS/S3 연결 상태 뱃지나 실시간 시계처럼 상시 표시되던 요소들은
화면을 복잡하게 만든다는 판단하에 정리되었습니다 — 시계는 '실시간 감시'
페이지 헤더로, 연결 상태는 '설정' 페이지의 "시스템 상태" 섹션(조회 전용,
admin/user 공통)으로 옮겨졌습니다.

---

## 2. 로그인과 권한 모델

로그인 화면(`views/login.py`)은 ID, **사용자 유형**(관리자/사용자) 드롭다운,
PW 세 가지를 입력받습니다. ID/PW가 맞아도 선택한 사용자 유형이 계정의 실제
role과 다르면 로그인이 거부됩니다 (`config.USER_TYPE_OPTIONS`).

| 페이지 | 관리자(admin) | 병사(user) |
|---|---|---|
| 실시간 감시 (그리드/스포트라이트, 관제 지도 포함) | ✅ | ✅ |
| 감지 기록 — 로그 조회 및 이미지 | ✅ | ✅ |
| 감지 기록 — 로그 편집 및 삭제 | ✅ | ❌ (탭 자체가 보이지 않음) |
| 설정 — 초소 위치/정보/영상 매핑 편집 | ✅ | 조회만 가능 (❌ 마커 추가·삭제·영상 업로드·선택) |
| 설정 — 데모 모드 | ✅ | ❌ (섹션 자체가 보이지 않음) |
| 설정 — 시스템 상태(RDS/S3 연결 여부) | ✅ | ✅ (조회만) |

로그인 직후 랜딩 페이지도 role에 따라 다릅니다(`config.DEFAULT_LANDING_PAGE`):
관리자는 초소별 CCTV 영상이 제대로 매핑되어 있는지 먼저 확인할 수 있도록
**설정** 페이지로, 사용자는 곧바로 **실시간 감시**로 진입합니다.

"설정" 페이지는 이제 admin/user 모두 접근할 수 있지만(사이드바 "설정" 버튼이
두 role 모두에 보임), 페이지 내부에서 role별로 위젯 노출을 다르게 합니다
(`ui/outposts/editor.py`, `views/settings.py`) — 접근 자체를 막던 방식에서
"보여주되 조회만 가능하게" 하는 방식으로 바뀌었습니다.

---

## 3. 초소(카메라) 설정 — services/outposts.py, ui/outposts/

지도 **"이미지"**는 `config.PRESET_MAP_IMAGE_PATH`에 고정되어 있어 관리자가
업로드하지 않습니다. 반면 그 위의 초소(마커) **"위치"**는 관리자가 설정
페이지 지도를 클릭해 직접 찍고 지울 수 있습니다 — **찍은 마커 개수가 곧
'실시간 감시'의 카메라 개수**입니다. 실제 배포 시에는 `config.
PRESET_MAP_IMAGE_PATH` 경로의 파일만 실제 GOP 관할구역 지도 이미지로
교체하면 됩니다 (좌표는 관리자가 그 위에서 직접 찍으므로 별도 설정이 필요
없습니다).

관리자가 설정 페이지(`ui/outposts/editor.py`)에서 초소별로 할 수 있는 일
(user는 아래 1번의 "조회"만 가능하고 나머지는 버튼 자체가 보이지 않습니다):

1. **마커 추가/삭제** — 지도를 클릭하면 그 위치에 새 마커가 추가됩니다
   (`services/outposts.add_marker()`). 목록의 🗑 버튼으로 삭제하면 그 채널의
   재생 리소스도 함께 정리됩니다(`remove_marker()`).
2. **초소 정보 수정** — 입력하는 즉시 자동 저장됩니다.
3. **CCTV 영상 매핑(EO/TIR 채널별)** — 저희 탐지 모델은 EO(가시광)·TIR(열화상)
   두 영상을 함께 입력받는 RGB-IR 융합 모델이므로, 각 초소에 영상을 EO/TIR
   채널로 각각 매핑해둘 수 있습니다(`services/outposts.set_marker_video()`,
   팝오버 버튼 🎬 안에 있음). 기본적으로는 **EO 채널이 재생·탐지 파이프라인을
   구동**합니다 — `services/camera_registry.get_active_cameras()`가 대시보드
   진입 시마다 아직 반영되지 않은 채널을 찾아 자동으로 재생을 시작합니다
   (`services/playback.start_camera_media()`). 카메라 카드 오버레이 제목 바의 EO/TIR
   버튼(`ui/camera/card.py`)으로 즉석에서 **어느 채널이든** 재생 채널로
   전환할 수 있습니다 — 전환된 채널은 `session_state.active_channel_{id}`에
   기억되어, 다음 자동 반영 시에도(예: 다른 페이지에 다녀온 뒤) 그 채널이
   유지됩니다. **'실시간 감시' 페이지의 카메라 카드는 자체 업로드 버튼을
   갖지 않습니다** — 이 설정 페이지 매핑이 그 역할을 대신합니다.
4. **"CCTV 화면 보기" 선택/해제** — 🔵/🔴 버튼으로 토글하며, 이 선택은
   '실시간 감시' 페이지(그리드 필터)·관제 지도와 모두 동기화됩니다(§3.2).

마커 좌표(x_ratio/y_ratio)는 지도 원본 이미지 기준 0~1 비율로 저장되므로,
설정 페이지와 대시보드 지도 탭에서 이미지가 서로 다른 크기로 표시되더라도
항상 같은 상대 위치에 마커가 그려집니다.

`services/camera_registry.get_active_cameras()`가 이 초소 목록을
`{"id", "name"}` 카메라 딕셔너리로 변환해 나머지 시스템(재생 루프, 트래킹,
그리드/스포트라이트)에 기존과 동일하게 공급합니다. 아직 초소를 하나도
찍지 않은 초기 상태에서는 기본 카메라 1개로 폴백합니다.

카메라 클래스를 추가/변경할 때 함께 맞춰야 할 5곳(§4의 "탐지 클래스 목록"
항목)은 초소 설정과 무관하며 그대로 적용됩니다.

현재 초소 목록(위치/정보)과 매핑된 영상은 **세션(session_state) 메모리에만
보관**됩니다 — 앱 재시작/재로그인 시 초기화됩니다. 영구 저장이 필요해지면
`db_rds.py`에 전용 테이블(영상은 `s3_storage.py`)을 추가하고
`services/outposts.py`의 CRUD 함수만 DB/S3 연동으로 바꿔주면 됩니다.

### 3.1 지도 미리보기가 클릭 가능한 마커 버튼을 쓰지 않는 이유

설정 페이지 지도는 새 마커를 "클릭으로 추가"해야 하므로,
`streamlit_image_coordinates`(클릭 좌표를 돌려주는 컴포넌트)가 이미지 위
클릭을 전담해서 가로챕니다. 그 위에 관제 지도처럼 클릭 가능한 마커 버튼을
또 겹쳐 그리면 "클릭 = 추가"와 "클릭 = 선택"이 같은 이미지 위에서
충돌합니다. 그래서 설정 페이지 지도는 마커를 PIL로 그려 넣은 읽기 전용
미리보기(색상만 반영)로 보여주고, 실제 선택/해제·삭제는 그 아래 목록의
버튼으로 하도록 역할을 분리했습니다(`ui/outposts/editor.py`). 관제 지도는
클릭으로 마커를 추가할 필요가 없으므로, 마커 자체가 클릭 가능한 버튼입니다
(`ui/outposts/marker_overlay.py`).

### 3.2 마커 색상과 선택 상태 — 설정 페이지 · 관제 지도 · '실시간 감시' 그리드 필터, 3곳 동기화

설정 페이지의 지도 미리보기와 관제 지도는 `ui/outposts/marker_overlay.py`를
함께 사용해 동일한 색상 규칙을 씁니다.

- 🔵 **하늘색(기본)** — 아직 "CCTV 화면 보기"로 선택되지 않은 마커.
- 🔴 **빨간색** — "CCTV 화면 보기"로 선택된 마커.

마커를 선택/해제하면(설정 페이지의 🔵/🔴 버튼, 또는 관제 지도의 마커 클릭)
`ui/outposts/marker_overlay.toggle_selection()`이 `session_state.
_map_selected_cam_ids`(다중 선택 상태)를 갱신합니다. 이 값 하나가 세 곳
모두에서 같은 뜻으로 쓰입니다: 관제 지도의 왼쪽 CCTV 요약, 두 화면의 마커
색상, 그리고 '실시간 감시' 페이지의 그리드 필터(`views/dashboard.py`가 이
값이 비어있지 않으면 선택된 카메라만 그리드로 좁혀 보여줍니다 — §4 참고).

사람 탐지 시의 점멸(blink)은 이 색상과는 별개 축입니다 — 선택 여부와
무관하게 현재 색상(빨강/하늘색) 그대로 깜빡이는 효과만 덧붙습니다(관제
지도에서만 동작 — §4 참고).

---

## 4. 실시간 감시 페이지 — 그리드 · 스포트라이트 · 그리드 필터

`views/dashboard.py`는 더 이상 탭으로 나뉘어 있지 않습니다 — 예전에는
"카메라 화면"/"관제 지도" 탭 2개였지만, "관제 지도" 탭은 제거되었고 그
지도(마커 점멸 포함)는 스포트라이트 모드일 때만 좌측 열 2행에 끼워 넣습니다
(`ui/outposts/viewer.render_map()` → `ui/camera/spotlight.py`).

화면은 상황에 따라 세 가지 모드 중 하나로 그려집니다(`views/dashboard.py`
가 매 실행마다 이 순서로 판단):

1. **그리드 필터 모드** — 지도(설정 페이지 또는 관제 지도)에서 마커를 하나
   이상 선택해둔 상태(`session_state._map_selected_cam_ids`가 비어있지
   않음)면, 아래 그리드/스포트라이트 여부와 무관하게 **선택된 카메라만
   그리드로 필터링**해서 보여줍니다 — 확대(스포트라이트)가 아니라 기존
   그리드 배치 그대로 대상만 좁히는 것입니다.
2. **그리드 모드(평상시 기본)** — 그리드 필터가 없고 `selected_cam ==
   "전체 구역"`이면, 전체 카메라를 정사각형에 가깝게 자동 계산된 열 수로
   그립니다(`ui/camera/grid.py`).
3. **스포트라이트 모드** — 그리드 필터가 없고 특정 카메라에 포커스되어
   있으면(사람 탐지 시 자동 전환, 또는 카드의 ⛶ 버튼으로 수동 전환),
   `ui/camera/spotlight.py`가 **2열** 구조로 배치합니다: 좌측 열은 위아래
   2행으로 [포커스된 CCTV 화면] · [관제 지도], 우측 열은 나머지 카메라를
   세로로 나열합니다. 좌우 비율은 `st.columns([1.4, 1])`이고, 관제 지도는
   이미지 실제 종횡비에 래퍼가 고정되어 있어 폭이 좁아져도 잘리거나 마커
   위치가 어긋나지 않습니다. 우측 열(나머지 카메라)은 `st.container(
   height=REST_HEIGHT_PX)`로 고정 높이를 주고, 넘치면 Streamlit이 기본
   제공하는 세로 스크롤바가 자동으로 생깁니다 — 커스텀 CSS 없이 세로
   스크롤 파라미터 하나로 해결되는 부분이라, 예전에 가로 스크롤을 직접
   구현하며 겪었던 것과 같은 레이아웃 버그가 애초에 생길 수 없는 구조입니다.
   카드 내부의 겹쳐 보이는 오버레이 버튼(이름/EO·TIR/⛶)은 `ui/camera/
   card.py`가 전담합니다(실측 헤드리스 브라우저 검증 완료). 스포트라이트에서
   전체 그리드로 되돌아가는 것은 카드의 ▦ 버튼으로 합니다(예전 사이드바의
   "구역 선택 → 전체 구역" 드롭다운을 대체).

영상 업로드는 이 페이지 어디에도 없습니다 — '설정' 페이지에서 초소별로
미리 매핑해둔 영상을 대시보드 진입 시 자동으로 재생합니다(§3 참고).

관제 지도의 마커는 다중 선택이 가능합니다. 사람이 탐지된 카메라의 마커는
점멸하고, 그 옆에는 별도의 작은 "⏹" 정지 아이콘이 함께 붙습니다 — 마커
본체를 클릭하면 선택만 토글되고 점멸은 유지되며, 점멸을 멈추려면 반드시 이
"⏹" 아이콘을 클릭해야 합니다. 정지 상태는 추적이 끊기면 자동 해제되어
다음 탐지부터 다시 점멸합니다.

사람이 새로 탐지되면 `services/playback.py`가 `_pending_selected_cam`을
예약해 자동으로 그 카메라의 스포트라이트로 전환시킵니다
(`ui/camera/toolbar.consume_pending_camera_switch()`가 반영). 단, 그리드
필터가 걸려 있으면(위 1번) 그 필터가 우선이라, 자동 전환은 그리드 필터가
없을 때만 실제로 스포트라이트로 나타납니다.

---

## 5. 파일별 상세 설명

### 5.1 최상위

| 파일 | 역할 |
|---|---|
| `app.py` | `streamlit run`으로 실행되는 유일한 진입점. 페이지 설정 → `state.init_session_state()` → 로그인 게이트(`views.login`) → `ui.layout.render_sidebar()` → 카메라 목록 계산 → 현재 선택된 페이지의 `render()` 호출 → `services.playback.run_playback_loop()`. 재생 루프는 **어떤 페이지를 보고 있든** 항상 마지막에 호출되어, 로그/설정 페이지에 있어도 탐지가 끊기지 않습니다. |
| `config.py` | `build_camera_list()`(초소가 하나도 없을 때의 폴백 카메라 생성), `PRESET_MAP_IMAGE_PATH`(초소 지도 이미지 경로), 클래스별 색상(`COLORS`), 계정 정보(`USERS`), 로그인 사용자 유형 매핑(`USER_TYPE_OPTIONS`), role별 랜딩 페이지(`DEFAULT_LANDING_PAGE`), 백엔드 API 주소(`API_BASE_URL`), 트래킹 튜닝 값, 클립 저장 해상도/동시 개수 상한(`CLIP_STORAGE_MAX_WIDTH`, `MAX_PENDING_CLIPS_PER_CAMERA` — §8 참고) 등 전역 상수. |
| `state.py` | 앱이 (재)실행될 때마다 `st.session_state`에 필요한 키들의 기본값을 채워 넣습니다 (초소/지도 선택 상태 포함). |
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
| | `start_camera_media()` | 미디어 바이트를 카메라 채널에 반영(영상 재생 시작/이미지 1회 분석) — 설정 페이지의 영상 매핑, 대시보드 진입 시 자동 반영, 카드의 EO/TIR 전환 버튼이 공용으로 사용합니다. |
| | `reset_cam_state()` | 카메라 채널의 재생/클립 관련 리소스를 완전 정리. 새 영상이 매핑될 때(`services/outposts.set_marker_video`)도 호출됩니다. |
| | `_downscale_for_clip()` | 화면 표시용 프레임과 별개로, 클립/버퍼 저장용 프레임만 더 작게 축소합니다(§8 메모리 관리). |
| `clip_recorder.py` | `push_frame_buffer()` / `start_pending_clips()` / `append_pending_clips()` | 탐지 전후 짧은 클립(mp4) 버퍼링·인코딩·S3 업로드. 카메라당 동시 대기 클립 개수를 제한합니다(§8). |
| `alerts.py` | `create_detection_alert()`, `update_detection_alert()` | 로그 생성/갱신, DB 동기화, 스냅샷 S3 업로드. S3에 영구 사본이 있으면 메모리 스냅샷은 보관하지 않습니다(§8). |
| `camera_registry.py` | `get_active_cameras()` | `services/outposts.py`의 초소 목록을 카메라 목록으로 변환하고, 각 카메라의 현재 활성 채널(EO/TIR, `active_channel_{id}`)에 매핑된 영상을 아직 반영하지 않았다면 자동 반영(`_sync_preset_media`)하고, 삭제된 카메라의 리소스를 정리합니다. |
| | `compute_grid_columns()`, `get_valid_area_options()` | 그리드 열 수 계산, 유효한 구역(카메라) 이름 목록 확인 — 삭제된 카메라를 보던 stale `selected_cam` 값을 안전하게 되돌리는 용도로도 쓰입니다(더 이상 드롭다운 UI 자체는 없음, §4 참고). |
| `log_management.py` | `save_log_edits()` | 로그 편집 탭 저장 처리 — 원본과 비교해 실제로 변경된 행만 반영합니다. |
| `audio_alert.py` | `play_alert_sound()` | 사람 탐지 시 재생할 비프음을 즉석에서 생성. |
| `outposts.py` | `get_outposts()` | 현재 등록된 초소(마커) 목록을 반환. |
| | `add_marker()` / `remove_marker()` | 지도 클릭 좌표로 마커 추가 / id로 마커 삭제(재생 리소스·선택 상태까지 함께 정리). |
| | `update_marker()` | 초소 정보/영상 소스(메모) 텍스트 갱신 (좌표는 건드리지 않음). |
| | `set_marker_video()` / `get_marker_video()` | 초소에 CCTV 영상을 채널별(EO/TIR)로 매핑/조회 — EO 매핑 시에만 재생 상태를 정리해 다음 렌더에서 새 영상으로 재초기화되게 함. |
| | `to_camera_list()` | 초소 목록을 `{"id","name"}` 카메라 딕셔너리 리스트로 변환. |

### 5.3 `ui/` — Streamlit 화면 렌더링

| 파일 | 주요 함수 | 설명 |
|---|---|---|
| `styles.py` | (상수 모음) | 버튼 줄바꿈 방지 CSS, 브랜드명 인라인 스타일, 헤더 시계 스타일 등 여러 화면이 공유하는 순수 CSS 문자열. |
| `layout.py` | `render_sidebar()` | 브랜드명, 페이지 전환 버튼(실시간 감시/감지 기록, role 공통), 최근 사람 탐지 배너, RDS 기록 실패 경고, 계정 영역(사이드바 최하단 고정 — 로그아웃/설정 버튼을 flexbox `margin-top:auto`로 밀어냄)을 조립합니다. RDS/S3 상태 뱃지와 실시간 시계는 더 이상 여기 없습니다(시계는 '실시간 감시' 헤더로, 연결 상태는 '설정' 페이지로 이동 — §1 참고). |
| `log_tabs.py` | `render_view_tab()`, `render_manage_tab()` | 로그 조회(표+이미지/클립 뷰어)와 편집(data_editor) 탭. 편집 탭 호출 여부는 `views/logs.py`가 role을 보고 결정합니다. |

#### `ui/camera/` — 카메라 카드 전용 하위 패키지

| 파일 | 역할 |
|---|---|
| `card.py` | 카드 레이아웃(영상 위에 겹쳐 그리는 오버레이 제목 바: 이름·EO/TIR 전환·⛶/▦·↺) + 상태 전환(매핑 전 → 재생 중 → 정지). 오버레이 3그룹(이름/EO·TIR/아이콘)은 표준 flexbox 3분할 패턴(`flex: 1 1 0` 균등분배)으로 배치하고, 폰트/패딩은 CSS 컨테이너 쿼리(cqw)로 카드 폭에 비례해 조절됩니다 — 카드 폭이 200~900px 어느 범위든 겹치지 않는 것을 헤드리스 브라우저로 실측 검증했습니다(파일 상단 주석 참고). 자체 업로드 버튼은 없습니다 — 매핑된 영상은 `services/camera_registry.py`가 자동으로 반영합니다. `render_camera_card()`가 유일한 공개 진입점입니다. |
| `zoom.py` | 집중 보기에서만 켜지는 마우스 휠 확대·드래그 이동. |
| `grid.py` | `render_camera_grid()` — 카드를 몇 개, 몇 열로 배치할지만 결정. |
| `spotlight.py` | `render_camera_spotlight()` — 좌측 열(2행: 포커스 카메라 · 관제 지도) + 우측 열(나머지 카메라, `st.container(height=N)` 세로 스크롤). §4 참고. |
| `toolbar.py` | `render_header_clock()`(헤더 우측 날짜+시각, 1초마다 독립 갱신되는 fragment) + `consume_pending_camera_switch()`(사람 탐지 자동 전환/카드 버튼이 예약한 스포트라이트 전환 반영). "구역 선택" 드롭다운은 더 이상 없습니다(§4 참고). |

#### `ui/outposts/` — 초소(지도 마커) 전용 하위 패키지

| 파일 | 역할 |
|---|---|
| `marker_overlay.py` | 마커 색상 규칙(선택=빨강/기본=하늘색) 상수, 클릭 가능한 마커 버튼(`render_marker()` — 관제 지도 전용), 선택 상태 토글(`toggle_selection()` — `_map_selected_cam_ids` 하나만 갱신, editor.py도 이 함수를 직접 호출). |
| `editor.py` | 설정 페이지: 지도 클릭으로 마커 추가(`streamlit_image_coordinates`, admin 전용) + 마커 미리보기(PIL로 그린 읽기 전용 원, §3.1) + 초소별 정보 자동저장 + EO/TIR 영상 매핑(팝오버) + 선택/삭제 버튼(모두 admin 전용). user는 읽기 전용 행(이름 + 비활성화된 정보 텍스트)만 봅니다. `render_outpost_editor()`가 유일한 공개 진입점입니다. |
| `viewer.py` | 관제 지도(마커+점멸) 렌더링. `render_map(cameras)`가 유일한 공개 진입점이며, `ui/camera/spotlight.py`가 좌측 열 2행에 끼워 호출합니다. |

### 5.4 `views/` — 페이지 조립

| 파일 | 설명 |
|---|---|
| `login.py` | 로그인 화면. ID + 사용자 유형(관리자/사용자) + PW를 모두 확인해야 인증에 성공합니다. |
| `dashboard.py` | 관제 대시보드. 그리드/스포트라이트/그리드 필터 3가지 모드를 조립합니다(§4 참고). **로직을 거의 담지 않습니다.** |
| `logs.py` | 감지 기록 — 최신순 정렬 후 조회 탭(공통)과 편집 탭(admin 전용)을 배치합니다. |
| `settings.py` | 설정 — 초소 위치 설정(`ui.outposts.editor`)이 최상단에 위치하고, 그 아래 데모 모드(admin 전용)/시스템 상태(admin·user 공통 조회)가 이어집니다. admin/user 모두 접근 가능하지만 노출되는 위젯이 role별로 다릅니다(§2 참고). |

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
6) (admin) 설정 페이지에서 지도를 클릭해 초소 마커를 찍고, 초소별 EO/TIR
   CCTV 영상을 매핑 → '실시간 감시'에서 EO 영상이 자동 재생
```

데모 계정은 `config.USERS`에 있습니다 (`admin`/`admin1234`, `user`/`user1234`).
로그인 화면에서 ID/PW와 함께 "사용자 유형"도 계정에 맞게 선택해야 합니다.

사이드바의 **"설정"** 페이지에서(데모 모드 토글은 admin 전용, §2 참고)
**"데모 모드"**를 켜두면 백엔드 없이도 무작위 탐지 데이터로 화면 동작을
확인할 수 있습니다.

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
- **카메라 개수/이름의 단일 출처**: 설정 페이지에서 지도에 클릭으로 찍은
  초소 개수로 결정됩니다(§3). 관련 상태 관리는 전부 `services/outposts.py`에
  있고, `services/camera_registry.py`가 이를 나머지 시스템이 쓰는 카메라
  목록 형태로 변환합니다. 지도 "이미지"만 고정(`config.PRESET_MAP_IMAGE_PATH`)
  이고, 마커 "위치"는 세션마다 관리자가 직접 만드는 동적 상태입니다.
- **EO/TIR 영상 매핑 = 설정 페이지, 재생 시작 = 대시보드 자동 반영**: 관리자가
  `ui/outposts/editor.py`에서 초소별로 EO/TIR 영상을 매핑(`services/outposts.
  set_marker_video(marker_id, "eo"|"tir", ...)`)해두면, 그 즉시 재생을
  시작하는 것이 아니라(그 채널이 지금 활성 채널일 때만) 재생 상태를 정리
  (`reset_cam_state`)해둡니다. 실제 `cv2.VideoCapture` 오픈과 재생 시작은
  `services/camera_registry.get_active_cameras()`가 대시보드 진입 시(또는
  다른 페이지에 있어도 app.py가 매 실행마다 카메라 목록을 계산하므로 그
  즉시) 그 카메라의 현재 활성 채널(`active_channel_{id}`, 기본값 EO)에
  매핑된 영상으로 `services/playback.start_camera_media()`를 호출해
  수행합니다 — `ui/camera/card.py`는 이 결과 상태만 그립니다. 카드 제목
  행의 EO/TIR 버튼을 누르면 그 자리에서 `active_channel_{id}`를 바꾸고
  즉시 그 채널로 재생을 다시 시작합니다 — **EO/TIR 둘 다 재생 채널이 될 수
  있습니다** (한쪽만 재생을 구동하던 이전 설계에서 바뀐 부분).
- **마커 클릭 = 화면마다 다른 의미**: 관제 지도에서는 마커 자체가 클릭
  가능한 버튼이라(`ui/outposts/marker_overlay.render_marker`) 클릭하면
  바로 선택이 토글됩니다. 설정 페이지 지도는 클릭이 "새 마커 추가"로
  쓰이고 있어서(§3.1), 선택/해제는 대신 목록의 🔵/🔴 버튼이
  `toggle_selection()`을 직접 호출하는 방식입니다. 두 경로 모두 결국 같은
  `toggle_selection()` 함수를 거치므로 결과 상태(`_map_selected_cam_ids`
  갱신, §3.2)는 동일합니다. `services/tracking.py`가 관리하는
  `person_tracks_{cid}`(카메라별 현재 추적 중인 사람 트랙)를 그대로
  재사용해 점멸 여부를 판단합니다(관제 지도에서만) — 별도의 점멸 전용
  상태를 새로 만들지 않고 기존 트래킹 상태에 얹은 구조이므로, 트래킹
  로직이 바뀌면 점멸 조건도 자동으로 같이 바뀝니다. 점멸을 멈추는 것은
  마커 본체가 아니라 옆의 작은 "⏹" 아이콘의 역할입니다(`blink_stopped_{cid}`).
- **관제 지도가 카메라 카드를 재사용하지 않는 이유**: `ui/outposts/viewer.py`의
  왼쪽 CCTV 요약(과거 "관제 지도" 탭이 쓰던 것과 동일한 컴포넌트)은
  `ui/camera/card.py`의 인터랙티브 카드 대신 `st.image()` 기반 읽기 전용
  표시만 사용합니다 — 같은 위젯 key를 가진 인터랙티브 카드를 그리드/
  스포트라이트와 동시에 두면 key 충돌이 나기 때문입니다.
- **영상 반복 재생**: 매핑한 영상이 끝에 도달하면 `services/playback.py`가
  자동으로 처음으로 되돌려 계속 재생합니다(24시간 CCTV 시뮬레이션). 현재
  일시정지/재개 버튼은 테스트 중 로그가 계속 쌓이는 것을 막기 위한 임시
  기능으로, `ui/camera/card.py`에 `TODO(임시/테스트용)` 주석으로 표시되어
  있습니다 — 실제 배포 전 제거를 검토하세요.
- **탐지 전후 클립 저장**: 새로운 사람/동물이 탐지되면, 탐지 시점 기준 앞뒤로
  `CLIP_PRE_SECONDS`/`CLIP_POST_SECONDS`(기본 각 3초)를 mp4로 녹화해 S3에
  올리고 로그의 스냅샷 경로를 그 클립으로 교체합니다. S3가 설정되어 있지
  않으면 클립을 만들지 않고 기존처럼 스냅샷 이미지만 남습니다.

---

## 8. 메모리 관리 — 장시간 운영 시 MemoryError 대응

카메라를 여러 대 동시에, 오래 재생할수록 서버 프로세스의 메모리 사용량이
늘어날 수 있는 시스템입니다. 아래 두 지점이 실제로 문제를 일으켰던(또는
일으킬 수 있는) 지점이고, 각각 어떤 안전장치가 들어가 있는지 정리합니다.

### 8.1 `session_state.detection_logs`의 스냅샷 누적 (핵심 원인이었던 버그)

`detection_logs`는 세션 내내 계속 `append`만 되고, 관리자가 로그 편집
탭에서 수동으로 삭제하기 전까지는 절대 줄어들지 않는 리스트입니다
(`services/log_management.py`가 유일한 삭제 경로). 예전에는 새 탐지가
생길 때마다 이 리스트의 각 레코드가 **원본 해상도 PIL 이미지 객체**
(`record["snapshot"]`)를 무조건 통째로 들고 있었고, 추적이 계속되는
동안(`update_detection_alert()`) 더 선명한 프레임으로 계속 교체되면서도
리스트 자체는 줄어들지 않았습니다 — 탐지가 잦은 카메라가 여러 대인 채로
오래 운영하면 이 리스트가 곧 수백MB~수GB 단위로 불어나, 결국 다음
이미지를 PNG로 인코딩하려는 시점(`PIL.PngImagePlugin.putchunk` 등, 딱히
그 코드 자체가 원인은 아니고 그 시점에 메모리가 이미 바닥나 있었을
뿐입니다)에 `MemoryError`로 이어졌습니다.

**현재 원칙(`services/alerts.py`): "S3에 이미 영구 사본이 있으면 메모리
사본은 갖고 있지 않는다"**를 생성/갱신 양쪽에 일관되게 적용합니다.

- `create_detection_alert()` — S3 업로드가 성공했으면(`image_key`가
  채워짐) 그 즉시 `record["snapshot"] = None`으로 두고, 실패했거나 S3
  자체가 꺼져있는 "메모리 모드"일 때만 유일한 사본으로서 보관합니다.
- `update_detection_alert()` — 추적 중 더 선명한 프레임이 들어와도, 이미
  S3 영구 사본(`image_path`/`uri`)이 있는 레코드라면 스냅샷을 다시
  채우지 않습니다. 오래 추적되는 대상일수록(예: 한 화면에 몇 분씩 머무는
  사람) 이 갱신이 반복 호출되므로, 여기서 걸러주지 않으면 그 시간 내내
  큰 이미지 객체를 계속 새로 만들어 붙잡고 있게 됩니다.
- `services/clip_recorder._apply_clip_to_log()` — 클립(mp4) 업로드가
  끝나 스냅샷을 클립으로 교체할 때도 명시적으로 `snapshot = None`을
  한 번 더 걸어 안전망을 둡니다.

로그 조회 화면(`ui/log_tabs.py`)은 이미 이 상황을 전제로 설계되어
있었습니다 — 메모리 스냅샷이 없으면 클립을 우선 보여주고, 클립도 없으면
그때 S3에서 다시 내려받습니다. 즉 이번 수정은 "화면에 보여줄 이미지가
없어지는" 회귀 없이, **불필요하게 오래 붙잡고 있던 메모리만** 줄인
것입니다. S3가 꺼져있는 "메모리 모드"에서는 여전히 유일한 사본이라 계속
보관해야 하므로, 매우 오래(며칠 단위로) 운영할 계획이라면 S3 연동을
켜두는 것을 권장합니다.

### 8.2 클립/순환 버퍼의 프레임 메모리 (`services/clip_recorder.py`, `services/playback.py`)

탐지 전후 짧은 클립을 만들기 위해 카메라별로 최근 `CLIP_PRE_SECONDS`
(기본 3초) 분량의 프레임을 순환 버퍼에 들고 있다가, 새 탐지가 발생하면
그 버퍼 + 이후 `CLIP_POST_SECONDS`(기본 3초) 분량을 합쳐 인코딩합니다.
프레임 1장이 화면 표시 해상도(최대 1080px) 그대로면 카메라 수·클립
개수에 비례해 금방 커질 수 있어, 두 가지 상한을 뒀습니다.

- **저장 해상도 축소** — `services/playback.py`가 클립/버퍼에 넘기는
  프레임은 화면 표시용(`annotated`)과 별개로 `CLIP_STORAGE_MAX_WIDTH`
  (기본 640px, `config.py`)로 한 번 더 축소한 사본입니다
  (`_downscale_for_clip()`). 클립은 "무슨 일이 있었는지 확인하는 짧은
  리뷰 영상"이 목적이라 화면 표시만큼 고해상도일 필요가 없습니다.
- **카메라당 동시 대기 클립 개수 상한** — 대기 클립 1개는
  `CLIP_PRE_SECONDS`+`CLIP_POST_SECONDS`(기본 6초) 분량의 프레임을
  통째로 들고 있습니다. 짧은 시간에 새 탐지가 연달아 발생하면(여러
  사람이 잇따라 등장 등) 카메라 1대에서 대기 클립이 동시에 여러 개
  쌓일 수 있는데, `config.MAX_PENDING_CLIPS_PER_CAMERA`(기본 2)를
  넘어서는 새 클립 요청은 건너뜁니다 — 로그 자체는 그대로 남고(탐지를
  놓치지 않음), 그 사건의 짧은 리뷰 클립만 생략됩니다.
- 클립 인코딩·업로드는 항상 별도 daemon 스레드에서 실행됩니다
  (`_finalize_clip_async`) — 개수 상한이 없다면 탐지가 몰릴 때 동시
  실행 스레드 수도 함께 늘어날 수 있는데, 위 대기 클립 개수 상한이
  간접적으로 동시 스레드 수도 제한합니다.

### 8.3 흔히 오해하기 쉬운 부분

- **"영상을 0.3초 단위로 쪼개서 추론하기 때문"이라는 설명은 절반만 맞습니다.**
  `DETECT_EVERY_SECONDS`(0.3초)는 실제 모델 추론 주기일 뿐이고, 프레임
  자체는 영상의 실제 FPS(보통 24~30fps)에 맞춰 그보다 훨씬 자주
  버퍼/클립에 쌓입니다 — 메모리 사용량은 추론 주기가 아니라 이 프레임
  버퍼링 주기에 더 크게 좌우됩니다(§8.2).
- **프레임을 리스트에 무한정 쌓아두고 있었던 것은 아닙니다.** 순환 버퍼
  (`frame_buffer_{cid}`)는 원래부터 `deque` + cutoff로 오래된 프레임을
  자동으로 버리는 구조였고, 대기 클립(`pending_clips_{cid}`)도 완료되면
  목록에서 제거됩니다 — "제너레이터로 바꿔서 한 프레임만 메모리에 남게
  하라"는 식의 구조적 재설계가 필요했던 것은 아니고, 문제의 핵심은
  §8.1의 `detection_logs` 누적과, §8.2의 프레임 크기/동시 개수였습니다.
- **`st.image()`를 계속 호출하는 것 자체가 누수는 아닙니다.** 카메라별로
  `st.empty()` 슬롯 하나만 만들어두고 그 자리에 계속 이미지를 갈아
  끼우는 구조라(`ui/camera/card.py`), 화면에 프레임이 쌓여 페이지가
  길어지는 문제는 원래 없습니다. 다만 매 프레임 `session_state[
  f"result_{cid}"]`에 마지막 프레임 1장을 저장해두는 것은 카메라당
  최대 1장이라 무시할 수 있는 수준입니다.
