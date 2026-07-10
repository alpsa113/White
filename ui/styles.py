"""ui/styles.py — 여러 화면이 공통으로 쓰는 CSS 스니펫 모음."""

# 버튼 라벨 줄바꿈 방지
BUTTON_NOWRAP_CSS = """
<style>
div[data-testid="stButton"] > button p {
    white-space: nowrap;
}
</style>
"""

# 상단 브랜드명 스타일
BRAND_TITLE_STYLE = "font-size:1.3rem; font-weight:700; margin-bottom:0.8rem;"

# 헤더 시계 스타일 (ui/camera/toolbar.py)
CLOCK_DATE_STYLE = "font-size:0.85rem; color:gray;"
CLOCK_PERIOD_STYLE = "font-size:1.2rem; font-weight:500;"
CLOCK_TIME_STYLE = "font-size:1.6rem; font-weight:600;"
