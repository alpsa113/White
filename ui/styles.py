"""ui/styles.py — 여러 화면이 공통으로 쓰는 CSS 스니펫 모음."""

# 버튼 라벨 줄바꿈 방지
BUTTON_NOWRAP_CSS = """
<style>
div[data-testid="stButton"] > button p {
    white-space: nowrap;
}
</style>
"""

# 헤더 시계 스타일 (ui/camera/toolbar.py)
CLOCK_DATE_STYLE = "font-size:0.85rem; color:gray;"
CLOCK_PERIOD_STYLE = "font-size:1.2rem; font-weight:500;"
CLOCK_TIME_STYLE = "font-size:1.6rem; font-weight:600;"


# ── 페이지 공통 여백/스크롤 (views/settings.py, views/logs.py) ──────────────
# block-container 기본 상/좌/우 여백을 줄입니다.
PAGE_PADDING_CSS = """
<style>
[data-testid="stMain"] .block-container {
    padding-top: 0.5rem;
    padding-left: 1rem;
    padding-right: 1rem;
}
</style>
"""


# ── 로그인 화면 (views/login.py) ────────────────────────────────────────
# HEIMDALL 배경 이미지 + 반투명 로그인 패널. {bg_b64}는 배경 이미지의 base64 문자열입니다.
LOGIN_BACKGROUND_CSS_TEMPLATE = """
<style>
html, body {{
    overflow: hidden;
}}
.stApp {{
    background-color: #030303;
    background-image: url("data:image/png;base64,{bg_b64}");
    background-size: 100% auto;
    background-repeat: no-repeat;
    background-position: top center;
    height: 100vh;
    overflow: hidden;
}}
[data-testid="stAppViewContainer"], [data-testid="stMain"] {{
    height: 100vh;
    overflow: hidden;
}}
[data-testid="stHeader"] {{
    background: rgba(0,0,0,0);
}}
.st-key-login_panel {{
    position: fixed;
    top: 40vh;
    left: 50%;
    transform: translate(-50%, 0);
    width: min(92vw, 30rem);
    max-height: 54vh;
    overflow-y: auto;
    background: rgba(10, 10, 10, 0.55);
    border: 1px solid rgba(201, 162, 39, 0.45);
    border-radius: 10px;
    padding: clamp(1.2rem, 2.5vh, 2.5rem) clamp(1.2rem, 3vw, 2.5rem) 1.5rem;
    backdrop-filter: blur(6px);
    box-shadow: 0 0 30px rgba(0,0,0,0.4);
    z-index: 10;
}}
.st-key-login_panel label {{
    color: #e8e2d0 !important;
}}
</style>
"""


# ── HEIMDALL 다크 테마 — 사이드바 (ui/layout.py) ──────────────────────────
# 로고는 실제 <img> 요소(ui/layout.py에서 렌더링)라 사이드바 폭이 달라져도 항상
# 정확한 비율로 나오고, 바로 아래에 버튼이 이어집니다. 초소 야경(sidebar_scene.png)은
# 하단 고정 배경, 그 사이는 어두운 단색으로 자연스럽게 이어집니다.
# admin·관리자/로그아웃(sidebar_footer)은 사이드바 맨 아래로 고정합니다 — Streamlit이
# st.container(key=...)마다 stLayoutWrapper를 한 겹 더 씌우기 때문에, 그 래퍼까지
# 함께 flex-column으로 늘려줘야 margin-top:auto가 실제로 동작합니다.
SIDEBAR_THEME_CSS_TEMPLATE = """
<style>
div[data-testid="stSidebarContent"] {{
    background-color: #05070a;
    background-image: url("data:image/png;base64,{scene_b64}");
    background-repeat: no-repeat;
    background-position: bottom center;
    background-size: 100% auto;
    display: flex;
    flex-direction: column;
    height: 100%;
    box-sizing: border-box;
    padding-bottom: 0;
}}
div[data-testid="stSidebarUserContent"],
div[data-testid="stSidebarUserContent"] > div,
div[data-testid="stSidebarUserContent"] > div > div[data-testid="stVerticalBlock"] {{
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
}}
div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-sidebar_footer"]) {{
    margin-top: auto;
    padding-top: 1.5rem;
}}
div[class*="st-key-sidebar_logo"] img {{
    display: block;
    width: 100%;
    margin-bottom: 0.5rem;
}}
div[data-testid="stSidebarContent"] div[data-testid="stButton"] > button {{
    width: 100%;
    justify-content: flex-start !important;
    background-color: rgba(255, 255, 255, 0.02) !important;
    border: 1px solid rgba(148, 163, 184, 0.18) !important;
    color: #cbd5e1 !important;
    font-weight: 500 !important;
}}
div[data-testid="stSidebarContent"] div[data-testid="stButton"] > button:hover {{
    border-color: rgba(34, 211, 238, 0.55) !important;
    color: #ffffff !important;
}}
div[data-testid="stSidebarContent"] div[data-testid="stButton"] > button[kind="primary"] {{
    background-color: rgba(34, 211, 238, 0.12) !important;
    border: 1px solid rgba(34, 211, 238, 0.65) !important;
    color: #67e8f9 !important;
    box-shadow: inset 3px 0 0 #22d3ee;
}}
div[class*="st-key-sidebar_account"] {{
    color: #64748b !important;
    font-size: 0.8rem;
    margin: 0.4rem 0 0.8rem 0.2rem;
}}
</style>
"""

# ── HEIMDALL 다크 테마 — 전역 배경 (app.py 로그인 이후 페이지 전체) ────────
GLOBAL_APP_BG_CSS = """
<style>
.stApp {
    background:
        radial-gradient(ellipse 60% 40% at 15% 0%, rgba(34, 211, 238, 0.07), transparent 60%),
        radial-gradient(ellipse 50% 50% at 100% 100%, rgba(34, 211, 238, 0.05), transparent 60%),
        #05070a;
}
[data-testid="stHeader"] {
    background: transparent;
    height: 1.5rem;
}
</style>
"""


# ── 관제 대시보드 (views/dashboard.py) ───────────────────────────────────
# 페이지 자체는 스크롤되지 않고, 콘텐츠는 block-container 안에서만 스크롤됩니다.
DASHBOARD_FIXED_PAGE_CSS = """
<style>
html, body {
    overflow: hidden;
}
[data-testid="stAppViewContainer"], [data-testid="stMain"] {
    height: 100vh;
    overflow: hidden;
}
[data-testid="stMain"] .block-container {
    padding-top: 0.5rem;
    padding-bottom: 1rem;
    padding-left: 1rem;
    padding-right: 1rem;
    height: 100vh;
    overflow-y: auto;
}
</style>
"""

# 우측 패널(초소 위치+탐지 이력)이 좌측 카메라 화면과 같은 높이만큼만 채우도록 합니다.
# minimap_section은 자기 크기를 유지하고, 탐지 이력이 남는 공간을 flex로 채웁니다.
DASHBOARD_PANEL_COL_CSS = """
<style>
div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-panel_col_wrap"]) {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
    height: 100%;
}
div[class*="st-key-panel_col_wrap"] {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
}
div[class*="st-key-minimap_section"] {
    flex: 0 0 auto;
    gap: 0.15rem !important;
}
</style>
"""


# ── 탐지 이력 패널 (ui/camera/detection_panel.py) ─────────────────────────
# 목록(detection_panel_list)만 남는 세로 공간을 채우고, 넘치면 그 안에서만
# 스크롤됩니다. 제목은 고정 크기, 래퍼 두 겹 모두 flex-column으로 이어줍니다.
DETECTION_PANEL_CSS = """
<style>
div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-detection_panel_wrap"]),
div[class*="st-key-detection_panel_wrap"] {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
}
div[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-detection_panel_list"]),
div[class*="st-key-detection_panel_list"] {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
}
div[class*="st-key-detection_panel_list"] {
    overflow-y: auto;
}
</style>
"""


# ── 카메라 카드 (ui/camera/card.py) ─────────────────────────────────────
# 카드 상단 툴바 CSS — [카메라 이름] .......... [EO][TIR][▦/⛶][↺]
# 컨테이너 쿼리(cqw)로 카드 폭에 비례해 배지 크기가 커지고 작아집니다.
TOPBAR_CSS_TEMPLATE = """
<style>
div[class*="st-key-topbar_{cid}"] {{
    width: 100% !important;
    padding: 0.3cqw 2cqw;
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center;
    justify-content: space-between;
    gap: 1.5cqw;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) {{
    flex: 1 1 0;
    min-width: 0;
    overflow-x: hidden;
    overflow-y: visible;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) button,
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) p {{
    display: inline-block !important;
    width: auto !important;
    max-width: 100% !important;
    min-width: 0 !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
    overflow-y: visible !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(2) {{
    flex: 0 0 auto !important;
    width: auto !important;
    max-width: none !important;
}}
div[class*="st-key-topbar_{cid}"] p {{
    margin: 0 !important;
    padding: clamp(1px, 0.8cqw, 5px) clamp(4px, 2cqw, 10px);
    font-size: clamp(0.55rem, 3cqw, 0.85rem);
    line-height: 1.4;
    display: inline-block;
    white-space: nowrap;
}}
div[class*="st-key-topbar_{cid}"] button {{
    padding: clamp(1px, 0.8cqw, 5px) clamp(4px, 2cqw, 10px) !important;
    min-height: 0 !important;
    height: auto !important;
    white-space: nowrap !important;
    flex-shrink: 0;
}}
div[class*="st-key-topbar_{cid}"] button p {{
    font-size: clamp(0.55rem, 3cqw, 0.85rem) !important;
    margin: 0 !important;
    white-space: nowrap !important;
}}
div[class*="st-key-controls_{cid}"],
div[data-testid="stHorizontalBlock"][class*="st-key-controls_{cid}"] {{
    display: flex !important;
    flex-wrap: nowrap !important;
    flex: 0 0 auto !important;
    width: auto !important;
    max-width: none !important;
    align-items: center;
    gap: clamp(3px, 1.2cqw, 8px);
}}
div[class*="st-key-channel_toggle_{cid}"],
div[class*="st-key-view_toggle_{cid}"],
div[data-testid="stHorizontalBlock"][class*="st-key-channel_toggle_{cid}"],
div[data-testid="stHorizontalBlock"][class*="st-key-view_toggle_{cid}"] {{
    display: flex !important;
    flex-wrap: nowrap !important;
    flex: 0 0 auto !important;
    width: auto !important;
    max-width: none !important;
    gap: clamp(2px, 1cqw, 6px);
}}
div[class*="st-key-controls_{cid}"] > div[data-testid="stLayoutWrapper"] {{
    width: auto !important;
    max-width: none !important;
    flex: 0 0 auto !important;
}}
</style>
"""

# 카드 여백 최소화 + cqw 기준점(container-type) 선언
CARD_CSS_TEMPLATE = """
<style>
div[class*="st-key-card_{cid}"] {{
    container-type: inline-size;
}}
div[class*="st-key-card_{cid}"],
div[class*="st-key-card_{cid}"] [data-testid="stVerticalBlockBorderWrapper"],
div[class*="st-key-card_{cid}"] [data-testid="stVerticalBlock"] {{
    padding: 0.35rem !important;
    gap: 0 !important;
    margin: 0 !important;
}}
div[class*="st-key-card_{cid}"] [data-testid="stElementContainer"],
div[class*="st-key-card_{cid}"] [data-testid="stLayoutWrapper"],
div[class*="st-key-card_{cid}"] [data-testid="stMarkdownContainer"] {{
    margin: 0 !important;
    padding: 0 !important;
}}
</style>
"""

# img_wrap 위치 기준 스타일 (ui/camera/zoom.py가 마우스 휠/드래그 확대에도 사용)
IMG_WRAP_CSS_TEMPLATE = """
<style>
div[class*="st-key-img_wrap_{cid}"] {{
    position: relative;
    overflow: hidden;
    border-radius: 4px;
}}
</style>
"""


# ── 초소 지도 / 마커 (ui/outposts/marker_overlay.py, viewer.py) ──────────
# 마커 점멸 애니메이션 + 지도 래퍼(마커 절대좌표 기준점) 선언. {wrap_key}는 MAP_WRAP_KEY.
MAP_BLINK_CSS_TEMPLATE = """
<style>
@keyframes outpost-marker-blink {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.15; }} }}
div[class*="st-key-{wrap_key}"] {{ position: relative; }}
</style>
"""

# 지도 이미지 래퍼 — 원본 비율 유지 + 마커 절대좌표 기준점
MAP_WRAP_CSS_TEMPLATE = """
<style>
div[class*="st-key-{wrap_key}"] {{
    position: relative;
    width: 100%;
    aspect-ratio: {img_w} / {img_h};
    overflow: hidden;
    border-radius: 4px;
    container-type: inline-size;
}}
div[class*="st-key-{wrap_key}"] img {{
    width: 100% !important;
    height: 100% !important;
    object-fit: contain;
    display: block;
}}
</style>
"""

# 마커+정지 아이콘+체크 배지의 절대 위치 및 상태별(점멸) 스타일.
# 크기는 지도 폭 기준 cqw로 비례합니다. {color}/{blink_rule}은 점멸 여부에 따라 채워집니다.
MARKER_CSS_TEMPLATE = """
<style>
div[class*="st-key-outpost_marker_{cid}"] {{
    position: absolute;
    left: {x_pct:.3f}%;
    top: {y_pct:.3f}%;
    transform: translate(-50%, -50%);
    z-index: 10;
    width: auto !important;
}}
div[class*="st-key-outpost_marker_{cid}"] button {{
    width: clamp(12px, 6.5cqw, 22px); height: clamp(12px, 6.5cqw, 22px);
    min-height: 0 !important;
    box-sizing: border-box !important;
    padding: 0 !important; border-radius: 50% !important;
    display: flex !important; align-items: center; justify-content: center;
    background-color: {color} !important; color: white !important;
    border: clamp(1px, 0.6cqw, 2px) solid white !important;
    font-size: clamp(7px, 3.4cqw, 13px); font-weight: 700; line-height: 1;
    {blink_rule}
}}
div[class*="st-key-outpost_stop_{cid}"] {{
    position: absolute;
    left: calc({x_pct:.3f}% + 4.5cqw);
    top: calc({y_pct:.3f}% - 4.5cqw);
    transform: translate(-50%, -50%);
    z-index: 11;
    width: auto !important;
}}
div[class*="st-key-outpost_stop_{cid}"] button {{
    width: clamp(8px, 4.2cqw, 15px); height: clamp(8px, 4.2cqw, 15px);
    min-height: 0 !important;
    box-sizing: border-box !important;
    padding: 0 !important; border-radius: 50% !important;
    display: flex !important; align-items: center; justify-content: center;
    background-color: #21262d !important; color: white !important;
    border: 1px solid white !important;
    font-size: clamp(5px, 2.5cqw, 10px); line-height: 1;
}}
div[class*="st-key-outpost_check_{cid}"] {{
    position: absolute;
    left: {x_pct:.3f}%;
    top: calc({y_pct:.3f}% - 4.2cqw);
    transform: translate(-50%, -50%);
    z-index: 12;
    width: clamp(16px, 8.5cqw, 28px);
    height: clamp(16px, 8.5cqw, 28px);
    pointer-events: none;
}}
div[class*="st-key-outpost_check_{cid}"] * {{
    margin: 0 !important;
    padding: 0 !important;
    height: 100% !important;
    width: 100% !important;
}}
</style>
"""

# "현재 화면에 표시 중" 체크 배지 모양 — 짧은 아래쪽 획 + 긴 위쪽 획 폴리라인
# (설정 페이지 지도 미리보기의 PIL 체크와 같은 비율, 반지름 1 기준 상대 좌표).
_CHECK_MARK_POINTS = "-0.7,0 -0.15,0.55 0.85,-0.65"

CHECK_MARK_SVG = f"""
<svg viewBox="-1 -1 2 2" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%;overflow:visible;">
    <polyline points="{_CHECK_MARK_POINTS}" fill="none" stroke="white"
              stroke-width="0.46" stroke-linecap="round" stroke-linejoin="round" />
    <polyline points="{_CHECK_MARK_POINTS}" fill="none" stroke="#22c55e"
              stroke-width="0.30" stroke-linecap="round" stroke-linejoin="round" />
</svg>
"""
