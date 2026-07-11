"""ui/camera/zoom.py — 카메라 화면 확대/이동(마우스 휠·드래그) 기능. 집중 보기에서만 활성화됩니다."""
import streamlit.components.v1 as components


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


def inject_reset_zoom_script(cid: str) -> None:
    """확대/이동 상태를 초기화합니다(이미지가 아직 DOM에 없으면 나타날 때까지 재시도)."""
    components.html(f"""
    <script>
    (function() {{
        const doc = window.parent.document;
        const key = "{cid}";
        const tryReset = () => {{
            const wrap = doc.querySelector('div[class*="st-key-img_wrap_' + key + '"]');
            const img = wrap ? wrap.querySelector('img') : null;
            if (!img) return setTimeout(tryReset, 100);
            img.style.transform = 'none';
        }};
        tryReset();
    }})();
    </script>
    """, height=0)
