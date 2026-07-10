"""utils/formatters.py — 화면 표시용 순수 포맷팅 함수 모음."""


def fmt_dt(a: dict) -> str:
    """탐지 일시를 "YYYY-MM-DD HH:MM:SS" 문자열로 반환합니다(DB/메모리 레코드 통일)."""
    val = a.get("created_at")
    if not val:
        date_part = a.get("date", "")
        time_part = a.get("time", "")
        val = f"{date_part} {time_part}".strip() if date_part else time_part
    return str(val)[:19]
