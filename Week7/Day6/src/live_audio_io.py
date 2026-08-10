"""
Shared live audio I/O for the voice agent.

Key local-demo behavior:
- Uses an EXPLICIT PyAudio input device instead of blindly relying on the
  Deepgram Microphone helper/default Windows recording source.
- Set LIVE_INPUT_DEVICE_INDEX in .env after running:
      python tests/audio/list_audio_inputs.py
- Barge-in does NOT trigger on raw VAD by default.
- Interim Deepgram hypotheses must be stable before playback is interrupted.
- Only FINAL Deepgram text is normally forwarded to LangGraph.

This avoids common Windows cases where "Stereo Mix", a virtual cable, or
another monitor source captures the agent's own TTS even while headphones
are being used.
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
)

import voice_pipeline as vp

DEEPGRAM_MODEL = vp.DEEPGRAM_MODEL
DEEPGRAM_LANGUAGE = vp.DEEPGRAM_LANGUAGE
DEEPGRAM_KEYTERMS = vp.DEEPGRAM_KEYTERMS

MIC_SAMPLE_RATE = 16000
MIC_ENCODING = "linear16"
MIC_CHANNELS = 1
MIC_FRAMES_PER_BUFFER = int(os.getenv("LIVE_MIC_FRAMES_PER_BUFFER", "1024"))

DEFAULT_ENDPOINTING_MS = int(os.getenv("LIVE_ENDPOINTING_MS", "1200"))
DEFAULT_LISTEN_TIMEOUT_S = float(os.getenv("LIVE_LISTEN_TIMEOUT_S", "25"))

# Safer barge-in defaults for a Windows local demo.
BARGE_IN_GRACE_MS = int(os.getenv("LIVE_BARGE_IN_GRACE_MS", "450"))
BARGE_IN_FINAL_WAIT_S = float(os.getenv("LIVE_BARGE_IN_FINAL_WAIT_S", "5"))
BARGE_IN_ON_VAD = os.getenv("LIVE_BARGE_IN_ON_VAD", "0").lower() in {
    "1", "true", "yes"
}
BARGE_IN_INTERIM_CONFIRMATIONS = max(
    1, int(os.getenv("LIVE_BARGE_IN_INTERIM_CONFIRMATIONS", "2"))
)
BARGE_IN_INTERIM_MIN_CHARS = max(
    1, int(os.getenv("LIVE_BARGE_IN_INTERIM_MIN_CHARS", "3"))
)
BARGE_IN_ALLOW_INTERIM_FALLBACK = os.getenv(
    "LIVE_BARGE_IN_ALLOW_INTERIM_FALLBACK", "0"
).lower() in {"1", "true", "yes"}

LAST_STT_CONFIDENCE = None

def get_last_stt_confidence():
    return LAST_STT_CONFIDENCE

_mixer_ready = False
_printed_input_device = False


def get_deepgram_client() -> DeepgramClient:
    return vp._get_deepgram_client()


# ---------------------------------------------------------------------------
# Explicit local microphone selection
# ---------------------------------------------------------------------------

def _pyaudio():
    try:
        import pyaudio  # type: ignore
        return pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "PyAudio is required for live microphone capture. "
            "Install it with: pip install pyaudio"
        ) from exc


def list_input_devices():
    """Return PortAudio input devices visible to PyAudio."""
    pyaudio = _pyaudio()
    pa = pyaudio.PyAudio()
    devices = []
    try:
        for index in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) > 0:
                devices.append(
                    {
                        "index": index,
                        "name": info.get("name", "Unknown"),
                        "max_input_channels": int(info.get("maxInputChannels", 0)),
                        "default_sample_rate": int(float(info.get("defaultSampleRate", 0))),
                        "host_api": int(info.get("hostApi", -1)),
                    }
                )
        return devices
    finally:
        pa.terminate()


def _selected_input_device_index(pa) -> int:
    raw = os.getenv("LIVE_INPUT_DEVICE_INDEX", "").strip()

    if raw:
        try:
            index = int(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"LIVE_INPUT_DEVICE_INDEX must be an integer, got {raw!r}"
            ) from exc

        if index < 0 or index >= pa.get_device_count():
            raise RuntimeError(
                f"LIVE_INPUT_DEVICE_INDEX={index} is not a valid PortAudio device."
            )

        info = pa.get_device_info_by_index(index)
        if int(info.get("maxInputChannels", 0)) <= 0:
            raise RuntimeError(
                f"PortAudio device #{index} ({info.get('name')}) is not an input device."
            )
        return index

    try:
        return int(pa.get_default_input_device_info()["index"])
    except Exception as exc:
        raise RuntimeError(
            "No default microphone was found. Run "
            "`python tests/audio/list_audio_inputs.py` and set "
            "LIVE_INPUT_DEVICE_INDEX in .env."
        ) from exc


def selected_input_device_info():
    pyaudio = _pyaudio()
    pa = pyaudio.PyAudio()
    try:
        index = _selected_input_device_index(pa)
        info = dict(pa.get_device_info_by_index(index))
        info["index"] = index
        return info
    finally:
        pa.terminate()


def print_selected_input_device(force=False):
    global _printed_input_device
    if _printed_input_device and not force:
        return

    info = selected_input_device_info()
    print(
        "Microphone input: "
        f"#{int(info['index'])} {info.get('name')} "
        f"(input channels={int(info.get('maxInputChannels', 0))})"
    )

    lowered = str(info.get("name", "")).lower()
    suspicious = (
        "stereo mix",
        "what u hear",
        "loopback",
        "virtual cable",
        "cable output",
        "monitor",
    )
    if any(token in lowered for token in suspicious):
        print(
            "  WARNING: this looks like a loopback/monitor device and may capture "
            "the agent's own TTS. Select your physical microphone instead."
        )

    _printed_input_device = True


class LocalMicrophone:
    """Small PyAudio input stream that sends raw PCM to Deepgram."""

    def __init__(
        self,
        send_callback,
        rate=MIC_SAMPLE_RATE,
        channels=MIC_CHANNELS,
    ):
        self._send_callback = send_callback
        self._rate = rate
        self._channels = channels
        self._pa = None
        self._stream = None
        self.device_index = None
        self.device_name = None

    def _callback(self, in_data, frame_count, time_info, status_flags):
        pyaudio = _pyaudio()
        try:
            self._send_callback(in_data)
        except Exception:
            # Deepgram's websocket error handler owns network failures.
            pass
        return (None, pyaudio.paContinue)

    def start(self):
        pyaudio = _pyaudio()
        self._pa = pyaudio.PyAudio()
        self.device_index = _selected_input_device_index(self._pa)
        info = self._pa.get_device_info_by_index(self.device_index)
        self.device_name = info.get("name")

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=MIC_FRAMES_PER_BUFFER,
            stream_callback=self._callback,
        )
        self._stream.start_stream()
        return self

    def finish(self):
        if self._stream is not None:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def _ensure_mixer():
    global _mixer_ready
    if not _mixer_ready:
        import pygame
        pygame.mixer.init()
        _mixer_ready = True


def play_audio_bytes(
    audio_bytes: bytes,
    interrupt_event: Optional[threading.Event] = None,
) -> bool:
    """Play MP3 bytes. Return False when caller barge-in stops playback."""
    import pygame

    _ensure_mixer()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name

    try:
        if interrupt_event is not None and interrupt_event.is_set():
            return False

        pygame.mixer.music.load(temp_path)
        pygame.mixer.music.play()

        completed = True
        while pygame.mixer.music.get_busy():
            if interrupt_event is not None and interrupt_event.is_set():
                pygame.mixer.music.stop()
                completed = False
                break
            time.sleep(0.02)
        return completed
    finally:
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass
        try:
            os.remove(temp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Barge-in
# ---------------------------------------------------------------------------

def _normalize_interim(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _interims_are_related(previous: str, current: str) -> bool:
    """
    Deepgram interim results normally grow/revise as speech continues.
    Count them as the same candidate only when one substantially extends the
    other or they share a meaningful prefix.
    """
    if not previous or not current:
        return False
    if previous in current or current in previous:
        return True

    prev_words = previous.split()
    curr_words = current.split()
    if prev_words and curr_words and prev_words[0] == curr_words[0]:
        return True
    return False


class BargeInListener:
    """Keep the selected physical microphone open while TTS is playing."""

    def __init__(self):
        self.interrupt_event = threading.Event()
        self.utterance_done = threading.Event()
        self.got_any_speech = threading.Event()

        self.final_pieces = []
        self.latest_interim = ""

        self._connection = None
        self._microphone = None
        self._started_at = None
        self._closed = False

        self._candidate_interim = ""
        self._candidate_confirmations = 0

    def _past_grace(self) -> bool:
        if self._started_at is None:
            return False
        return (
            (time.monotonic() - self._started_at) * 1000
            >= BARGE_IN_GRACE_MS
        )

    def _consider_interim_for_interrupt(self, transcript: str):
        normalized = _normalize_interim(transcript)
        if len(normalized) < BARGE_IN_INTERIM_MIN_CHARS:
            return

        if _interims_are_related(self._candidate_interim, normalized):
            self._candidate_confirmations += 1
        else:
            self._candidate_interim = normalized
            self._candidate_confirmations = 1

        if (
            self._past_grace()
            and self._candidate_confirmations >= BARGE_IN_INTERIM_CONFIRMATIONS
        ):
            self.interrupt_event.set()

    def start(self):
        print_selected_input_device()

        client = get_deepgram_client()
        dg_connection = client.listen.websocket.v("1")
        self._connection = dg_connection

        def on_open(_, open=None, **kwargs):
            pass

        def on_speech_started(_, speech_started=None, **kwargs):
            self.got_any_speech.set()
            # Raw VAD is intentionally OFF by default because keyboard noise,
            # mic bumps, and monitor/loopback sources can trigger it.
            if BARGE_IN_ON_VAD and self._past_grace():
                self.interrupt_event.set()

        def on_message(_, result=None, **kwargs):
            if result is None:
                return

            global LAST_STT_CONFIDENCE
            alt = result.channel.alternatives[0]
            transcript = alt.transcript
            if result.is_final:
                try:
                    LAST_STT_CONFIDENCE = float(getattr(alt, "confidence", None))
                except (TypeError, ValueError):
                    LAST_STT_CONFIDENCE = None
            if not transcript:
                return

            transcript = transcript.strip()
            self.got_any_speech.set()
            self.latest_interim = transcript

            if result.is_final:
                self.final_pieces.append(transcript)

                # A finalized non-empty phrase is strong evidence that the
                # caller actually spoke. Interrupt even if interim stability
                # was not reached first.
                if self._past_grace():
                    self.interrupt_event.set()

                if result.speech_final:
                    self.utterance_done.set()
            else:
                self._consider_interim_for_interrupt(transcript)

        def on_utterance_end(_, utterance_end=None, **kwargs):
            # Do NOT promote a raw interim hypothesis into a caller turn.
            if self.final_pieces:
                self.utterance_done.set()

        def on_error(_, error=None, **kwargs):
            print(f"  [live_audio_io] Deepgram barge-in error: {error}")
            self.utterance_done.set()

        dg_connection.on(LiveTranscriptionEvents.Open, on_open)
        dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        dg_connection.on(
            LiveTranscriptionEvents.SpeechStarted,
            on_speech_started,
        )
        dg_connection.on(
            LiveTranscriptionEvents.UtteranceEnd,
            on_utterance_end,
        )
        dg_connection.on(LiveTranscriptionEvents.Error, on_error)

        options = LiveOptions(
            model=DEEPGRAM_MODEL,
            language=DEEPGRAM_LANGUAGE,
            smart_format=True,
            numerals=True,
            keyterm=DEEPGRAM_KEYTERMS or None,
            interim_results=True,
            utterance_end_ms=os.getenv(
                "LIVE_UTTERANCE_END_MS",
                "1200",
            ),
            vad_events=True,
            endpointing=int(
                os.getenv("LIVE_BARGE_IN_ENDPOINTING_MS", "700")
            ),
            encoding=MIC_ENCODING,
            sample_rate=MIC_SAMPLE_RATE,
            channels=MIC_CHANNELS,
        )

        if not dg_connection.start(options):
            raise RuntimeError(
                "Failed to open Deepgram barge-in connection."
            )

        self._microphone = LocalMicrophone(
            dg_connection.send,
            rate=MIC_SAMPLE_RATE,
            channels=MIC_CHANNELS,
        ).start()
        self._started_at = time.monotonic()

        return self

    def wait_for_transcript(
        self,
        timeout_s: float = BARGE_IN_FINAL_WAIT_S,
    ) -> Optional[str]:
        """
        Wait for FINAL Deepgram caller text.

        By default an unstable interim is never sent to LangGraph. This keeps
        stray preliminary hypotheses from becoming fake customer turns.
        """
        self.utterance_done.wait(timeout=timeout_s)

        transcript = " ".join(
            piece.strip()
            for piece in self.final_pieces
            if piece.strip()
        ).strip()

        if transcript:
            return transcript

        if BARGE_IN_ALLOW_INTERIM_FALLBACK:
            return self.latest_interim.strip() or None

        return None

    def stop(self):
        if self._closed:
            return
        self._closed = True

        if self._microphone is not None:
            try:
                self._microphone.finish()
            except Exception:
                pass

        if self._connection is not None:
            try:
                self._connection.finish()
            except Exception:
                pass

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False


# ---------------------------------------------------------------------------
# Normal live listening
# ---------------------------------------------------------------------------

def listen_for_utterance(
    timeout_s: float = DEFAULT_LISTEN_TIMEOUT_S,
) -> Optional[str]:
    """Capture one complete user utterance from the selected microphone."""
    print_selected_input_device()

    client = get_deepgram_client()
    dg_connection = client.listen.websocket.v("1")

    utterance_done = threading.Event()
    final_pieces = []
    got_any_speech = threading.Event()

    def on_open(_, open=None, **kwargs):
        pass

    def on_message(_, result=None, **kwargs):
        if result is None:
            return

        global LAST_STT_CONFIDENCE
        alt = result.channel.alternatives[0]
        transcript = alt.transcript
        if result.is_final:
            try:
                LAST_STT_CONFIDENCE = float(getattr(alt, "confidence", None))
            except (TypeError, ValueError):
                LAST_STT_CONFIDENCE = None
        if not transcript:
            return

        got_any_speech.set()

        if result.is_final:
            final_pieces.append(transcript.strip())
            if result.speech_final:
                utterance_done.set()

    def on_utterance_end(_, utterance_end=None, **kwargs):
        if final_pieces:
            utterance_done.set()

    def on_error(_, error=None, **kwargs):
        print(f"  [live_audio_io] Deepgram error: {error}")
        utterance_done.set()

    dg_connection.on(LiveTranscriptionEvents.Open, on_open)
    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
    dg_connection.on(
        LiveTranscriptionEvents.UtteranceEnd,
        on_utterance_end,
    )
    dg_connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model=DEEPGRAM_MODEL,
        language=DEEPGRAM_LANGUAGE,
        smart_format=True,
        numerals=True,
        keyterm=DEEPGRAM_KEYTERMS or None,
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

    microphone = LocalMicrophone(
        dg_connection.send,
        rate=MIC_SAMPLE_RATE,
        channels=MIC_CHANNELS,
    ).start()

    print("Listening... (speak now)")
    finished_in_time = utterance_done.wait(timeout=timeout_s)

    microphone.finish()
    dg_connection.finish()

    if not finished_in_time and not got_any_speech.is_set():
        print(
            f"  [live_audio_io] No speech detected in "
            f"{timeout_s:.0f}s, listening again."
        )
        return None

    transcript = " ".join(
        piece.strip()
        for piece in final_pieces
        if piece.strip()
    ).strip()
    return transcript or None
