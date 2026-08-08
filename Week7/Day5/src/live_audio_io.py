"""
Week 7 - Day 5 (extension): shared live audio I/O primitives.

Pulled out of live_voice_pipeline.py so BOTH orchestrators
(conversation_agent.py and graph.py) can run a live mic conversation loop
without importing each other. This module owns only the hardware edges:

    microphone  -> Deepgram Live STT (streaming)  -> listen_for_utterance()
    audio bytes -> speaker                         -> play_audio_bytes()

It has no knowledge of ConversationMemory, LangGraph, or run_turn() of any
kind - that orchestration-specific logic lives in conversation_agent.py's
and graph.py's own run_live_mic_conversation() functions, which both import
listen_for_utterance()/play_audio_bytes() from here.

Only imports voice_pipeline.py (for its Deepgram client getter, language
config, and Fish Audio TTS helpers) - not conversation_agent.py or graph.py -
so there is no import cycle no matter which orchestrator imports this module.

Requires (not needed by the rest of Day 5) - matches the deepgram-sdk==3.7.7
already pinned for voice_pipeline.py's prerecorded STT, no SDK upgrade needed:
    pip install pygame
Deepgram's Microphone helper additionally needs PyAudio, which itself needs
PortAudio installed at the OS level:
    macOS:   brew install portaudio
    Ubuntu:  sudo apt-get install portaudio19-dev
    Windows: PyAudio installs pre-built, nothing extra needed
"""

import os
import sys
import tempfile
import threading
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deepgram import (  # type: ignore
    DeepgramClient,
    LiveOptions,
    LiveTranscriptionEvents,
    Microphone,
)

import voice_pipeline as vp  # reused: Deepgram client getter, language config

# deepgram-sdk==3.7.7 (pinned project-wide, same version voice_pipeline.py's
# prerecorded STT already uses) - client.listen.live still works on this
# version but is deprecated in favor of client.listen.websocket, which is
# what's used below. Both expose the identical LiveOptions/events/Microphone
# API, so nothing in this module is version-sensitive.

DEEPGRAM_LANGUAGE = vp.DEEPGRAM_LANGUAGE

# Deepgram Live requires raw PCM in, matched to what Microphone actually
# captures (16kHz mono 16-bit linear PCM) - if these two drift apart the
# transcript comes back empty/garbled with no error raised.
MIC_SAMPLE_RATE = 16000
MIC_ENCODING = "linear16"
MIC_CHANNELS = 1

# How long to wait with no new words before considering a full utterance
# done (Deepgram's `endpointing` param). Confirmed live at the old default
# (300ms): a customer speaking multiple pieces of info in one turn (name,
# then a pause, then phone number, then a pause, then continuing) got cut
# off mid-utterance - a natural thinking pause exceeded 300ms and Deepgram
# marked speech_final=True before they were actually done, which closes
# the mic (see listen_for_utterance() below) and can't be undone for that
# turn. Raised to a much more forgiving default; tune via env if needed.
DEFAULT_ENDPOINTING_MS = int(os.getenv("LIVE_ENDPOINTING_MS", "1200"))

# How long to wait with no final transcript before giving up on a turn and
# going back to "listening" (protects against a silent/dead mic hanging forever)
DEFAULT_LISTEN_TIMEOUT_S = float(os.getenv("LIVE_LISTEN_TIMEOUT_S", "25"))

_mixer_ready = False


def get_deepgram_client() -> DeepgramClient:
    # reuses voice_pipeline.py's own client getter (same api key, same
    # RuntimeError-if-missing behavior) instead of building a second one here
    return vp._get_deepgram_client()


# ---------- Playback (Fish Audio returns mp3 bytes; pygame plays them with no ffmpeg dependency) ----------

def _ensure_mixer():
    global _mixer_ready
    if not _mixer_ready:
        import pygame  # imported lazily so the rest of the module works without it installed

        pygame.mixer.init()
        _mixer_ready = True


def play_audio_bytes(audio_bytes: bytes):
    """Blocks until playback finishes. Writes to a short-lived temp file because
    pygame's mixer.music needs a seekable file, not just a bytes buffer."""
    import pygame

    _ensure_mixer()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name

    try:
        pygame.mixer.music.load(temp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
    finally:
        pygame.mixer.music.unload()
        try:
            os.remove(temp_path)
        except OSError:
            pass


# ---------- Live mic capture + Deepgram streaming STT ----------

def listen_for_utterance(timeout_s: float = DEFAULT_LISTEN_TIMEOUT_S) -> Optional[str]:
    """Opens the mic, streams audio to Deepgram Live until the caller finishes
    a full utterance (Deepgram's endpointing/UtteranceEnd), then closes both
    and returns the transcript. Returns None on timeout or empty speech."""
    client = get_deepgram_client()
    dg_connection = client.listen.websocket.v("1")

    utterance_done = threading.Event()
    final_pieces = []
    got_any_speech = threading.Event()

    def on_open(_, open, **kwargs):
        pass

    def on_message(_, result=None, **kwargs):
        if result is None:
            return
        transcript = result.channel.alternatives[0].transcript
        if not transcript:
            return
        got_any_speech.set()
        if result.is_final:
            final_pieces.append(transcript)
            if result.speech_final:
                utterance_done.set()

    def on_utterance_end(_, utterance_end=None, **kwargs):
        # fires even when speech_final never triggered (e.g. trailing silence)
        if final_pieces:
            utterance_done.set()

    def on_error(_, error=None, **kwargs):
        print(f"  [live_audio_io] Deepgram error: {error}")
        utterance_done.set()

    dg_connection.on(LiveTranscriptionEvents.Open, on_open)
    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
    dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
    dg_connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model="nova-3",
        language=DEEPGRAM_LANGUAGE,
        smart_format=True,
        interim_results=True,
        utterance_end_ms=os.getenv("LIVE_UTTERANCE_END_MS", "1500"),
        vad_events=True,
        endpointing=DEFAULT_ENDPOINTING_MS,
        encoding=MIC_ENCODING,
        sample_rate=MIC_SAMPLE_RATE,
        channels=MIC_CHANNELS,
    )

    if not dg_connection.start(options):
        raise RuntimeError("Failed to open Deepgram live connection.")

    microphone = Microphone(dg_connection.send, rate=MIC_SAMPLE_RATE, channels=MIC_CHANNELS)
    microphone.start()

    print("Listening... (speak now)")
    finished_in_time = utterance_done.wait(timeout=timeout_s)

    microphone.finish()
    dg_connection.finish()

    if not finished_in_time and not got_any_speech.is_set():
        print(f"  [live_audio_io] No speech detected in {timeout_s:.0f}s, listening again.")
        return None

    transcript = " ".join(p.strip() for p in final_pieces if p.strip()).strip()
    return transcript or None