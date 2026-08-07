"""
Day 5 integration - Streamlit UI: live call interface.

Thin HTTP client for the FastAPI backend (src/api.py) - no LangGraph/LLM/
Deepgram/Fish Audio imports here, every provider call still happens
server-side. The only thing that lives in the browser is audio capture:
streamlit-webrtc keeps the mic live for the whole call (one click to grant
mic access and connect, same as answering a phone), and a simple
energy-based VAD segments speech into turns automatically as you talk -
no push-to-talk button, no record/stop/wait cycle per turn.

Run the backend first, then this app:
    uvicorn src.api:app --reload --port 8000      (from Day5/)
    streamlit run app.py                          (from Day5/, separate terminal)
"""

import base64
import io
import os
import queue
import time
from typing import Any, Dict, Optional

import pydub
import requests
import streamlit as st
from dotenv import load_dotenv, find_dotenv
from streamlit_webrtc import WebRtcMode, webrtc_streamer

load_dotenv(find_dotenv())

API_BASE = os.getenv("VOICE_AGENT_API_BASE", "http://localhost:8000")

# ---- VAD tuning (energy-based: pydub's .rms per audio frame) ----
SILENCE_RMS_THRESHOLD = 600     # below this = silence; tune up/down for a noisy room vs. a quiet mic
SILENCE_DURATION_MS = 900       # how long silence must persist to end an utterance
MIN_UTTERANCE_MS = 400          # discard anything shorter than this (coughs, clicks, mic noise)
MAX_UTTERANCE_MS = 20000        # safety cap - flushes a long ramble instead of buffering forever

st.set_page_config(page_title="RealEstate Hub Voice Agent", page_icon="🏠", layout="centered")

st.markdown(
    """
    <style>
    .block-container { max-width: 720px; padding-top: 2rem; }
    .call-orb {
        width: 96px; height: 96px; border-radius: 50%; margin: 0 auto 1rem auto;
        display: flex; align-items: center; justify-content: center; font-size: 2.5rem;
        transition: background 0.3s ease;
    }
    .orb-idle { background: #e5e7eb; }
    .orb-listening { background: #dbeafe; animation: pulse 1.6s ease-in-out infinite; }
    .orb-thinking { background: #fef3c7; }
    .orb-speaking { background: #dcfce7; animation: pulse 1s ease-in-out infinite; }
    @keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.08); } 100% { transform: scale(1); } }
    .call-status { text-align: center; color: #6b7280; margin-bottom: 1.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Backend HTTP helpers
# ---------------------------------------------------------------------------

def _api_post(path: str, **kwargs) -> Optional[Dict[str, Any]]:
    try:
        r = requests.post(f"{API_BASE}{path}", timeout=60, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        detail = None
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                detail = resp.json().get("detail")
            except Exception:
                pass
        st.error(f"Backend request to {path} failed: {detail or e}")
        return None


def _api_get(path: str) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.error(f"Backend request to {path} failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Session bootstrap - starts the call and gets the spoken greeting
# ---------------------------------------------------------------------------

def _start_new_call() -> None:
    result = _api_post("/session/start")
    st.session_state.session_id = result["session_id"] if result else None
    st.session_state.pending_audio = base64.b64decode(result["audio_base64"]) if result and result.get("audio_base64") else None


if "session_id" not in st.session_state:
    _start_new_call()


# ---------------------------------------------------------------------------
# Header + call controls
# ---------------------------------------------------------------------------

header_col, button_col = st.columns([4, 1])
with header_col:
    st.markdown("### 🏠 RealEstate Hub — Live Call")
with button_col:
    if st.button("📞 New Call"):
        _start_new_call()
        st.rerun()

status_ph = st.empty()
orb_ph = st.empty()


def set_status(label: str, css_class: str, icon: str) -> None:
    orb_ph.markdown(f'<div class="call-orb {css_class}">{icon}</div>', unsafe_allow_html=True)
    status_ph.markdown(f'<div class="call-status">{label}</div>', unsafe_allow_html=True)


set_status("Click Start below to begin the call", "orb-idle", "☎️")


# ---------------------------------------------------------------------------
# Conversation history (DB-backed via the backend, survives a restart)
# ---------------------------------------------------------------------------

chat_ph = st.container()


def render_chat() -> list:
    if not st.session_state.session_id:
        return []
    resp = _api_get(f"/session/{st.session_state.session_id}/transcript")
    rows = resp["transcript"] if resp else []
    chat_ph.empty()
    with chat_ph:
        for row in rows:
            role = "user" if row["speaker"] == "customer" else "assistant"
            with st.chat_message(role):
                st.write(row["text"])
        if not rows:
            st.info("Click Start below - the agent will greet you and the call begins.")
    return rows


render_chat()

audio_ph = st.empty()
if st.session_state.get("pending_audio"):
    audio_ph.audio(st.session_state.pending_audio, format="audio/mp3", autoplay=True)
    st.session_state.pending_audio = None


# ---------------------------------------------------------------------------
# Live mic - one click to connect (unavoidable browser mic-permission
# gesture), fully hands-free after that.
# ---------------------------------------------------------------------------

st.divider()
st.caption("🎙️ Click **Start** once to join the call, then just talk naturally - your turn is sent automatically when you pause.")

webrtc_ctx = webrtc_streamer(
    key="live-call",
    mode=WebRtcMode.SENDONLY,
    audio_receiver_size=256,
    media_stream_constraints={"audio": True, "video": False},
    rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
)


def _process_utterance(wav_bytes: bytes) -> None:
    set_status("Thinking...", "orb-thinking", "🤔")
    files = {"file": ("utterance.wav", wav_bytes, "audio/wav")}
    data = _api_post(f"/session/{st.session_state.session_id}/turn/audio", files=files)
    if data:
        render_chat()
        if data.get("audio_base64"):
            set_status("Speaking...", "orb-speaking", "🔊")
            audio_ph.audio(base64.b64decode(data["audio_base64"]), format="audio/mp3", autoplay=True)
    set_status("Listening...", "orb-listening", "🎙️")


if webrtc_ctx.state.playing and st.session_state.session_id:
    set_status("Listening...", "orb-listening", "🎙️")

    segment = pydub.AudioSegment.empty()
    speaking = False
    speech_started_at = 0.0
    silence_started_at: Optional[float] = None

    while webrtc_ctx.state.playing:
        if not webrtc_ctx.audio_receiver:
            time.sleep(0.1)
            continue
        try:
            frames = webrtc_ctx.audio_receiver.get_frames(timeout=1)
        except queue.Empty:
            continue

        for frame in frames:
            sound = pydub.AudioSegment(
                data=frame.to_ndarray().tobytes(),
                sample_width=frame.format.bytes,
                frame_rate=frame.sample_rate,
                channels=len(frame.layout.channels),
            )
            now_ms = time.monotonic() * 1000

            is_loud = sound.rms > SILENCE_RMS_THRESHOLD
            if is_loud:
                if not speaking:
                    speaking = True
                    speech_started_at = now_ms
                    segment = pydub.AudioSegment.empty()
                silence_started_at = None
                segment += sound
            elif speaking:
                segment += sound
                if silence_started_at is None:
                    silence_started_at = now_ms

            utterance_ended = speaking and silence_started_at is not None and (now_ms - silence_started_at) >= SILENCE_DURATION_MS
            utterance_too_long = speaking and (now_ms - speech_started_at) >= MAX_UTTERANCE_MS

            if utterance_ended or utterance_too_long:
                speaking = False
                silence_started_at = None
                duration_ms = len(segment)
                captured = segment
                segment = pydub.AudioSegment.empty()

                if duration_ms >= MIN_UTTERANCE_MS:
                    wav_buf = io.BytesIO()
                    captured.export(wav_buf, format="wav")
                    _process_utterance(wav_buf.getvalue())
                    # drop whatever queued up in the browser while that turn
                    # was being processed, so listening resumes cleanly
                    # instead of picking up stale audio from mid-processing
                    try:
                        while True:
                            webrtc_ctx.audio_receiver.get_frames(timeout=0)
                    except queue.Empty:
                        pass
elif st.session_state.session_id:
    set_status("Call not connected - click Start above", "orb-idle", "☎️")
