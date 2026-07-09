"""
ui/camera/zoom.py — 카메라 화면 확대/이동(마우스 휠·드래그) 기능

집중 보기(카메라 1개를 크게 본 화면)에서만 활성화됩니다. Streamlit 위젯이 아니라
브라우저 DOM을 직접 조작하는 순수 HTML/JS라서, 영상 프레임이 계속 갱신되는
동안에도(fragment 재실행과 무관하게) 확대/이동 상태가 그대로 유지됩니다.
"""
import streamlit.components.v1 as components


# ------------------------------------------------------------------ #
# img_wrap 위치 기준 스타일 — ui/camera/card.py가 카메라별로 {cid}만 채워 사용.
# 오버레이 아이콘(⛶/↺) 및 상단 바 스타일은 ui/camera/card.py의
# TOPBAR_CSS_TEMPLATE으로 이동했습니다 — 이 파일은 확대/이동(zoom) 기능
# 자체에만 집중합니다.
#
# overflow:hidden이 중요합니다 — 상단 오버레이 바는 position:absolute라
# 카드 폭이 좁을 때(가로 스크롤 썸네일 등) 내용이 넘칠 수 있는데, 이 규칙이
# 없으면 넘친 부분이 옆 카드 위로 그대로 번져 보이는 문제가 생깁니다.
#
# container-type: inline-size — 이 카드 자신의 가로폭을 기준으로 하는
# "컨테이너 쿼리" 단위(cqw)의 기준점을 여기 선언합니다. 오버레이 바
# (TOPBAR_CSS_TEMPLATE)가 이 기준으로 폰트/패딩 크기를 정해서, 카드 폭이
# 달라지면(그리드 칸 개수, 가로 스크롤 카드 등) 배지 크기도 함께 비례해서
# 커지거나 작아집니다 — 고정 px였을 때 좁은 카드에서 버튼끼리 겹치던
# 문제의 근본 해결책입니다.
# ------------------------------------------------------------------ #
IMG_WRAP_CSS_TEMPLATE = """
<style>
div[class*="st-key-img_wrap_{cid}"] {{
    position: relative;
    overflow: hidden;
    border-radius: 4px;
    container-type: inline-size;
}}
</style>
"""


def inject_live_zoom_script(cid: str) -> None:
    """영상 영역(img_wrap_{cid})에 마우스 휠 확대/축소, 드래그 이동 기능을 심습니다."""
    components.html(f"""
    <script>
    (function() {{
        const doc = window.parent.document;  // iframe 밖 실제 페이지 DOM에 접근
        const key = "{cid}";

        const trySetup = () => {{
            const wrap = doc.querySelector('div[class*="st-key-img_wrap_' + key + '"]');
            const img = wrap ? wrap.querySelector('img') : null;
            if (!wrap || !img) return setTimeout(trySetup, 200);

            // 이전에 붙여둔 리스너가 있으면 먼저 제거 (재호출 시 중복 등록 방지)
            if (wrap._zoomMouseDown) wrap.removeEventListener('mousedown', wrap._zoomMouseDown);
            if (wrap._zoomWheel) wrap.removeEventListener('wheel', wrap._zoomWheel);
            if (doc['_zoomMouseMove_' + key]) doc.removeEventListener('mousemove', doc['_zoomMouseMove_' + key]);
            if (doc['_zoomMouseUp_' + key]) doc.removeEventListener('mouseup', doc['_zoomMouseUp_' + key]);

            wrap.style.overflow = "hidden";
            wrap.style.cursor = "grab";

            let scale = 1, panX = 0, panY = 0;
            let dragging = false, startX = 0, startY = 0;

            function apply() {{
                img.style.transformOrigin = "0 0";
                img.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{scale}})`;
            }}

            const onWheel = (e) => {{
                e.preventDefault();
                const rect = wrap.getBoundingClientRect();
                const x = e.clientX - rect.left, y = e.clientY - rect.top;
                const factor = e.deltaY < 0 ? 1.1 : 0.9;
                const prev = scale;
                scale = Math.min(Math.max(scale * factor, 1), 6);
                const actual = scale / prev;
                panX = x - (x - panX) * actual;
                panY = y - (y - panY) * actual;
                apply();
            }};

            const onMouseDown = (e) => {{
                dragging = true;
                startX = e.clientX - panX;
                startY = e.clientY - panY;
                wrap.style.cursor = "grabbing";
                e.preventDefault();  // 드래그 중 이미지가 브라우저 기본 동작으로 끌려가는 것 방지
            }};
            const onMouseMove = (e) => {{
                if (!dragging) return;
                panX = e.clientX - startX;
                panY = e.clientY - startY;
                apply();
            }};
            const onMouseUp = () => {{
                dragging = false;
                wrap.style.cursor = "grab";
            }};

            wrap.addEventListener('wheel', onWheel, {{ passive: false }});
            wrap.addEventListener('mousedown', onMouseDown);
            doc.addEventListener('mousemove', onMouseMove);
            doc.addEventListener('mouseup', onMouseUp);

            // 다음 재설치 시 정확히 이 리스너들을 제거할 수 있도록 참조를 저장
            wrap._zoomMouseDown = onMouseDown;
            wrap._zoomWheel = onWheel;
            doc['_zoomMouseMove_' + key] = onMouseMove;
            doc['_zoomMouseUp_' + key] = onMouseUp;
        }};
        trySetup();
    }})();
    </script>
    """, height=0)
