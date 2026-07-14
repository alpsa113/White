"""config.py — 전역 설정 및 튜닝 파라미터."""
import os

# 백엔드 API
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

# "사람"으로 취급할 클래스명
PERSON_CLASSES = {"사람", "person"}

# 과부하/도배 방지 튜닝값
PERSON_GAP_TOLERANCE = 10      # 사람이 사라져도 추적을 유지할 프레임 수
ANIMAL_TOAST_COOLDOWN = 10     # 동일 동물 토스트 억제 간격(초)

# 탐지(트랙) 시작/종료 전후로 덧붙일 여유 시간(초) — 클립은 이 여유를 더한
# [트랙 최초 탐지 ~ 트랙 종료] 전체 구간으로 생성됩니다(고정 길이가 아님).
CLIP_PRE_SECONDS = 3.0
CLIP_POST_SECONDS = 3.0

# 트랙이 비정상적으로 오래 지속될 경우(예: 정지된 오브젝트를 계속 같은 개체로 추적) 클립이
# 지나치게 길어지는 것을 막는 안전 상한(초)
MAX_CLIP_SECONDS = 60.0

# 클립/버퍼 저장 프레임의 최대 가로 해상도(px) — 메모리 절감용
CLIP_STORAGE_MAX_WIDTH = 480

# 클립 추출 동시 실행 개수 상한(자원 보호) — 초과분은 버리지 않고 큐에서 순서대로 처리됩니다.
CLIP_EXTRACTION_WORKERS = 2

# 데모/백엔드 실패 시 conf/nms 임계값 폴백
FALLBACK_CONF_THRESH = 0.50
FALLBACK_NMS_THRESH = 0.4

# 클래스별 바운딩 박스 색상
COLORS = {
    "사람": "#f85149",
    "멧돼지": "#e3a008",
    "고라니": "#3fb950",
    "소형동물": "#a371f7",
}
DEFAULT_COLOR = "#CFC8F1"

# 로그인 계정 (데모용 평문 하드코딩)
USERS = {
    "admin": {"password": "admin1234", "role": "admin"},
    "user": {"password": "user1234", "role": "user"},
}

# 초소 지도 이미지 경로 (고정 파일, 업로드 아님)
PRESET_MAP_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "assets", "gop_preset_map.png")

# 시연용 사전 등록 영상 — 마커 위치는 여전히 관리자가 지도에서 직접 찍어야 합니다. 이 목록을
# 채워두면, 관리자가 마커를 찍는 순서대로(1번째 클릭 → 0번 항목, 2번째 클릭 → 1번 항목, ...)
# 업로드 버튼 없이 로컬 영상 경로가 자동 배정됩니다(원본 파일을 복사하지 않고 경로만 참조).
# 비워두면(기본값) 기존처럼 마커를 찍은 뒤 업로드해야 합니다. eo_path/tir_path는 한쪽만 있어도 됩니다.
DEMO_VIDEOS: list[dict] = [
    {"info": "초소1",
     "eo_path": r"videos//video4.mp4", "tir_path": r"videos//video1.mp4"},
    {"info": "초소2",
     "eo_path": r"videos//video3.mp4", "tir_path": r"videos//video2.mp4"},
    {"info": "초소3",
     "eo_path": r"videos//video1.mp4", "tir_path": r"videos//video3.mp4"},
    {"info": "초소4",
     "eo_path": r"videos//video2.mp4", "tir_path": r"videos//video4.mp4"},
]

# 카메라 개수 상한 (실제 개수는 초소 마커 개수로 결정됨)
MAX_CAMERAS = 8


def build_camera_list(count: int) -> list[dict]:
    """count개의 카메라 슬롯 딕셔너리 리스트를 생성합니다."""
    count = max(1, min(count, MAX_CAMERAS))
    cams = []
    for i in range(count):
        name = f"CCTV-{i+1:02d} (구역 {i+1})"
        cams.append({"id": f"cam{i+1}", "name": name})
    return cams
