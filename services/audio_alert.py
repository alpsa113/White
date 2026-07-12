"""services/audio_alert.py — 사람 탐지 시 재생할 알림음(사인파로 즉석 생성, 파일 없음).

React 클라이언트가 `GET /api/alert-sound`로 WAV 바이트를 1회 받아 캐시해두고,
`/api/tracking/state` 폴링으로 새 사람 탐지를 감지할 때마다 재생합니다."""
import io
import math
import struct
import wave


def beep_wav_bytes(freq: int = 880, duration_ms: int = 200, volume: float = 0.4) -> bytes:
    """짧은 사인파 비프음을 WAV 바이트로 반환합니다."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            value = int(volume * 32767 * math.sin(2 * math.pi * freq * t))
            wf.writeframesraw(struct.pack("<h", value))
    return buf.getvalue()
