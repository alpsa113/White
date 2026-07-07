"""
services/audio_alert.py — 사람 탐지 시 재생할 알림음

별도 음원 파일 없이 순수 계산(사인파)으로 짧은 비프음을 생성합니다.
저작권 문제가 없고, 파일 I/O 없이 메모리에서 바로 base64로 인코딩해
<audio> 태그로 재생합니다.
"""
import base64
import io
import math
import struct
import wave

import streamlit as st


def _beep_data_uri(freq: int = 880, duration_ms: int = 200, volume: float = 0.4) -> str:
    """짧은 사인파 비프음을 즉석에서 생성해 <audio> 태그에 바로 쓸 수 있는
    base64 데이터 URI로 반환합니다."""
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
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:audio/wav;base64,{b64}"


def play_alert_sound() -> None:
    """사람 탐지 시 짧은 비프음을 재생합니다."""
    st.markdown(
        f'<audio autoplay style="display:none"><source src="{_beep_data_uri()}" type="audio/wav"></audio>',
        unsafe_allow_html=True,
    )
