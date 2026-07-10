"""config.py — 전역 설정 및 튜닝 파라미터."""
import os

# 백엔드 API
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
API_URL = API_BASE_URL + "/detect"

# "사람"으로 취급할 클래스명
PERSON_CLASSES = {"사람"}

# 과부하/도배 방지 튜닝값
DETECT_EVERY_SECONDS = 0.75    # 추론 호출 최소 간격(초)
PERSON_GAP_TOLERANCE = 10      # 사람이 사라져도 추적을 유지할 프레임 수
ANIMAL_TOAST_COOLDOWN = 10     # 동일 동물 토스트 억제 간격(초)

# 탐지 전후 클립 길이(초)
CLIP_PRE_SECONDS = 3.0
CLIP_POST_SECONDS = 3.0

# 클립/버퍼 저장 프레임의 최대 가로 해상도(px) — 메모리 절감용
CLIP_STORAGE_MAX_WIDTH = 480

# 카메라 1대당 동시 대기 클립 개수 상한(메모리 보호)
MAX_PENDING_CLIPS_PER_CAMERA = 1

# 데모/백엔드 실패 시 conf/nms 임계값 폴백
FALLBACK_CONF_THRESH = 0.7
FALLBACK_NMS_THRESH = 0.7

# 클래스별 바운딩 박스 색상
COLORS = {
    "사람": "#f85149",
    "멧돼지": "#e3a008",
    "고라니": "#3fb950",
    "소형동물": "#a371f7",
}
DEFAULT_COLOR = "#CFC8F1"

# 업로드 허용 확장자
IMAGE_EXTS = ("jpg", "jpeg", "png")
VIDEO_EXTS = ("mp4", "mov", "avi", "mkv")

# 로그인 계정 (데모용 평문 하드코딩)
USERS = {
    "admin": {"password": "admin1234", "role": "admin"},
    "user": {"password": "user1234", "role": "user"},
}
USER_TYPE_OPTIONS = {"관리자": "admin", "병사": "user"}
DEFAULT_LANDING_PAGE = {"admin": "설정", "user": "관제 대시보드"}

# 초소 지도 이미지 경로 (고정 파일, 업로드 아님)
PRESET_MAP_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "assets", "gop_preset_map.png")

# 카메라 개수 상한 (실제 개수는 초소 마커 개수로 결정됨)
MAX_CAMERAS = 16


def build_camera_list(count: int) -> list[dict]:
    """count개의 카메라 슬롯 딕셔너리 리스트를 생성합니다."""
    count = max(1, min(count, MAX_CAMERAS))
    cams = []
    for i in range(count):
        name = f"CCTV-{i+1:02d} (구역 {i+1})"
        cams.append({"id": f"cam{i+1}", "name": name})
    return cams
