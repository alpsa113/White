"""
utils/formatters.py — 화면 표시용 순수 포맷팅 함수 모음

DB 레코드와 세션(메모리) 레코드 간 필드 구조 차이
(created_at vs date+time, source vs input_type)를 UI 레이어에서
일관되게 표시하기 위한 정규화 헬퍼입니다. Streamlit 호출 없는 순수 함수입니다.
"""


def fmt_dt(a: dict) -> str:
    """연월일시분초 형태의 탐지 일시를 반환합니다.

    DB 레코드는 created_at, 세션(메모리) 레코드는 date+time 분리 저장 → 통합.
    """
    val = a.get("created_at")
    if not val:
        date_part = a.get("date", "")
        time_part = a.get("time", "")
        val = f"{date_part} {time_part}".strip() if date_part else time_part
    return str(val)[:19]


def fmt_src(a: dict) -> str:
    """입력 소스를 video / image 중 하나로 정규화합니다.

    실시간 영상은 source="영상", DB 레코드는 input_type="video"|"image" → 정규화.
    """
    raw = a.get("input_type") or a.get("source", "video")
    return raw if raw in ("video", "image") else "video"


def fmt_bbox(a: dict) -> str:
    """바운딩 박스 좌표를 "[x1, y1, x2, y2]" 문자열로 포맷합니다."""
    return (
        f"[{a.get('x1', 0):.1f}, {a.get('y1', 0):.1f}, "
        f"{a.get('x2', 0):.1f}, {a.get('y2', 0):.1f}]"
    )
