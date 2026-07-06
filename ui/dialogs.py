"""
ui/dialogs.py — 전역 다이얼로그(팝업) 모음 및 트리거 처리

show_person_dialog(): 사람 탐지 상세를 화면 중앙에 크게 보여주는 다이얼로그.
handle_pending_popup(): session_state의 popup_queue/popup_id를 확인해 필요하면
                       위 다이얼로그를 실제로 띄웁니다. views/dashboard.py가
                       매 렌더마다 이 함수 하나만 호출하면 됩니다.
"""
import streamlit as st
import time
import s3_storage as s3
from config import POPUP_STALE_SECONDS

def open_popup(aid: int) -> None:
    """특정 로그의 팝업을 열도록 예약하고, 연 시각을 함께 기록합니다."""
    st.session_state["popup_id"] = aid
    st.session_state["_popup_opened_at"] = time.time()

@st.dialog("🚨 사람 탐지 상세", width="small")
def show_person_dialog(alert: dict) -> None:
    """특정 탐지 로그의 스냅샷 이미지와 상세 정보를 화면 중앙에 크게 띄워주는 다이얼로그(팝업)입니다.
    경보 패널의 '탐지 화면' 버튼 클릭 또는 신규 사람 탐지 시 자동으로 트리거됩니다."""
    ss = st.session_state
    snap = alert.get("snapshot")
    if snap is not None:
        # 이번 세션에서 직접 탐지된 경우: 메모리에 보관된 스냅샷을 그대로 사용 (S3 왕복 없이 빠름)
        st.image(snap, use_container_width=True)
    elif ss.get("S3_ENABLED") and alert.get("image_path"):
        # 앱 재시작 후 DB에서 복원된 로그: S3 객체 키로 임시 열람 URL을 발급해 표시
        url = s3.get_presigned_url(alert["image_path"])
        if url:
            st.image(url, use_container_width=True)
        else:
            st.info("S3 이미지를 불러올 수 없습니다.")
    else:
        st.info("표시할 스냅샷이 없습니다.")

    extra = f" · 누적 {alert['hit_frames']}프레임 추적" if alert["source"] == "영상" else ""
    st.markdown(f"**{alert['camera']}** — {alert['class_name']}: 신뢰도 {alert['confidence']:.0%}")
    st.caption(f"{alert['source']}{extra} · {alert['date']} {alert['time']}")

def handle_pending_popup() -> None:
    """대기열(popup_queue)에 항목이 있으면 popup_id로 지정하고, 유효한 로그를
    가리키면 show_person_dialog()를 띄웁니다."""
    ss = st.session_state

    # X로 이미 닫혔을 가능성이 높은 오래된 popup_id 정리 — 팝업을 강제로 닫는
    # 게 아니라, 이미 닫혔는데 남아있는 상태만 청소하는 용도입니다.
    opened_at = ss.get("_popup_opened_at")
    if ss.get("popup_id") is not None and opened_at is not None:
        if time.time() - opened_at > POPUP_STALE_SECONDS:
            ss["popup_id"] = None
            ss["_popup_opened_at"] = None

    if ss.get("popup_id") is None and ss.get("popup_queue"):
        open_popup(ss["popup_queue"].pop(0))

    popup_id = ss.get("popup_id")  # pop()이 아닌 get() — "닫기"를 누르기 전엔 재생 중 rerun에도 유지되어야 함
    if popup_id is not None:
        target = next((a for a in ss.detection_logs if a["id"] == popup_id), None)
        if target is not None:
            show_person_dialog(target)
        else:
            ss["popup_id"] = None  # 삭제 등으로 대상이 사라진 경우 안전하게 초기화
