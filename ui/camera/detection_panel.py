"""ui/camera/detection_panel.py — '실시간 감시' 화면 우측 객체 탐지 이력 패널."""
import base64
from pathlib import Path

import streamlit as st

from config import COLORS, PERSON_CLASSES
from utils.formatters import fmt_dt

ICON_DIR = Path(__file__).resolve().parents[2] / "icons"

# 탐지 클래스명 → icons/ 파일명
CLASS_ICON_FILES = {
    "사람": "person.png",
    "멧돼지": "boar.png",
    "고라니": "deer.png",
    "소형동물": "small_object.png",
}

PANEL_HEIGHT_PX = 780
MAX_ITEMS = 50


@st.cache_data
def _icon_b64(class_name: str) -> str:
    """클래스 아이콘 파일을 base64 문자열로 읽어옵니다. 없으면 빈 문자열."""
    filename = CLASS_ICON_FILES.get(class_name)
    if not filename:
        return ""
    path = ICON_DIR / filename
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _format_dt_dot(a: dict) -> str:
    """"YYYY-MM-DD HH:MM:SS" → "YYYY.MM.DD. HH:MM:SS" (요청된 표시 형식)."""
    raw = fmt_dt(a)
    date_part, sep, time_part = raw.partition(" ")
    y, _, rest = date_part.partition("-")
    m, _, d = rest.partition("-")
    if not (sep and d):
        return raw
    return f"{y}.{m}.{d}. {time_part}"


def _render_card(a: dict) -> str:
    class_name = a.get("class_name", "")
    icon_b64 = _icon_b64(class_name)
    confidence = float(a.get("score", a.get("confidence", 0)))
    dt_str = _format_dt_dot(a)

    is_person = class_name in PERSON_CLASSES
    border = f"3px solid {COLORS.get('사람', '#f85149')}" if is_person else "1px solid rgba(255,255,255,0.15)"
    bg = "rgba(248,81,73,0.10)" if is_person else "rgba(255,255,255,0.04)"

    icon_html = (
        f'<img src="data:image/png;base64,{icon_b64}" '
        f'style="width:34px;height:34px;object-fit:contain;flex-shrink:0;">'
        if icon_b64 else '<div style="width:34px;height:34px;flex-shrink:0;"></div>'
    )

    return f"""
<div style="display:flex;align-items:center;gap:0.7rem;padding:0.55rem 0.75rem;
            margin-bottom:0.5rem;border-radius:8px;border:{border};background-color:{bg};">
    {icon_html}
    <div style="flex:1;min-width:0;">
        <div style="font-weight:700;font-size:0.95rem;">{class_name}</div>
        <div style="font-size:0.8rem;color:#9aa4b2;white-space:nowrap;">
            {confidence:.1%} · {dt_str}
        </div>
    </div>
</div>
"""


def render_detection_panel() -> None:
    """우측 탐지 이력 패널. 이번 세션에서 새로 생긴 탐지만(워터마크 이후 id) 보여줍니다."""
    st.markdown("**탐지 이력**")

    ss = st.session_state
    watermark = ss.get("_session_start_max_id", 0)
    new_logs = [a for a in ss.get("detection_logs", []) if a.get("id", 0) > watermark]
    logs = sorted(new_logs, key=fmt_dt, reverse=True)[:MAX_ITEMS]

    with st.container(height=PANEL_HEIGHT_PX, border=False):
        if not logs:
            st.caption("최근 탐지 이력이 없습니다.")
        else:
            st.markdown("".join(_render_card(a) for a in logs), unsafe_allow_html=True)
