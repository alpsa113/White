"""
utils/formatters.py — 화면 표시용 순수 포맷팅 함수 모음

DB 레코드와 세션(메모리) 레코드는 필드 구조가 서로 다른데
(예: DB는 created_at 하나, 메모리는 date+time 분리 저장), 이 차이를 UI 레이어에서
매번 신경 쓰지 않도록 여기서 한 번에 통일해서 반환합니다. Streamlit 호출이 없는
순수 함수들이라 어디서든 부작용 걱정 없이 사용할 수 있습니다.
"""


def fmt_dt(a: dict) -> str:
    """연월일시분초 형태의 탐지 일시 문자열을 반환합니다.
    DB 레코드는 created_at 필드를, 메모리 레코드는 date+time을 조합해 사용합니다."""
    val = a.get("created_at")
    if not val:
        date_part = a.get("date", "")
        time_part = a.get("time", "")
        val = f"{date_part} {time_part}".strip() if date_part else time_part
    return str(val)[:19]  # 마이크로초 등 불필요한 부분은 잘라내어 "YYYY-MM-DD HH:MM:SS" 형태로 고정


def fmt_src(a: dict) -> str:
    """입력 소스를 "video" / "image" 중 하나로 정규화합니다.
    실시간 영상 처리 로직은 source="영상"(한글)을 쓰고, DB 레코드는
    input_type="video"|"image"(영문)를 쓰기 때문에 이 둘을 하나로 맞춰줍니다."""
    raw = a.get("input_type") or a.get("source", "video")
    return raw if raw in ("video", "image") else "video"


def fmt_bbox(a: dict) -> str:
    """바운딩 박스 좌표를 "[x1, y1, x2, y2]" 문자열로 포맷하여 표에 표시하기 좋게 만듭니다."""
    return (
        f"[{a.get('x1', 0):.1f}, {a.get('y1', 0):.1f}, "
        f"{a.get('x2', 0):.1f}, {a.get('y2', 0):.1f}]"
    )
