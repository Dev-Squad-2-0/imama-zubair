"""
Week 7 - Day 5 (extension): Live Streaming Voice Pipeline

Real-time loop, replacing the file-in/file-out pipeline in voice_pipeline.py
with a live mic-in / speaker-out one:

    User speaks -> Microphone -> Deepgram Live STT (streaming)
        -> LangGraph Agent (graph.run_turn, Day 5's full state/tools/guardrails)
        -> Fish Audio TTS -> Play audio -> wait for user to speak again

Nothing from Day 5 is reimplemented here: this module only wires two new
edges onto the existing graph -
  1. live audio in  -> transcript   (Deepgram's streaming/websocket API,
     instead of voice_pipeline.py's file-based stt_transcribe())
  2. agent_reply     -> speaker out (voice_pipeline.py's real Fish Audio
     TTS call, played instead of saved to disk)
graph.run_turn() (LangGraph orchestration, tools, guardrails, logging) and
voice_pipeline.py's TTS/cleaning/emotion-tagging helpers are reused as-is.

Requires (not needed by the rest of Day 5) - matches the deepgram-sdk==3.7.7
already pinned for voice_pipeline.py's prerecorded STT, no SDK upgrade needed:
    pip install pygame
Deepgram's Microphone helper additionally needs PyAudio, which itself needs
PortAudio installed at the OS level:
    macOS:   brew install portaudio
    Ubuntu:  sudo apt-get install portaudio19-dev
    Windows: PyAudio installs pre-built, nothing extra needed

Run:
    cd Day5/src
    python live_voice_pipeline.py                 # live mic conversation loop
    python live_voice_pipeline.py --session my-id  # use a specific session id
"""

import os
import re
import sys
import tempfile
import threading
import time
import traceback
from typing import Optional

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from deepgram import (  # type: ignore
    DeepgramClient,
    LiveOptions,
    LiveTranscriptionEvents,
    Microphone,
)

# deepgram-sdk==3.7.7 (pinned project-wide, same version voice_pipeline.py's
# prerecorded STT already uses) - client.listen.live still works on this
# version but is deprecated in favor of client.listen.websocket, which is
# what's used below. Both expose the identical LiveOptions/events/Microphone
# API, so nothing else in this module is version-sensitive.

import graph  # Day 5's compiled LangGraph agent (run_turn)
import voice_pipeline as vp  # reused: TTS call, sentence cleaning, emotion tags

# Reuses voice_pipeline.py's own env lookups directly, instead of re-reading
# os.getenv() separately here, so the two pipelines can never drift apart on
# API key / language config.
DEEPGRAM_API_KEY = vp.DEEPGRAM_API_KEY
DEEPGRAM_LANGUAGE = vp.DEEPGRAM_LANGUAGE

# Deepgram Live requires raw PCM in, matched to what Microphone actually
# captures (16kHz mono 16-bit linear PCM) - if these two drift apart the
# transcript comes back empty/garbled with no error raised.
MIC_SAMPLE_RATE = 16000
MIC_ENCODING = "linear16"
MIC_CHANNELS = 1

# How long to wait with no final transcript before giving up on a turn and
# going back to "listening" (protects against a silent/dead mic hanging forever)
LISTEN_TIMEOUT_S = float(os.getenv("LIVE_LISTEN_TIMEOUT_S", "25"))

_GOODBYE_WORDS = re.compile(
    r"\b(bye|khuda\s*hafiz|allah\s*hafiz|shukriya\s*khuda\s*hafiz|good\s*bye)\b",
    re.IGNORECASE,
)

_mixer_ready = False


def _get_deepgram_client() -> DeepgramClient:
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


def speak_reply(reply_text: str):
    """Splits agent_reply into sentences and speaks each as it's synthesized -
    same sentence-by-sentence approach as run_voice_turn(), just played live
    instead of saved to disk."""
    sentences = vp._split_into_sentences(reply_text)
    if not sentences:
        return

    for sentence in sentences:
        tagged = vp._apply_emotion_tag(sentence)
        print(f"AGENT: {sentence}")
        try:
            audio_bytes, _ = vp.tts_stream_audio(tagged)
        except RuntimeError as e:
            print(f"  [live_voice_pipeline] TTS failed for this sentence, skipping: {e}")
            continue
        play_audio_bytes(audio_bytes)


# ---------- Live mic capture + Deepgram streaming STT ----------

def listen_for_utterance(timeout_s: float = LISTEN_TIMEOUT_S) -> Optional[str]:
    """Opens the mic, streams audio to Deepgram Live until the caller finishes
    a full utterance (Deepgram's endpointing/UtteranceEnd), then closes both
    and returns the transcript. Returns None on timeout or empty speech."""
    client = _get_deepgram_client()
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
        print(f"  [live_voice_pipeline] Deepgram error: {error}")
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
        utterance_end_ms="1000",
        vad_events=True,
        endpointing=300,
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
        print(f"  [live_voice_pipeline] No speech detected in {timeout_s:.0f}s, listening again.")
        return None

    transcript = " ".join(p.strip() for p in final_pieces if p.strip()).strip()
    return transcript or None


# ---------- Main conversation loop ----------

def run_live_session(session_id: str = "live-caller"):
    """Runs the full loop: greet -> (listen -> agent -> speak) forever, until
    the caller says goodbye or the process is interrupted."""
    print(f"Starting live session '{session_id}'. Press Ctrl+C to end the call.\n")

    vp.warmup_tts()

    reply, _trace = graph.run_turn(session_id, "")
    if reply:
        speak_reply(reply)

    try:
        while True:
            transcript = listen_for_utterance()
            if transcript is None:
                continue

            print(f"USER: {transcript}")

            reply, trace = graph.run_turn(session_id, transcript)
            if reply:
                speak_reply(reply)

            if _GOODBYE_WORDS.search(transcript) or not reply:
                print("\nCall ended.")
                break

    except KeyboardInterrupt:
        print("\nCall interrupted by user.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live mic-to-mic voice agent session.")
    parser.add_argument("--session", default="live-caller", help="Session id to use/resume.")
    args = parser.parse_args()

    try:
        run_live_session(args.session)
    except RuntimeError as e:
        print(f"Live pipeline failed to start: {e}")
        print(
            "Check that DEEPGRAM_API_KEY / BASE_URL / API_KEY / FISH_AUDIO_API_KEY are "
            "set in your .env, and that PortAudio is installed (needed by PyAudio, "
            "which Deepgram's Microphone helper uses)."
        )
        raise SystemExit(1)
