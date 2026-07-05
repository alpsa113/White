"""
app.py — GOP 통합 감시 시스템 메인 엔트리포인트

역할: 페이지 설정, session_state 초기화, 상단 레이아웃(브랜드명/네비게이션/상태뱃지/시계)
렌더링, 페이지 라우팅만 담당합니다. 실제 화면 구성과 로직은 ui/, services/, views/
모듈에 위임되어 있어 이 파일은 항상 가볍게 유지됩니다.

실행 방법:
    streamlit run app.py
"""
import streamlit as st

from state import init_session_state
from ui.layout import render_topnav
from views import dashboard, logs, settings

# wide 레이아웃 사용 — 카메라 그리드와 로그 표가 넓은 화면을 최대한 활용하도록 설정
st.set_page_config(page_title="GOP 통합 감시 시스템", layout="wide")

# session_state 기본값 채우기 + RDS/S3 연결 확인 (스크립트가 재실행될 때마다 매번 실행됨)
init_session_state()

# 브랜드명 + 페이지 전환 버튼(실시간 감시/관리자 로그/설정) + 상태뱃지 + 실시간 시계
# → 어떤 페이지를 보고 있든 항상 동일하게 상단에 표시됩니다.
render_topnav()

page_selection = st.session_state.current_page

# 현재 선택된 페이지의 render()만 호출 — 나머지 페이지 코드는 실행되지 않음
if page_selection == "관제 대시보드":
    dashboard.render()
elif page_selection == "탐지 데이터 로그":
    logs.render()
elif page_selection == "설정":
    settings.render()
