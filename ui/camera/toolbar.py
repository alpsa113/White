"""
ui/camera/toolbar.py — '실시간 감시' 페이지 상단 헤더(날짜+시각) + 구역 전환 상태 동기화

과거에는 "라이브 카메라 피드" 제목과 "구역 선택" 드롭다운이 사이드바에
있었지만, 이제 화면 전환(그리드 ↔ 특정 카메라 스포트라이트)은 각 카메라
카드 상단 오버레이 바의 버튼(ui/camera/card.py의 ⛶/▦/↺)으로 직접 이뤄지므로
드롭다운이 필요 없어졌습니다. 카메라 개수도 더 이상 이 화면에서 조절하지
않고, 설정 페이지의 초소 마킹 개수로 자동 결정됩니다. 그래서 이 파일에
남은 위젯은 실시간 시계(날짜+시각) 하나뿐입니다 — 예전에는 사이드바에
있었지만, 이제 '실시간 감시' 페이지 본문 상단(헤더 행 좌측 정렬)에
표시됩니다. 지도 미니맵은 더 이상 이 헤더 옆이 아니라, 맨 오른쪽 컬럼에서
객체 탐지 이력 패널 위에 표시됩니다(views/dashboard.py가
ui.outposts.viewer.render_map을 호출).
"""
from datetime import datetime

import streamlit as st

from services.playback import reset_cam_state
from ui.styles import CLOCK_DATE_STYLE, CLOCK_PERIOD_STYLE, CLOCK_TIME_STYLE

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def consume_pending_camera_switch(cameras: list[dict]) -> None:
    """예약된 구역 전환 요청(_pending_selected_cam)을 카드가 그려지기 전에
    반영합니다. 사람 탐지 시 자동 스포트라이트 전환(services/playback.py)과
    카드의 ⛶ 버튼(수동 전환)이 공통으로 이 예약 큐를 사용합니다.

    카메라마다 "배경 채널" 하나만 항상 재생되고, 스포트라이트에서 켠 보조
    채널(2분할의 두 번째 화면)은 그 카메라를 실제로 보고 있을 때만
    재생됩니다(services/camera_registry._sync_preset_media, ui/camera/
    card.py) — 그래서 다른 카메라로 전환하기 직전, 지금 보고 있던 카메라에
    보조 채널이 켜져 있었다면 여기서 재생을 멈추고 리소스를 반납합니다.
    ui/camera/card.py의 ▦(전체 그리드로 돌아가기) 버튼은 스스로 정리하지만,
    ⛶ 버튼이나 사람 탐지로 인한 자동 전환은 모두 이 함수를 거치므로
    여기가 놓치지 않고 정리할 수 있는 지점입니다."""
    ss = st.session_state
    pending = ss.pop("_pending_selected_cam", None)
    if pending is None:
        return

    prev = ss.get("selected_cam")
    if prev not in (None, "전체 구역", pending):
        prev_cam = next((c for c in cameras if c["name"] == prev), None)
        if prev_cam:
            secondary = ss.pop(f"active_channel_secondary_{prev_cam['id']}", None)
            if secondary:
                reset_cam_state(prev_cam["id"], state_suffix=f"_{secondary}")

    ss["selected_cam"] = pending


@st.fragment(run_every=1)
def render_header_clock() -> None:
    """'실시간 감시' 페이지 헤더 행 좌측에 표시되는 날짜+시각 — 1초마다
    이 부분만 독립적으로 재실행되어 갱신됩니다 (fragment 덕분에 카메라
    카드 등 나머지 화면은 영향받지 않음)."""
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
