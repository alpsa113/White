"""app.py — GOP 통합 감시 시스템 메인 엔트리포인트. 페이지 설정, 로그인 게이트, 사이드바, 페이지 라우팅만 담당합니다."""
import streamlit as st

from state import init_session_state
from ui.layout import render_sidebar
from views import login, dashboard, logs, settings
from services.camera_registry import get_active_cameras
from services.playback import run_playback_loop

st.set_page_config(page_title="GOP 통합 감시 시스템", layout="wide", initial_sidebar_state="expanded")

init_session_state()

ss = st.session_state

if not ss.authenticated:
    login.render()
    st.stop()

render_sidebar()

page_selection = ss.current_page

# 카메라 목록/재생 상태는 페이지와 무관하게 항상 계산(탐지가 끊기지 않도록)
cameras = get_active_cameras()
video_slots = {}

if page_selection == "관제 대시보드":
    video_slots = dashboard.render(cameras)
elif page_selection == "감지 기록":
    logs.render()
elif page_selection == "설정":
    settings.render()


def _is_active_channel_playing(cam):
    channel = ss.get(f"active_channel_{cam['id']}", "eo")
    return ss.get(f"playing_{cam['id']}_{channel}")


# 카메라마다 현재 선택된 채널만 재생 대상에 포함(1대당 최대 1채널 디코딩)
active_cams = [cam for cam in cameras if _is_active_channel_playing(cam)]

if active_cams:
    run_playback_loop(active_cams, video_slots)
    st.rerun()
