"""
ui/camera_card.py — 카메라 카드(업로드+영상 슬롯) 렌더링 및 사람 탐지 팝업

'전체 구역' 그리드와 '특정 카메라' 집중 보기가 동일한 카드 UI를 공유하도록
render_camera_card() 하나로 구현해두었고, 그리드/집중보기 함수는 이 카드를
어떤 배치로 몇 번 반복할지만 결정합니다.
"""
import tempfile

import streamlit as st
from streamlit_sortables import sort_items
from streamlit_cropper import st_cropper
from PIL import Image

import s3_storage as s3
from config import IMAGE_EXTS, VIDEO_EXTS
from services.video_tracking import reset_cam_state, process_frame, HAS_CV2
from services.detection import draw_boxes

try:
    import cv2
except ImportError:
    cv2 = None

@st.dialog("🔍 영역 확대", width="large")
def show_zoom_dialog(cam_name: str, image: Image.Image) -> None:
    """정지된 프레임 위에서 사용자가 드래그로 선택한 영역만 잘라내어 확대 표시합니다.
    실시간으로 계속 갱신되는 화면(재생 중인 영상)에는 적용하지 않습니다 — 커스텀
    컴포넌트가 매 프레임 재생성되면 불안정해질 수 있기 때문입니다."""
    st.caption(f"{cam_name} — 마우스로 드래그해서 확대할 영역을 선택하세요.")

    col_select, col_zoom = st.columns(2)
    with col_select:
        st.markdown("**드래그로 영역 선택**")
        cropped = st_cropper(
            image,
            realtime_update=True,
            box_color="#f85149",
            aspect_ratio=None,
            return_type="image",
            should_resize_image=True,  # 미리보기는 최대 700px로 자동 축소, 자르기는 원본 해상도 기준
        )
    with col_zoom:
        st.markdown("**확대 결과**")
        st.image(cropped, use_container_width=True)

    if st.button("닫기", use_container_width=True):
        st.rerun()

def render_camera_card(cam: dict, video_slots: dict, progress_slots: dict) -> None:
    """카메라 1대에 대한 카드(제목 + 업로드 팝오버 + 영상 슬롯)를 렌더링합니다.
    video_slots/progress_slots 딕셔너리에 이 카메라의 st.empty() 자리를 등록해두면,
    이후 재생 루프(run_playback_loop)가 그 자리를 찾아 프레임을 계속 덮어씁니다."""
    ss = st.session_state
    cid = cam["id"]

    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute"):
            # 그리드('전체 구역') 상태에서만 제목을 클릭해 확대 전환할 수 있게 합니다.
            # tertiary 버튼  CSS로 일반 볼드 텍스트처럼 보이게 스타일링했지만, 실제로는
            # Streamlit 버튼이라 URL 변경 없이 구역 선택 드롭다운과 동일하게 매끄럽게 전환됩니다.
            if st.session_state.get("selected_cam") == "전체 구역":
                if st.button(f"**{cam['name']}**", key=f"title_btn_{cid}", type="tertiary"):
                    st.session_state["_pending_selected_cam"] = cam["name"]
                    st.rerun()
            else:
                st.markdown(f"**{cam['name']}**")
            # ⚙️ 팝오버 안에 업로드/초기화 기능을 숨겨 카드 자체는 항상 깔끔하게 유지
            with st.popover("⚙️"):
                uploaded = st.file_uploader(
                    "미디어 업로드", type=list(IMAGE_EXTS + VIDEO_EXTS), key=f"upload_{cid}"
                )
                if st.button("비우기 🗑️", key=f"clear_btn_{cid}", use_container_width=True):
                    reset_cam_state(cid)
                    st.rerun()

        # 영상/이미지가 그려질 자리를 미리 확보 — 재생 루프가 이 슬롯을 찾아 프레임을 갱신함
        video_slots[cid] = st.empty()
        progress_slots[cid] = st.empty()

        if uploaded is not None:
            # 파일명+크기 조합으로 "새로 업로드된 파일인지"를 판별 — 동일 파일이면 재처리하지 않음
            fp = (uploaded.name, uploaded.size)
            if ss.get(f"fp_{cid}") != fp:
                reset_cam_state(cid)
                ss[f"fp_{cid}"] = fp
                ext = uploaded.name.rsplit(".", 1)[-1].lower()

                if ext in VIDEO_EXTS:
                    if not HAS_CV2:
                        st.error("opencv-python 필요")
                    else:
                        # cv2.VideoCapture는 파일 경로가 필요하므로, 업로드된 바이트를
                        # 임시파일로 먼저 저장한 뒤 그 경로를 열어 재생을 시작합니다.
                        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
                            tmp.write(uploaded.getvalue())
                            ss[f"tmp_path_{cid}"] = tmp.name

                        cap = cv2.VideoCapture(ss[f"tmp_path_{cid}"])
                        ss[f"cap_{cid}"] = cap
                        ss[f"total_frames_{cid}"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        ss[f"cursor_{cid}"] = 0
                        ss[f"playing_{cid}"] = True
                        ss[f"finished_{cid}"] = False
                        st.rerun()  # 재생 상태를 즉시 반영 → 이후 run_playback_loop가 이어받아 프레임을 읽음
                else:
                    # 이미지 업로드는 영상과 달리 1회성 처리 — 즉시 추론하고 결과 이미지를 저장해둠
                    image = Image.open(uploaded).convert("RGB")
                    dets, _ = process_frame(cam, image, "이미지", single=True)
                    ss[f"result_{cid}"] = draw_boxes(image, dets)
                    st.rerun()

        # 카드 하단 상태 표시: 업로드 전 안내 → 결과 이미지 → (영상이면) 완료 표시
        if ss.get(f"fp_{cid}") is None:
            video_slots[cid].info("⚙️ 아이콘을 눌러 업로드")
        elif not ss.get(f"playing_{cid}"):
            result = ss.get(f"result_{cid}")
            if result:
                video_slots[cid].image(result, use_container_width=True)
                if st.button("🔍 영역 확대", key=f"zoom_btn_{cid}", use_container_width=True):
                    show_zoom_dialog(cam["name"], result)
                # cap_{cid}가 아직 열려 있고, 아직 끝까지 재생되지 않았다면 '일시정지 후' 상태 → 재개 가능
                cap = ss.get(f"cap_{cid}")
                if cap is not None and cap.isOpened() and not ss.get(f"finished_{cid}"):
                    if st.button("▶️ 재개", key=f"resume_btn_{cid}", use_container_width=True):
                        ss[f"playing_{cid}"] = True
                        st.rerun()
            if ss.get(f"finished_{cid}"):
                st.caption("✅ 영상 분석 완료")
        else:
            # 재생 중일 때는 확대 대신 '일시정지' 버튼만 노출 — 정지해야 그 프레임을 확대할 수 있음
            if st.button("⏸️ 일시정지", key=f"pause_btn_{cid}", use_container_width=True):
                ss[f"playing_{cid}"] = False
                st.rerun()


def render_camera_grid(cameras: list[dict], video_slots: dict, progress_slots: dict, cols_per_row: int) -> None:
    """cameras 목록을 cols_per_row(한 줄당 카메라 수)에 맞춰 그리드 형태로 렌더링합니다.
    카메라 개수가 cols_per_row로 나누어 떨어지지 않아도 마지막 줄은 남은 개수만큼만 채웁니다."""
    cols_per_row = max(1, min(cols_per_row, len(cameras)))  # 카메라 수보다 열이 많아지는 경우를 방지
    for row_start in range(0, len(cameras), cols_per_row):
        row_cams = cameras[row_start: row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, cam in zip(cols, row_cams):
            with col:
                render_camera_card(cam, video_slots, progress_slots)


def render_camera_focus(cameras: list[dict], cam_name: str, video_slots: dict, progress_slots: dict) -> None:
    """특정 카메라 하나만 전체 너비로 확대 표시합니다 (대시보드 구역 선택 드롭다운에서
    '전체 구역'이 아닌 개별 카메라를 골랐을 때 호출됨)."""
    cam = next((c for c in cameras if c["name"] == cam_name), None)
    if cam:
        render_camera_card(cam, video_slots, progress_slots)


def render_camera_reorder(cameras: list[dict]) -> list[str] | None:
    """카메라 이름 목록을 드래그로 정렬할 수 있는 위젯을 표시합니다.
    사용자가 드래그로 순서를 바꾸면 새 순서의 카메라 id 리스트를 반환하고,
    변경이 없으면 None을 반환합니다.

    ⚠️ 영상이 재생 중일 때는 화면이 자주 다시 그려져(rerun) 이 컴포넌트가
    불안정해질 수 있습니다 — 재생을 잠시 멈춘 상태에서 순서를 조정하는 것을 권장합니다.
    """
    name_to_id = {c["name"]: c["id"] for c in cameras}
    current_names = [c["name"] for c in cameras]

    st.caption("이름표를 드래그해서 순서를 바꾸세요.")
    # 기본 빨간색 대신 시스템 톤(짙은 남색 계열)에 맞춘 이름표 색상
    _sortable_style = """
    .sortable-item {
        background-color: transparent;
        border: 1px solid var(--text-color);
        color: var(--text-color);
    }
    """
    sorted_names = sort_items(current_names, direction="horizontal", custom_style=_sortable_style)

    if sorted_names != current_names:
        return [name_to_id[n] for n in sorted_names]
    return None


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
    if st.button("닫기", use_container_width=True):
        ss.popup_id = None
        st.rerun()
