# 다중 카메라 객체 탐지 파이프라인 설계 문서

React/FastAPI 프로젝트에서 여러 차례 시행착오 끝에 정착한 아키텍처를 정리한 문서입니다.
프레임워크(Streamlit이든 React든)와 무관한 **백엔드 설계**이므로, 다른 프로젝트에도 그대로
적용할 수 있습니다.

---

## 1. 배경 — 무엇이 문제였나

**증상**: 영상 여러 개(카메라 4~8대)를 동시에 재생하며 실시간으로 객체 탐지를 하려고 하면
끊김·멈춤·메모리 에러가 반복됨. 스레드로 나눠도, 프로세스로 나눠도, GPU로 옮겨도 근본적으로
해결이 안 됨.

**근본 원인**: "매 프레임을 실시간으로 디코딩 → 추론 → 박스 그리기 → 다시 인코딩해서
전송"하는 구조 자체가 무겁습니다. 카메라가 실시간 RTSP 스트림이 아니라 **이미 업로드된
영상 파일을 반복 재생하는 것**이라면, 이 구조는 애초에 불필요합니다 — 파일이 통째로 이미
존재하므로, 실시간으로 처리할 이유가 없습니다.

**해결 원칙**: **"영상 재생"과 "객체 탐지"를 완전히 분리**합니다.
- 영상 재생은 브라우저(또는 플레이어)가 원본 파일을 그대로 재생 — Python이 프레임에 전혀
  관여하지 않으므로 항상 매끄럽습니다.
- 객체 탐지는 영상이 지정되는 순간 백그라운드에서 미리 전체를 한 번 분석해버립니다.

이렇게 하면 "화면에 박스가 실시간으로 따라다니는" 것처럼 보이면서도, 실제 무거운 연산(추론)은
재생 전에 이미 다 끝나 있어 재생 중 부담이 전혀 없습니다. (Frigate 같은 오픈소스 다중 카메라
NVR 도구들이 실제로 "재생과 분석 분리" 패턴을 씁니다.)

---

## 2. 두 가지 요구사항의 충돌과 해결

프로젝트를 진행하며 요구사항이 두 가지로 나뉘었고, 이 둘은 서로 충돌합니다:

1. **"영상 위에 실시간으로 박스가 따라다녀야 한다"** → 화면 표시는 빨리, 매끄럽게 되어야 함
2. **"탐지 기록(RDS/S3 저장)이 실제 영상이 재생되는 속도에 맞춰 쌓여야 한다"** → 마치 진짜
   실시간 카메라를 보고 있는 것처럼, 기록이 시간에 걸쳐 점진적으로 발생해야 함

하나의 실시간 루프로 둘 다 만족시키려 하면 다시 예전의 "실시간 처리 부담" 문제로 돌아갑니다.
그래서 **탐지 연산(무거움, 1회)**과 **기록 페이스(가벼움, 반복)**를 아예 분리한
**2단계 파이프라인**으로 풀었습니다.

---

## 3. 전체 파이프라인

```
영상 지정/업로드
     │
     ▼
┌─────────────────────────────────────────────┐
│ 1단계: 빠른 사전 분석 (백그라운드, 1회)         │
│  - 0.2초 간격으로 프레임 샘플링                 │
│  - YOLO 추론만 수행 (트래킹/알림/DB 기록 없음)   │
│  - 실시간 제약 없이 최대한 빠르게 (CPU/GPU 한계)  │
│  - 결과를 {t_ms, dets[]} 타임라인으로 캐싱(파일)  │
└─────────────────────────────────────────────┘
     │ 완료되면 자동으로 아래 두 가지가 동시에 가능해짐
     ▼
┌───────────────────────┐   ┌─────────────────────────────────────┐
│ 화면 표시 (프론트엔드)     │   │ 2단계: 실시간 페이스 재생(백그라운드, 반복) │
│  - <video> 원본 그대로   │   │  - 1단계 결과를 실제 영상 길이와 같은     │
│    재생 (Python 미개입)  │   │    속도로 다시 순회(sleep으로 페이스만)  │
│  - <canvas> 오버레이가   │   │  - 이미 아는 결과라 모델 재호출 없음     │
│    재생 시간에 맞춰       │   │  - 새 알림마다 즉시 RDS insert +       │
│    타임라인에서 가장       │   │    S3 스냅샷/클립 업로드              │
│    가까운 박스를 그림      │   │  - 한 바퀴 끝나면 처음부터 반복        │
└───────────────────────┘   │    (video loop와 동일한 개념)          │
                             └─────────────────────────────────────┘
```

핵심은 **1단계(무거운 연산)는 1회만, 2단계(가벼운 페이스 재생)는 그 결과를 재사용해서 반복**한다는
것입니다. 2단계는 모델을 부르지 않고 그냥 `sleep` + 이미 아는 결과로 DB/S3 기록만 하므로 매우
가볍습니다.

---

## 4. 1단계: 사전 분석 (의사코드)

```python
SAMPLE_INTERVAL_MS = 200  # 초당 5회 샘플링

def run_analysis(video_path, on_progress):
    cap = open_video(video_path)
    fps = cap.fps
    total_frames = cap.frame_count
    duration_ms = total_frames / fps * 1000
    frame_interval = max(1, round(fps * SAMPLE_INTERVAL_MS / 1000))

    timeline = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % frame_interval == 0:
            ts_ms = cap.current_pos_ms()
            dets = run_yolo_inference(frame)  # 순수 탐지만, 트래킹/알림 없음
            timeline.append({"t": ts_ms, "dets": dets})
            on_progress(ts_ms / duration_ms)  # 진행률 콜백(프론트에 "분석 중 N%" 표시용)
        idx += 1

    save_json(sidecar_path(video_path), timeline)  # 파일로 캐싱
    return timeline
```

- **트래킹/알림 로직을 여기서 절대 돌리지 않는 것이 핵심**입니다. 순수 탐지 결과만 모읍니다.
- 진행률은 프론트엔드가 폴링해서 "분석 중... N%" 로딩 화면을 보여주는 데 씁니다.
- 이미 분석된(사이드카 파일이 존재하는) 영상은 재분석하지 않고 캐시를 재사용합니다.

---

## 5. 2단계: 실시간 페이스 재생 (의사코드)

```python
def run_pacer(cam, video_path, timeline, stop_event):
    """1단계 결과를 실제 재생 속도로 다시 흘려보내며 트래킹/알림만 수행."""
    cap = open_video(video_path)  # 프레임을 다시 읽기 위해 (스냅샷/클립용)
    track_state = {"person_tracks": {}, "animal_tracks": {}}

    while not stop_event.is_set():
        cycle_start = now()
        for entry in timeline:
            if stop_event.is_set():
                break
            # 다음 항목까지 "실제 영상 시간만큼" 대기 — 여기가 페이싱의 핵심
            target_wall_time = cycle_start + entry["t"] / 1000.0
            sleep_until(target_wall_time, stop_event)

            if not entry["dets"]:
                continue

            frame = cap.seek_and_read(entry["t"])  # 스냅샷/클립용 프레임만 필요시 재획득
            new_alert_ids = process_frame_with_precomputed_dets(
                cam, frame, entry["dets"], track_state, entry["t"]
            )
            for aid in new_alert_ids:
                spawn_thread(extract_and_upload_clip, video_path, entry["t"], aid, timeline)

        # 한 바퀴 다 돌았으면 트랙 리셋 후 처음부터 반복 (video loop와 동일 개념)
        track_state = {"person_tracks": {}, "animal_tracks": {}}
```

- **`sleep_until`이 페이싱의 전부**입니다. 30초짜리 영상이면 한 바퀴가 정확히 실제 30초
  걸리도록 다음 샘플까지 남은 시간만큼 잠듭니다.
- 탐지 결과는 이미 알고 있으므로(`entry["dets"]`) 모델을 다시 부르지 않습니다 — 프레임을
  다시 읽는 이유는 오직 스냅샷/클립 이미지를 만들기 위해서입니다.
- 카메라/채널이 삭제되면 `stop_event.set()`으로 이 스레드를 반드시 멈춰야 합니다(안 하면
  좀비 스레드가 계속 기록을 쌓습니다).

---

## 6. 트래킹 로직 — IoU 기반 매칭 (알림 폭주 방지)

**문제**: 화면에 개체가 여러 마리 있으면(예: 동물 무리), 탐지 결과 배열의 "몇 번째"로
잡혔는지가 프레임마다 흔들립니다. 이걸 "같은 개체인지"의 기준으로 쓰면, 순서만 바뀌어도
매번 "새 개체"로 오인해서 알림이 폭주하고 RDS/S3에 중복 기록이 쌓입니다.

**해결**: 배열 인덱스 대신 **박스 위치 겹침(IoU, Intersection over Union)**으로 이전
프레임의 트랙과 매칭합니다.

```python
def iou(box_a, box_b):
    ix1, iy1 = max(box_a.x1, box_b.x1), max(box_a.y1, box_b.y1)
    ix2, iy2 = min(box_a.x2, box_b.x2), min(box_a.y2, box_b.y2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = (box_a.x2 - box_a.x1) * (box_a.y2 - box_a.y1)
    area_b = (box_b.x2 - box_b.x1) * (box_b.y2 - box_b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

IOU_MATCH_THRESHOLD = 0.25  # 이 이상 겹치면 같은 개체로 간주

def match_detections_to_tracks(dets, tracks):
    """이번 프레임 탐지들을 기존 트랙에 위치 기준으로 매칭. 매칭 안 되면 새 트랙 후보."""
    matches = {}
    used = set()
    for i, det in enumerate(dets):
        best_key, best_iou = None, IOU_MATCH_THRESHOLD
        for key, track in tracks.items():
            if key in used:
                continue
            score = iou(det.box, track.last_box)
            if score > best_iou:
                best_key, best_iou = key, score
        if best_key is not None:
            matches[i] = best_key
            used.add(best_key)
    return matches  # {det_index: track_key}, 매칭 안 된 det는 새 트랙(새 알림)
```

이후 로직:
- 매칭된 트랙 → `update_alert()`: 신뢰도(최댓값)/프레임 수만 조용히 갱신, 새 알림 생성 안 함
- 매칭 안 된 det → `create_alert()`: 새 알림 생성 + RDS insert + S3 스냅샷 업로드
- 몇 프레임 연속으로 매칭이 안 된 트랙은 삭제(사라진 것으로 간주) — "사라져도 N프레임은
  추적 유지" 관용치를 둬서 순간적인 미탐지에 트랙이 끊기지 않게 함

트랙 key는 **배열 인덱스를 재사용하지 말고 계속 증가하는 카운터**를 씁니다(재사용하면 방금
삭제된 트랙의 key와 새 트랙의 key가 우연히 겹칠 수 있음).

---

## 7. 클립(영상) 생성 — 박스 포함

**문제**: 실시간 스트리밍 때는 "탐지 전후 N초"를 위해 프레임을 미리 버퍼에 담아뒀다가 알림이
뜨면 그걸로 클립을 만들었습니다. 파일이 이미 통째로 존재하는 지금 구조에서는 그럴 필요가
없습니다.

**해결**: 알림이 발생한 시점을 알고 있고 원본 파일에 랜덤 접근이 가능하므로, **그 구간만
바로 잘라서** 각 프레임에 박스를 그린 뒤 인코딩합니다.

```python
CLIP_PRE_SECONDS = 3.0
CLIP_POST_SECONDS = 3.0

def extract_and_upload_clip(video_path, alert_ts_ms, alert_id, timeline):
    start_sec = max(0, alert_ts_ms / 1000 - CLIP_PRE_SECONDS)
    end_sec = alert_ts_ms / 1000 + CLIP_POST_SECONDS

    cap = open_video(video_path)
    cap.seek(start_sec)
    frames = []
    while cap.current_pos_sec() <= end_sec:
        ret, frame = cap.read()
        if not ret:
            break
        # 이 프레임 시점에 가장 가까운 탐지 결과를 타임라인에서 찾아 박스를 그림
        dets = nearest_timeline_entry(timeline, cap.current_pos_ms()).dets
        frames.append(draw_boxes(frame, dets))
    cap.release()

    clip_path = encode_mp4(frames, fps=cap.fps)  # H.264, 브라우저 재생 가능한 코덱
    s3_key = upload_to_s3(clip_path)
    update_log_with_clip_uri(alert_id, s3_key)
```

**놓치기 쉬운 함정**: 그냥 `ffmpeg -ss ... -t ...`로 구간만 자르면 **박스 없이 원본 그대로
잘립니다.** 박스를 그리려면 프레임 단위로 직접 읽어서 그린 뒤 다시 인코딩해야 합니다.

카메라당 동시 클립 생성 개수를 제한(예: 2개)해서, 알림이 몰릴 때 클립 인코딩 스레드가
무한정 쌓이는 걸 방지하는 것도 중요합니다.

---

## 8. 프론트엔드: 영상 재생 + 박스 오버레이 동기화

```
<video> (원본 파일, 브라우저 네이티브 재생, autoplay+muted+loop)
   +
<canvas> (video 위에 absolute 포지션으로 겹침, 같은 크기)
```

```javascript
function findNearestEntry(timeline, tMs) {
  // timeline은 t 기준 정렬되어 있음 — 이진 탐색으로 가장 가까운 항목 탐색
  ...
}

function tick() {
  const entry = findNearestEntry(timeline, video.currentTime * 1000);
  clearCanvas(canvas);
  for (const det of entry?.dets ?? []) {
    drawBox(canvas, det.box, det.class_name, det.confidence);
  }
  requestAnimationFrame(tick);  // 매 프레임 반복
}
```

- `canvas.width/height`를 영상의 **원본 픽셀 크기**(`video.videoWidth/videoHeight`)로
  맞추고, CSS로만 화면에 맞게 스케일링하면 박스 좌표를 그대로 써도 정확한 위치에 그려집니다.
- 재생/일시정지는 백엔드 API 호출 없이 `video.play()/video.pause()`로 프론트에서 직접
  제어합니다.
- **Streamlit에서 구현 시**: `st.video()`로 원본 파일 재생 자체는 가능하지만, 이 캔버스
  동기화 로직(연속적인 JS 애니메이션 루프)은 Streamlit 기본 위젯으로 안 됩니다. Streamlit
  커스텀 컴포넌트(내부적으로 iframe에 HTML/JS를 넣는 방식, `st.components.v1.html()` 등)로
  이 JS 코드를 직접 심어야 합니다.

---

## 9. 안정성 관련 세부 사항 (놓치기 쉬운 것들)

- **RDS/S3 호출에 짧은 타임아웃을 반드시 설정**하세요. boto3/SQLAlchemy 기본값은 최대
  60초까지 대기할 수 있어, 네트워크가 살짝만 불안정해도 스레드 하나가 오래 묶입니다.
  (예: S3 connect 3초/read 5초, RDS connect 5초, 재시도 0회)
- **모델은 프로세스/스레드 내부에서 직접 호출**하고, 자기 자신의 HTTP API로 루프백 호출하지
  마세요. `async def` 핸들러 안에서 무거운 동기 연산을 직접 돌리면 이벤트 루프 전체가
  막힙니다(FastAPI라면 동기 함수는 스레드풀에서 자동 실행되는 `def` 라우트로 만들거나
  `run_in_threadpool`로 감싸세요).
- **로컬 CPU 추론이 느리면 원격 GPU(Colab 등)으로 위임하는 것도 방법**이지만, 그 경우
  자기 프로세스 안에서 부르는 게 아니라 네트워크 호출이 되므로 반드시 다음을 지키세요:
  - `requests.Session()`으로 연결을 재사용하세요(매번 새 TCP+TLS 연결을 맺으면 요청마다
    수백ms가 반복해서 붙습니다).
  - 전송 전에 이미지를 모델 입력 크기 수준(예: 640px)으로 축소하세요(업로드 용량 절감).
  - **반환된 박스 좌표는 축소된 이미지 기준이므로, 원본 해상도로 다시 확대해서 그려야
    합니다** (이걸 빠뜨리면 박스가 엉뚱한 위치에 훨씬 작게 그려집니다).
- **하나의 프레임 처리 실패가 전체를 멈추게 하지 마세요.** 재생/분석 루프 전체를
  `try/except`로 감싸, 한 번의 에러(네트워크 순간 오류, 코덱 문제 등)가 스레드를 조용히
  죽이지 않고 다음 프레임에서 계속 재시도하게 만드세요.
- **Windows에서 OpenCV+PyTorch 조합 시 `OMP: Error #15`(OpenMP 런타임 중복 로드) 충돌이
  날 수 있습니다.** 카메라 여러 대가 동시에 cv2(디코딩)와 torch(추론)를 스레드로 함께
  두드릴 때 멈춤/크래시로 이어질 수 있어, 환경변수 `KMP_DUPLICATE_LIB_OK=TRUE`를
  설정해두는 걸 권장합니다.
- **FFmpeg가 "mmco: unref short failure" 경고를 반복 출력**할 수 있습니다(H.264 영상에서
  임의 위치로 seek할 때). 동작엔 문제없는 경고지만 콘솔에 도배되면 그 자체가 부하가 될 수
  있으니, `OPENCV_FFMPEG_LOGLEVEL=-8` 환경변수로 조용히 만드세요.

---

## 10. 요약 체크리스트

- [ ] 영상 지정 시 백그라운드에서 즉시 사전 분석 시작 (빠르게, 실시간 제약 없이)
- [ ] 분석 결과를 `{t_ms, dets[]}` 타임라인으로 캐싱
- [ ] 화면 재생: 원본 파일 그대로 + 타임라인을 재생 시간에 동기화해서 오버레이
- [ ] 분석 완료 후 별도 스레드로 "실제 재생 속도" 페이서 시작 → 이미 아는 결과로 트래킹/알림/
      RDS/S3 기록만 수행, 영상 길이만큼 돌면 반복
- [ ] 트래킹은 배열 인덱스가 아니라 IoU 기반 위치 매칭
- [ ] 클립은 원본에서 구간을 잘라 프레임별로 박스를 다시 그려서 인코딩
- [ ] RDS/S3 호출에 짧은 타임아웃, 루프는 예외에 안전하게, 모델은 직접 호출(자기 API
      루프백 금지)
