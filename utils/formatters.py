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
