# Python 파일 정리 및 시스템 부담 조사 보고서

조사 대상: `D:\SideProject\White`

작성 목적:
- 현재 프로그램에서 불필요하거나 구버전으로 보이는 Python 파일 식별
- 실제 실행 중 시스템 부담을 만들 가능성이 큰 Python 파일 식별
- 사람이 보기 쉽게 현재 폴더 구조와 실행 흐름을 함께 정리

## 요약

현재 삭제 또는 정리 후보로 가장 강한 Python 파일은 다음 2개입니다.

1. `ui/camera_card.py`
2. `services/video_tracking.py`

두 파일은 현재 실행 흐름에서 직접 사용되지 않고, 서로만 연결된 구버전 구현으로 보입니다.

반대로 실제 시스템 부담 가능성이 큰 현재 사용 파일은 다음입니다.

1. `services/playback.py`
2. `backend.py`
3. `services/clip_recorder.py`
4. `services/detection.py`
5. `services/tracking.py`

## 현재 폴더 구조

아래는 Python 파일과 주요 리소스 폴더 중심으로 정리한 구조입니다.

```text
White/
├── app.py
├── backend.py
├── config.py
├── db_rds.py
├── s3_storage.py
├── state.py
├── requirements.txt
├── environment.yml
├── README.md
├── PROJECT_GUIDE.md
├── configs/
├── data/
├── models/
├── notebooks/
├── service/
├── src/
├── videos/
├── weights/
├── services/
│   ├── __init__.py
│   ├── alerts.py
│   ├── audio_alert.py
│   ├── camera_registry.py
│   ├── clip_recorder.py
│   ├── detection.py
│   ├── log_management.py
│   ├── playback.py
│   ├── tracking.py
│   └── video_tracking.py        # 정리 후보
├── ui/
│   ├── __init__.py
│   ├── alert_panel.py
│   ├── camera_card.py           # 정리 후보
│   ├── dialogs.py
│   ├── layout.py
│   ├── log_tabs.py
│   ├── styles.py
│   └── camera/
│       ├── __init__.py
│       ├── card.py              # 현재 사용 중
│       ├── grid.py              # 현재 사용 중
│       ├── reorder.py
│       ├── spotlight.py         # 현재 사용 중
│       ├── toolbar.py           # 현재 사용 중
│       └── zoom.py              # 현재 사용 중
├── utils/
│   ├── __init__.py
│   └── formatters.py
├── views/
│   ├── __init__.py
│   ├── dashboard.py
│   ├── logs.py
│   └── settings.py
└── __pycache__/                 # 생성 캐시, 정리 가능
```

## 현재 실행 흐름

현재 앱의 주요 실행 흐름은 다음과 같습니다.

```text
app.py
├── state.init_session_state()
├── ui.layout.render_topnav()
├── services.camera_registry.get_active_cameras()
├── views.dashboard.render()
│   ├── ui.camera.toolbar
│   ├── ui.camera.grid
│   │   └── ui.camera.card.render_camera_card()
│   └── ui.camera.spotlight
│       └── ui.camera.card.render_camera_card()
└── services.playback.run_playback_loop()
    ├── services.tracking.process_frame()
    ├── services.detection.run_detection()
    └── services.clip_recorder
```

실제 YOLO 추론 서버는 별도 프로세스로 다음 파일이 담당합니다.

```text
backend.py
├── FastAPI 앱
├── YOLO 모델 로드
├── /detect
├── /health
└── /stream
```

## 불필요하거나 구버전으로 보이는 Python 파일

### 1. `ui/camera_card.py`

판단: 삭제 또는 보관 후보

이유:
- 현재 화면 구성은 `ui/camera/card.py`를 사용합니다.
- `ui/camera/grid.py`와 `ui/camera/spotlight.py` 모두 `ui.camera.card.render_camera_card`를 import합니다.
- `ui/camera_card.py`는 현재 실행 흐름에서 직접 import되지 않습니다.
- 내부에서 `services.video_tracking`을 참조하므로, 구버전 카메라 카드 구현으로 보입니다.

관련 현재 사용 파일:
- `ui/camera/card.py`
- `ui/camera/grid.py`
- `ui/camera/spotlight.py`
- `services/playback.py`

권장 조치:
- 바로 삭제하기 전에 백업 브랜치 또는 커밋을 만든 뒤 제거를 검토합니다.
- 제거 후 `rg "camera_card|video_tracking"`로 남은 참조가 없는지 확인합니다.

### 2. `services/video_tracking.py`

판단: 삭제 또는 보관 후보

이유:
- 현재 앱은 `services.playback.run_playback_loop`를 사용합니다.
- `services/video_tracking.py`에도 `run_playback_loop`와 `process_frame` 계열 로직이 있어 `services/playback.py`, `services/tracking.py`와 역할이 중복됩니다.
- 현재 직접 참조는 `ui/camera_card.py`에서만 확인됩니다.
- 따라서 `ui/camera_card.py`와 함께 남아 있는 구버전 재생/트래킹 구현으로 보입니다.

권장 조치:
- `ui/camera_card.py`와 함께 정리하는 것이 자연스럽습니다.
- 삭제 전 `services/playback.py`, `services/tracking.py`에 필요한 로직이 이미 모두 이전되어 있는지 최종 확인합니다.

## 시스템 부담 가능성이 큰 현재 사용 파일

### 1. `services/playback.py`

판단: 현재 필요한 파일이지만 런타임 부담 핵심

부담 요인:
- `while True` 기반 재생 루프
- 여러 카메라 프레임 처리
- `cv2.resize`
- `st.image` 기반 화면 갱신
- 주기적 탐지 호출
- 클립 버퍼링 및 클립 생성 트리거
- `st.rerun` 호출

특히 카메라 수가 많거나 영상 해상도가 크면 CPU 사용량이 커질 수 있습니다.

관련 설정:
- `config.py`의 `DETECT_EVERY_SECONDS`
- `config.py`의 `MAX_CAMERAS`
- `config.py`의 `CLIP_PRE_SECONDS`
- `config.py`의 `CLIP_POST_SECONDS`

### 2. `backend.py`

판단: 현재 필요한 파일이지만 추론 서버 부담 핵심

부담 요인:
- YOLO 모델 로드
- `/detect` 요청 처리
- `/stream` MJPEG 스트리밍
- `cv2.VideoCapture`
- 백그라운드 탐지 스레드
- 모델 추론 lock 처리

실제 모델 추론이 이 파일에서 수행되므로 CPU, GPU, 메모리 사용량의 중심입니다.

### 3. `services/clip_recorder.py`

판단: 현재 필요한 파일이지만 탐지 빈도에 따라 부담 증가

부담 요인:
- 탐지 전후 프레임 버퍼 유지
- 탐지 발생 시 별도 스레드 생성
- `imageio` 기반 MP4 인코딩
- S3 업로드

탐지가 자주 발생하면 인코딩 작업과 업로드가 겹쳐 CPU, 디스크 I/O, 네트워크 부담이 커질 수 있습니다.

### 4. `services/detection.py`

판단: 현재 필요한 파일

부담 요인:
- 데모 모드가 꺼져 있으면 백엔드 API로 탐지 요청을 보냅니다.
- 탐지 주기가 짧을수록 백엔드 요청 수가 증가합니다.

### 5. `services/tracking.py`

판단: 현재 필요한 파일

부담 요인:
- 프레임별 탐지 결과를 기반으로 사람 탐지 상태, 알림, 추적 상태를 관리합니다.
- 직접적인 무거운 연산보다는 `playback.py` 루프 안에서 반복 호출되는 점이 부담 요인입니다.

## 정리 가능한 생성 캐시

다음 폴더들은 Python 실행 중 자동 생성되는 캐시입니다.

```text
__pycache__/
services/__pycache__/
ui/__pycache__/
ui/camera/__pycache__/
utils/__pycache__/
views/__pycache__/
```

삭제해도 Python이 필요할 때 다시 생성합니다.

권장 조치:
- 저장소에 포함하지 않는 것이 좋습니다.
- `.gitignore`에 `__pycache__/`, `*.pyc`가 포함되어 있는지 확인합니다.

## 권장 정리 순서

1. `rg "camera_card|video_tracking"`로 참조 상태 확인
2. `ui/camera_card.py`와 `services/video_tracking.py`를 삭제 후보로 분리
3. 앱 실행 확인
4. 대시보드 영상 업로드 및 재생 확인
5. 데모 모드와 실제 백엔드 모드 각각 확인
6. 문제가 없으면 두 파일 삭제
7. `__pycache__` 정리

## 최종 결론

삭제 후보:

```text
ui/camera_card.py
services/video_tracking.py
```

부하 관리가 필요한 현재 핵심 파일:

```text
services/playback.py
backend.py
services/clip_recorder.py
services/detection.py
services/tracking.py
```

정리 가능한 생성물:

```text
__pycache__/
*.pyc
```

