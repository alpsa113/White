"""
app.py — GOP 통합 감시 시스템 메인 엔트리포인트

역할: 페이지 설정, session_state 초기화, 상단 레이아웃(사이드바/네비게이션)
렌더링, 페이지 라우팅만 담당합니다. 세부 UI/로직은 ui/, services/, views/
모듈에 위임되어 이 파일은 가볍게 유지됩니다.

실행 방법:
    streamlit run app.py
"""
import streamlit as st

from state import init_session_state
from ui.layout import render_sidebar, render_topnav
from views import dashboard, logs

st.set_page_config(page_title="GOP 통합 감시 시스템", layout="wide")

init_session_state()
render_sidebar()
render_topnav()

page_selection = st.session_state.current_page

if page_selection == "관제 대시보드":
    dashboard.render()
elif page_selection == "탐지 데이터 로그":
    logs.render()
