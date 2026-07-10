"""
ui/styles.py — 여러 화면이 공통으로 쓰는 CSS 스니펫 모음

카메라 카드 확대/이동처럼 특정 컴포넌트 전용 스타일은 그 컴포넌트 파일
(예: ui/camera/zoom.py)에 그대로 두고, 이 파일에는 상단 네비게이션처럼
"어디서든 재사용되는" 순수 CSS/인라인 스타일 문자열만 모아둡니다.
"""

# 버튼 라벨(예: "감지 기록")이 컬럼 폭보다 길 때 두 줄로 줄바꿈되는 것을 막는 CSS.
# Streamlit이 버튼 라벨을 내부적으로 <p> 태그로 렌더링하는 구조를 이용해 nowrap을 강제합니다.
BUTTON_NOWRAP_CSS = """
<style>
div[data-testid="stButton"] > button p {
    white-space: nowrap;
}
</style>
"""

# 상단 브랜드명("GOP 통합 감시 시스템") 스타일
BRAND_TITLE_STYLE = "font-size:1.3rem; font-weight:700; margin-bottom:0.8rem;"

# 실시간 시계 — '실시간 감시' 페이지 상단 헤더에 표시 (ui/camera/toolbar.py).
# 날짜는 작게, 오전/오후는 중간 크기, 시:분:초는 크고 굵게 표시해 강조 차등을 둠
CLOCK_DATE_STYLE = "font-size:0.85rem; color:gray;"
CLOCK_PERIOD_STYLE = "font-size:1.2rem; font-weight:500;"
CLOCK_TIME_STYLE = "font-size:1.6rem; font-weight:600;"
