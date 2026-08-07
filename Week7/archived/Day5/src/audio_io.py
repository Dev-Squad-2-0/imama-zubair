"""
Day 5 integration - STT + TTS, backend-only.

Consolidates the genuinely-reused audio helpers that used to live in
old_agent/voice_pipeline.py (sentence splitting, emotion tagging, the Fish
Audio TTS call) into one focused module, imported only by api.py (the
FastAPI backend) - never by app.py (the Streamlit UI), which only ever
talks to the backend over HTTP. Two real fixes live here that voice_pipeline
never had:

  1. STT switches from a live-streaming Deepgram websocket (needs a
     background thread pumping mic frames, awkward to run inside a
     request/response HTTP endpoint) to Deepgram's batch/prerecorded
     endpoint - a perfect fit for push-to-talk, which always hands over one
     complete recorded clip at a time.
  2. TTS gets real speed/latency tuning verified against Fish Audio's own
     documented /v1/tts request schema (prosody.speed, latency mode,
     temperature) - see tts_stream_audio()'s docstring for what each one
     does and why. The [emotion] bracket-tag syntax already in use
     (_apply_emotion_tag) is confirmed correct for the s2.1-pro-free model
     in use here, so it's kept as-is, not touched.

listen_live_utterance() and tts_synthesize_stream() (bottom of this file)
are the Day 3 Task 1 latency path instead - live Deepgram websocket STT
with tuned endpointing, and raw-PCM streaming TTS for incremental playback
- used by tests/test_streaming_voice_pipeline.py, not by api.py's
request/response endpoints.
"""

import os
import re
import threading
import time
import traceback
from typing import Iterator, List, Optional, Tuple

import requests
from dotenv import load_dotenv, find_dotenv
from deepgram import (  # type: ignore
    DeepgramClient, PrerecordedOptions, FileSource,
    LiveOptions, LiveTranscriptionEvents, Microphone,
)

load_dotenv(find_dotenv())

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
# nova-3 supports Urdu natively (language=ur) - without this, transcribe_file()
# defaults to English.
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "ur")

FISH_API_KEY = os.getenv("FISH_AUDIO_API_KEY")
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "")  # reference_id of the cloned/selected voice
FISH_MODEL = os.getenv("FISH_MODEL", "s2.1-pro-free")
# Speaking-rate multiplier Fish Audio's /v1/tts accepts under prosody.speed
# (documented valid range 0.5-2.0, default 1.0) - the "speaks a little slow"
# complaint had no lever to pull before, since the old payload never sent
# this field at all.
FISH_TTS_SPEED = float(os.getenv("FISH_TTS_SPEED", "1.15"))

# Live-STT endpointing tuning (Day 3 Task 1: keep first-audio-out under
# 2000ms) - how long Deepgram waits in silence before deciding the customer
# has stopped talking. Lower = faster turn-taking, more risk of cutting off
# a mid-sentence pause; these defaults match what's already proven to work
# in this project (old_agent/live_voice_pipeline.py used the same values).
DEEPGRAM_ENDPOINTING_MS = int(os.getenv("DEEPGRAM_ENDPOINTING_MS", "300"))
DEEPGRAM_UTTERANCE_END_MS = os.getenv("DEEPGRAM_UTTERANCE_END_MS", "1000")
_MIC_SAMPLE_RATE = 16000
_MIC_ENCODING = "linear16"
_MIC_CHANNELS = 1

_deepgram_client: Optional[DeepgramClient] = None


def _get_deepgram_client() -> DeepgramClient:
    global _deepgram_client
    if _deepgram_client is None:
        if not DEEPGRAM_API_KEY:
            raise RuntimeError("DEEPGRAM_API_KEY is not set. Set it in your .env before calling STT.")
        _deepgram_client = DeepgramClient(api_key=DEEPGRAM_API_KEY)
    return _deepgram_client


# ---------- Speech-to-Text (Deepgram, batch) ----------

def stt_transcribe(audio_bytes: bytes, mimetype: str = "audio/wav") -> Tuple[str, int]:
    """Batch (not streaming) Deepgram transcription of one complete audio
    clip - the natural fit for push-to-talk, where the browser hands over a
    finished recording rather than a live stream. Returns
    (transcript, latency_ms)."""
    client = _get_deepgram_client()
    start = time.monotonic()
    try:
        payload: FileSource = {"buffer": audio_bytes}
        options = PrerecordedOptions(model="nova-3", smart_format=True, language=DEEPGRAM_LANGUAGE)
        response = client.listen.rest.v("1").transcribe_file(
            payload, options, headers={"Content-Type": mimetype},
        )
        transcript = response.results.channels[0].alternatives[0].transcript
    except Exception as e:
        traceback.print_exc()
        raise RuntimeError(f"Deepgram STT failed: {e}") from e

    latency_ms = int((time.monotonic() - start) * 1000)
    return transcript, latency_ms


# ---------- Sentence splitting for TTS (no LLM call) ----------

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # pictographs, emoticons, transport, symbols
    "\U00002600-\U000027BF"  # misc symbols and dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicator flags
    "️"  # variation selector (emoji presentation)
    "]+",
    flags=re.UNICODE,
)


def _clean_for_speech(text: str) -> str:
    # strips emoji, markdown, list markers, and Devanagari (the LLM
    # sometimes drifts into Hindi script, which the Urdu voice can't speak)
    # before TTS
    text = _EMOJI_PATTERN.sub("", text)
    text = re.sub(r"[ऀ-ॿ]+", "", text)  # Devanagari script (Hindi, not Urdu)
    text = re.sub(r"(?m)^[ \t]*(\d+)\.[ \t]*\n*[ \t]*", r"\1) ", text)  # "1.\n\n**x" -> "1) **x"
    text = re.sub(r"(?m)^[ \t]*[-*][ \t]+", "", text)  # leading "- "/"* " bullet markers
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **bold**
    text = re.sub(r"__(.+?)__", r"\1", text)  # __bold__
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)  # *italic*
    text = re.sub(r"\n{2,}", ". ", text)  # paragraph break -> spoken pause
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    """Splits a reply into sentences for per-sentence TTS. Pure text
    splitting, no LLM call."""
    cleaned = _clean_for_speech(text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    return [s for s in sentences if s and re.search(r"\w", s, flags=re.UNICODE)]


# ---------- Emotion tagging for Fish Audio ([tag] syntax) ----------
# Fish Audio's S2/S2.1-Pro models read a leading `[emotion]` marker in
# square brackets and shift delivery accordingly (confirmed against Fish
# Audio's own docs - this is the correct syntax for s2.1-pro-free, unlike
# the older S1 model's (parenthesis) tags). Punctuation/keyword heuristic
# only, applied to the TTS copy, never to what's shown/logged as the reply.

_URDU_QUESTION_WORDS = re.compile(
    r"\b(kya|kaisa|kaisi|kaise|kab|kahan|kyun|kyu|kitna|kitni|kitne|konsa|konsi|kaun)\b",
    re.IGNORECASE,
)
_GRATITUDE_WORDS = re.compile(r"\b(shukriya|shukria|thank you|thanks)\b", re.IGNORECASE)


def _emotion_tag_for_sentence(sentence: str) -> Optional[str]:
    stripped = sentence.strip()
    if not stripped:
        return None
    if _GRATITUDE_WORDS.search(stripped):
        return "grateful"
    if stripped.endswith("?") or _URDU_QUESTION_WORDS.search(stripped):
        return "curious"
    if stripped.endswith("!"):
        return "excited"
    return None


def apply_emotion_tag(sentence: str) -> str:
    tag = _emotion_tag_for_sentence(sentence)
    return f"[{tag}] {sentence}" if tag else sentence


# ---------- Text-to-Speech (Fish Audio) ----------

def tts_synthesize(text: str, voice_id: Optional[str] = None) -> Tuple[bytes, int]:
    """Real Fish Audio TTS call for one piece of text. Returns
    (audio_bytes, latency_to_first_byte_ms).

    Three tuning fields added here that the old payload never sent at all
    (verified against Fish Audio's own /v1/tts request schema docs, not
    guessed):
      - prosody.speed: speaking-rate multiplier (0.5-2.0, default 1.0) -
        directly addresses "speaks a little slow" by giving this an actual
        lever to pull (FISH_TTS_SPEED env var, default 1.15).
      - latency: "normal" (best quality, the old implicit default and the
        slowest option) / "balanced" / "low". "balanced" trades a small
        amount of quality for real synthesis-latency reduction - free
        latency the old payload was leaving on the table by never setting
        this field at all.
      - temperature: lowered from Fish Audio's own default (0.7) to 0.4 for
        more consistent, less "creative" delivery - relevant on
        Urdu-English-mixed text, where a higher-temperature model is more
        likely to drift on pronunciation.
    """
    if not FISH_API_KEY:
        raise RuntimeError("FISH_AUDIO_API_KEY is not set. Set it in your .env before calling TTS.")

    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": FISH_MODEL,
    }
    payload = {
        "text": text,
        "reference_id": voice_id or FISH_VOICE_ID,
        "format": "mp3",
        "prosody": {"speed": FISH_TTS_SPEED},
        "latency": "balanced",
        "temperature": 0.4,
    }

    start = time.monotonic()
    try:
        with requests.post(
            "https://api.fish.audio/v1/tts", headers=headers, json=payload, stream=True, timeout=15,
        ) as response:
            response.raise_for_status()
            chunks = []
            first_byte_latency_ms = None
            for chunk in response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                if first_byte_latency_ms is None:
                    first_byte_latency_ms = int((time.monotonic() - start) * 1000)
                chunks.append(chunk)
            audio_bytes = b"".join(chunks)
    except requests.RequestException as e:
        raise RuntimeError(f"Fish Audio TTS failed: {e}") from e

    if not audio_bytes:
        raise RuntimeError("Fish Audio TTS returned no audio data.")
    if first_byte_latency_ms is None:
        first_byte_latency_ms = int((time.monotonic() - start) * 1000)

    return audio_bytes, first_byte_latency_ms


def synthesize_reply(reply_text: str, voice_id: Optional[str] = None) -> Tuple[bytes, int]:
    """Synthesizes a full agent reply (possibly multiple sentences) into
    one playable MP3 and returns (audio_bytes, tts_ms). Sentences are
    synthesized concurrently (a small thread pool, not the old
    voice_pipeline.py's fully-serial request-then-play-then-request loop)
    so the total wall-clock cost is close to the slowest single sentence
    rather than the sum of all of them, then concatenated in the original
    order - MP3 frames concatenate cleanly enough for speech playback."""
    from concurrent.futures import ThreadPoolExecutor

    sentences = split_into_sentences(reply_text)
    if not sentences:
        raise RuntimeError("Nothing speakable in this reply after cleaning.")

    start = time.monotonic()
    tagged = [apply_emotion_tag(s) for s in sentences]
    with ThreadPoolExecutor(max_workers=min(4, len(tagged))) as pool:
        results = list(pool.map(lambda s: tts_synthesize(s, voice_id=voice_id), tagged))

    audio_bytes = b"".join(audio for audio, _ in results)
    tts_ms = int((time.monotonic() - start) * 1000)
    return audio_bytes, tts_ms


# ---------------------------------------------------------------------------
# Day 3 Task 1 latency path: live STT + streaming TTS. Separate from the
# batch functions above on purpose - api.py's /turn/audio endpoint hands
# over one already-finished recording per request/response cycle, which
# batch STT and a single buffered TTS response both fit naturally; a
# sub-2-second Speech -> LLM -> Voice budget instead needs the mic and the
# speaker both streaming continuously, which is what these two do.
# ---------------------------------------------------------------------------

def listen_live_utterance(timeout_s: float = 25.0) -> Optional[Tuple[str, int]]:
    """Opens the mic, streams audio to Deepgram's live websocket with tuned
    endpointing (DEEPGRAM_ENDPOINTING_MS/DEEPGRAM_UTTERANCE_END_MS) until
    Deepgram itself decides the utterance is complete, then returns
    (transcript, stt_ms). Returns None on timeout/no speech.

    stt_ms measures the endpointing decision itself - elapsed time between
    the last transcript update Deepgram sent (a proxy for "the moment the
    customer stopped talking") and the moment Deepgram confirms the
    utterance is done - not the whole time the customer spent talking. That's
    the number actually being tuned here; how long someone's sentence is
    isn't something endpointing settings can or should affect."""
    client = _get_deepgram_client()
    dg_connection = client.listen.live.v("1")

    utterance_done = threading.Event()
    got_any_speech = threading.Event()
    final_pieces: List[str] = []
    last_speech_ts = [None]
    utterance_done_ts = [None]

    def on_message(_, result=None, **kwargs):
        if result is None:
            return
        transcript = result.channel.alternatives[0].transcript
        if not transcript:
            return
        got_any_speech.set()
        last_speech_ts[0] = time.monotonic()
        if result.is_final:
            final_pieces.append(transcript)
            if result.speech_final and not utterance_done.is_set():
                utterance_done_ts[0] = time.monotonic()
                utterance_done.set()

    def on_utterance_end(_, utterance_end=None, **kwargs):
        # fires even when speech_final never triggered (e.g. trailing silence)
        if final_pieces and not utterance_done.is_set():
            utterance_done_ts[0] = time.monotonic()
            utterance_done.set()

    def on_error(_, error=None, **kwargs):
        utterance_done.set()

    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
    dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
    dg_connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model="nova-3", language=DEEPGRAM_LANGUAGE, smart_format=True,
        interim_results=True, utterance_end_ms=DEEPGRAM_UTTERANCE_END_MS,
        vad_events=True, endpointing=DEEPGRAM_ENDPOINTING_MS,
        encoding=_MIC_ENCODING, sample_rate=_MIC_SAMPLE_RATE, channels=_MIC_CHANNELS,
    )
    if not dg_connection.start(options):
        raise RuntimeError("Failed to open Deepgram live connection.")

    microphone = Microphone(dg_connection.send, rate=_MIC_SAMPLE_RATE, channels=_MIC_CHANNELS)
    microphone.start()
    finished_in_time = utterance_done.wait(timeout=timeout_s)
    microphone.finish()
    dg_connection.finish()

    if not finished_in_time and not got_any_speech.is_set():
        return None

    transcript = " ".join(p.strip() for p in final_pieces if p.strip()).strip()
    if not transcript:
        return None

    end_ts = utterance_done_ts[0] or time.monotonic()
    start_ts = last_speech_ts[0] or end_ts
    stt_ms = max(int((end_ts - start_ts) * 1000), 0)
    return transcript, stt_ms


def tts_synthesize_stream(text: str, voice_id: Optional[str] = None,
                           sample_rate: int = 44100) -> Iterator[Tuple[bytes, int]]:
    """Streams raw 16-bit PCM chunks from Fish Audio as they arrive, for
    true incremental playback - callers write each chunk to a speaker
    output stream as it's yielded instead of waiting for the whole
    sentence's audio to finish downloading (what tts_synthesize()/
    synthesize_reply() do, fine for a REST response body, too slow for a
    live conversation). Requests "latency": "low" here specifically
    (tts_synthesize() uses "balanced") since this path only exists for the
    Day 3 Task 1 sub-2-second budget - trading a little synthesis quality
    for speed is the right call here in a way it isn't for the batch path.

    Yields (chunk_bytes, ms_since_call) - the first chunk's ms_since_call
    is "TTS time to first audio byte," the number that determines how soon
    the speaker can start."""
    if not FISH_API_KEY:
        raise RuntimeError("FISH_AUDIO_API_KEY is not set. Set it in your .env before calling TTS.")

    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": FISH_MODEL,
    }
    payload = {
        "text": text,
        "reference_id": voice_id or FISH_VOICE_ID,
        "format": "pcm",
        "sample_rate": sample_rate,
        "prosody": {"speed": FISH_TTS_SPEED},
        "latency": "low",
        "temperature": 0.4,
    }

    start = time.monotonic()
    try:
        with requests.post(
            "https://api.fish.audio/v1/tts", headers=headers, json=payload, stream=True, timeout=15,
        ) as response:
            response.raise_for_status()
            got_audio = False
            for chunk in response.iter_content(chunk_size=2048):
                if chunk:
                    got_audio = True
                    yield chunk, int((time.monotonic() - start) * 1000)
            if not got_audio:
                raise RuntimeError("Fish Audio TTS returned no audio data.")
    except requests.RequestException as e:
        raise RuntimeError(f"Fish Audio TTS failed: {e}") from e
