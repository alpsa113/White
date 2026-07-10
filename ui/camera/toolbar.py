"""ui/camera/toolbar.py — '실시간 감시' 페이지 상단 헤더(날짜+시각) + 구역 전환 상태 동기화."""
from datetime import datetime

import streamlit as st

from ui.styles import CLOCK_DATE_STYLE, CLOCK_PERIOD_STYLE, CLOCK_TIME_STYLE

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def consume_pending_camera_switch() -> None:
    """예약된 구역 전환 요청(_pending_selected_cam)을 카드가 그려지기 전에 반영합니다."""
    ss = st.session_state
    pending = ss.pop("_pending_selected_cam", None)
    if pending is not None:
        ss["selected_cam"] = pending


@st.fragment(run_every=1)
def render_header_clock() -> None:
    """헤더 좌측의 날짜+시각을 1초마다 독립적으로 갱신합니다."""
    now = datetime.now()
    weekday = _WEEKDAY_KO[now.weekday()]
    st.markdown(
        f"<div style='text-align:left; line-height:1.5;'>"
        f"<div style='{CLOCK_DATE_STYLE}'>{now.strftime('%Y.%m.%d')} ({weekday})</div>"
        f"<span style='{CLOCK_PERIOD_STYLE}'>{'오전' if now.hour < 12 else '오후'}</span> "
        f"<span style='{CLOCK_TIME_STYLE}'>{now.strftime('%I:%M:%S')}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
