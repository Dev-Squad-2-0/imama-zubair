"""
Day 3 - Task 1: Streaming Voice Pipeline (production)

Speech -> LLM -> Voice, target end-to-end latency under 2 seconds.

Real pipeline:
    Customer audio -> Deepgram (STT) -> [conversation_agent.py composes reply
    using memory + retrieval + objection handling] -> Edge TTS (TTS) -> caller

This file owns the STT and TTS legs and the latency accounting. It does NOT
own reply generation: conversation_agent.py is the source of truth for what
the agent says (memory, structured retrieval, recommendation engine,
objection strategy, persona all live there). That split matters here because
when `run_voice_turn()` is called WITH an `agent_reply_text` (this is how
conversation_agent.py calls it during a live/simulated call), that text is
already-decided and must be spoken as-is — this file must not re-run it
through the LLM as if it were a fresh instruction, or it would speak a
different sentence than conversation_agent.py just decided on, silently
bypassing objection handling / guardrails already applied upstream.
Sentence-splitting for TTS streaming is done locally with a regex, no LLM
call involved.

For OFFLINE END-TO-END TESTING (this file run directly, or `run_voice_turn()`
called with `agent_reply_text=None`), the story is different on purpose: with
no live orchestrator driving the call, `run_voice_turn()` transcribes the
given audio, then drives conversation_agent.py's reply generation itself
(lazy import — see `_generate_conversation_reply()` — to avoid a circular
import with conversation_agent.py, which imports this module at the top
level) before synthesizing and saving the spoken reply. This mode exists for
testing this file standalone against `sample_audio/*.wav`, not for the live
call path.

The LLM is also wired up for real in this file (`generate_llm_reply_stream()`),
kept as a standalone, explicitly-invoked function rather than something
run_voice_turn() calls automatically in the live-call path. It's the
integration point for Day 4, when conversation_agent.py's template-based
`_compose_reply()` is replaced with a real LLM call — at that point
conversation_agent.py calls `generate_llm_reply_stream()` itself and passes
the resulting text into `run_voice_turn()`, same as it does today with
template text.

LATENCY BUDGET (target: under 2000ms first-audio-out)
    STT                                          ~150-300ms  (real Deepgram)
    Reply composition (template or LLM)          owned by conversation_agent.py, not timed here
    TTS first audio chunk (streaming)             ~150-500ms  (real Edge TTS, varies with text length)
    Network/telephony overhead (Twilio media)     not wired up yet, see telephony_send_audio()
    ---------------------------------------------------------
    Total to FIRST AUDIO CHUNK reported by run_voice_turn() = STT + TTS-to-first-sentence

    A NOTE ON THAT ~150-500ms NUMBER: if you're seeing ~2.5s to first audio
    chunk in practice, that is NOT this code buffering the whole MP3 before
    reporting latency — verified against edge-tts 7.2.8's source
    (communicate.py: `yield {"type": "audio", "data": data}` fires per
    websocket frame as it arrives, and `tts_stream_audio()` below records
    the timestamp at the FIRST such frame, not after the loop finishes).
    What's actually being measured in that case is real one-time connection
    setup cost: DNS + TLS handshake + Azure's websocket negotiation, paid in
    full on every call since edge-tts opens a fresh connection per
    `Communicate` instance (no session reuse). That cost is highest on the
    very first TTS call in a process and on slow/proxied networks. Two
    concrete things that help:
      - call `warmup_tts()` once at process/call-session startup (see below)
        to pay that cost before you start timing real turns
      - set `EDGE_TTS_DEBUG=1` to log per-chunk arrival timestamps and see
        exactly where the time is going on your network

INTEGRATION POINTS NOT WIRED UP IN THIS DEMO (kept clearly separate so they
can be dropped in without touching the rest of the pipeline):
    - Live microphone / raw audio capture -> call `stt_transcribe()` with
      real audio bytes instead of text (see docstring on that function).
    - Live streaming STT over a websocket (partial transcripts while the
      caller is still talking) -> `stt_transcribe()` currently uses
      Deepgram's REST prerecorded endpoint against a full audio buffer,
      correct for a captured clip but not for a live in-progress stream.
      Swap in `deepgram.listen.websocket.v("1")` for that; the "returns
      final transcript + latency" contract stays the same from the caller's
      side.
    - Twilio Media Streams playback -> `telephony_send_audio()` is a stub
      that raises NotImplementedError on purpose, so a missing integration
      fails loudly instead of silently pretending audio was delivered.
"""

import os
import re
import sys
import time
import traceback
import requests
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from deepgram import DeepgramClient, PrerecordedOptions, FileSource

load_dotenv()

# Replies are natural Urdu/UrduLish and routinely contain characters outside
# cp1252 (Windows' default console/file encoding), e.g. non-breaking hyphens
# or Urdu script the LLM sometimes mixes in. Printing/writing that text with
# the default locale encoding raises UnicodeEncodeError mid-call instead of
# just displaying it, so stdout/stderr are reconfigured to UTF-8 up front.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sample_audio")
GENERATED_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "generated_audio")
# Separate from GENERATED_AUDIO_DIR on purpose: run_voice_turn()'s turn_NNN
# filenames come from a per-process counter that restarts at turn_001 every
# run, so a standalone `python voice_pipeline.py` run (this file's own
# offline test / --single demo) would otherwise silently overwrite whatever
# eval/sample_conversations.py's live-call-path run left in GENERATED_AUDIO_DIR.
OFFLINE_TEST_AUDIO_DIR = os.path.join(GENERATED_AUDIO_DIR, "offline_test")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
# nova-3 supports Urdu natively (language=ur) — without this, transcribe_file()
# defaults to English and returns empty/garbled transcripts for Urdu-script
# audio (confirmed against sample_audio/: every file transcribed as '' or a
# handful of wrong English words until this was set).
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "ur")
FISH_API_KEY = os.getenv("FISH_AUDIO_API_KEY")  # currently unused, kept for Fish Audio restoration
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "")  # reference_id of the cloned/selected voice, unused for now
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")

# Clients are created lazily (on first real use) rather than at import time.
# This keeps `import voice_pipeline` safe even if one of the three API keys
# isn't set yet in a given environment (e.g. running just the memory/objection
# demos), while still failing loudly with a clear error the moment a function
# that actually needs that client gets called.
_deepgram_client: Optional[DeepgramClient] = None
_llm_client = None


def _get_deepgram_client() -> DeepgramClient:
    global _deepgram_client
    if _deepgram_client is None:
        if not DEEPGRAM_API_KEY:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is not set. Set it in your .env before calling "
                "any STT function."
            )
        _deepgram_client = DeepgramClient(api_key=DEEPGRAM_API_KEY)
    return _deepgram_client


def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        if not BASE_URL or not API_KEY:
            raise RuntimeError(
                "BASE_URL / API_KEY are not set. Set them in your .env before "
                "calling generate_llm_reply_stream()."
            )
        _llm_client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    return _llm_client


# ---------- Audio file helpers ----------

def load_audio_file(path: str):
    """Reads an audio file from disk and returns (audio_bytes, mimetype).
    Mimetype is guessed from the extension since that's all Deepgram needs
    for the prerecorded REST endpoint."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Audio file not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    mimetype = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }.get(ext, "audio/wav")

    with open(path, "rb") as f:
        audio_bytes = f.read()
    return audio_bytes, mimetype


def _looks_like_audio_file_path(value) -> bool:
    """Distinguishes 'this string is a path to an audio file on disk' from
    'this string is already-transcribed customer text' (the existing usage
    from conversation_agent.py). Deliberately conservative: only treated as
    a file path if it has a known audio extension AND actually exists,
    so ordinary transcript text is never mistaken for a path."""
    if not isinstance(value, str):
        return False
    ext = os.path.splitext(value)[1].lower()
    return ext in (".wav", ".mp3", ".m4a", ".ogg", ".flac") and os.path.exists(value)


# ---------- Speech-to-Text (Deepgram) ----------

def stt_transcribe(audio_bytes: bytes, mimetype: str = "audio/wav"):
    """
    Real Deepgram transcription of a captured audio buffer (v1 REST batch
    endpoint — this expects a complete audio clip, e.g. one turn's worth of
    caller audio already captured by the telephony layer, not a live
    in-progress stream). Returns (transcript, latency_ms).

    Verified against deepgram-sdk 3.7.7 (the version pinned in
    requirements.txt) — this is `client.listen.rest.v("1").transcribe_file()`
    with `PrerecordedOptions` / `FileSource`, the correct call shape for this
    SDK version. `mimetype` is passed through as a `Content-Type` header
    override (via `transcribe_file(..., headers={...})`) since this SDK
    sends `application/octet-stream` by default for raw bytes; Deepgram's
    backend can usually still sniff common containers like WAV/MP3 correctly
    either way, but passing the real content-type is more correct when it's
    known (e.g. loaded from a file with a known extension).

    For low-latency live streaming (partial transcripts while the caller is
    still speaking), use `client.listen.v1.connect(...)` instead — that's a
    separate, callback-based integration path and out of scope for this
    file; wiring it in doesn't change the STT latency accounting done here,
    only how the transcript arrives.
    """
    client = _get_deepgram_client()
    start = time.monotonic()
    try:
            payload: FileSource = {
                "buffer": audio_bytes,
            }

            options = PrerecordedOptions(
                model="nova-3",
                smart_format=True,
                language=DEEPGRAM_LANGUAGE,
            )

            response = client.listen.rest.v("1").transcribe_file(
                payload,
                options,
                headers={"Content-Type": mimetype},
            )

            transcript = (
                response.results
                .channels[0]
                .alternatives[0]
                .transcript
            )

    except Exception as e:
            traceback.print_exc()
            raise RuntimeError(f"Deepgram STT failed: {e}") from e

    latency_ms = int((time.monotonic() - start) * 1000)
    return transcript, latency_ms


# ---------- Reply generation (LLM) — Day 4 integration point ----------

def generate_llm_reply_stream(prompt: str, model: str = "smart"):
    """
    Real streaming LLM call, kept separate from run_voice_turn() on purpose
    (see module docstring). Yields (sentence, latency_ms) tuples, so a caller
    can start TTS on the first sentence while the rest is still generating.

    Not called anywhere in the current Day 3 pipeline —
    conversation_agent.py still composes replies from templates
    (`_compose_reply()`). This is the ready-to-use integration point for
    when that changes: conversation_agent.py would call this with a prompt
    built from persona + system prompt + conversation slots + retrieved
    facts + objection strategy, then pass the assembled text into
    run_voice_turn() exactly as it does today.
    """
    client = _get_llm_client()
    start = time.monotonic()
    sentence = ""
    try:
        stream = client.chat.completions.create(
            model=model,
            stream=True,
            messages=[{"role": "user", "content": prompt}],
        )
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            sentence += token
            if token.strip().endswith((".", "?", "!")):
                latency_ms = int((time.monotonic() - start) * 1000)
                yield sentence.strip(), latency_ms
                sentence = ""
                start = time.monotonic()
        if sentence.strip():
            yield sentence.strip(), int((time.monotonic() - start) * 1000)
    except Exception as e:
        traceback.print_exc()
        raise RuntimeError(f"LLM streaming failed: {e}") from e


# ---------- Sentence splitting for TTS streaming (no LLM call) ----------

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
    """Strips formatting that reads fine as text on a screen but breaks or
    sounds wrong when spoken aloud by TTS:
      - emoji: seen in practice to make Edge TTS raise NoAudioReceived when
        a sentence is emoji-only (nothing phonetic to synthesize) — see
        tts_stream_audio()'s retry docstring, this is the actual fix, retries
        alone don't help since it's not transient.
      - markdown bold/italic markers (**text**, __text__, *text*): would
        otherwise be read literally as "asterisk asterisk" by a naive TTS
        pass-through, or just sound like stray noise.
      - numbered/bulleted list markers ("1. ", "- "): a bare "1." at the
        start of a line both gets read as "one dot" on its own and, worse,
        its trailing period is indistinguishable from a sentence boundary to
        _split_into_sentences() below, splitting the number away from the
        item it labels (that's why isolated "2." / "3." sentences showed up
        in early transcripts). Merged into the following text instead.
      - Devanagari script (Hindi, e.g. "धन्यवाद"): a different Unicode block
        entirely from Urdu's Arabic/Nastaliq script (اردو) — Urdulish is
        Urdu (Roman-transliterated OR Arabic-script, both are left alone
        here) plus English, never Devanagari, which belongs to Hindi. The
        LLM occasionally drifts into it for common words ("thanks" etc.)
        despite the persona, and EDGE_DEFAULT_VOICE (a Pakistani Urdu voice)
        genuinely can't synthesize it — confirmed non-transient, the same
        text fails Edge TTS's NoAudioReceived check identically on every
        retry, so this strips it rather than retrying uselessly.
    The LLM is asked for natural spoken UrduLish, not markdown, but models
    reliably slip into list/emphasis formatting for anything list-shaped —
    this is the boundary that keeps that from reaching the caller's ear.
    """
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


def _split_into_sentences(text: str):
    """Splits an already-composed reply into sentence-sized pieces so TTS can
    start on the first sentence while later ones are still being synthesized.
    Pure text splitting, no model call — see module docstring for why this
    must not go through the LLM again. Runs _clean_for_speech() first so list
    numbering and emphasis markers don't create false sentence boundaries or
    empty/symbol-only fragments (see that function's docstring), then drops
    any leftover fragment with no alphanumeric content as a safety net."""
    cleaned = _clean_for_speech(text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    return [s for s in sentences if s and re.search(r"\w", s, flags=re.UNICODE)]


# ---------- Text-to-Speech (Edge TTS) ----------
#
# Switched from Fish Audio to Microsoft Edge TTS: Fish Audio requires a paid
# subscription, Edge TTS is free (it uses the same voice service behind
# Microsoft Edge's "Read Aloud" feature, no API key needed). The Fish Audio
# implementation is kept below, commented out, so it can be restored later
# by uncommenting it and renaming `_tts_stream_audio_edge` back to
# `tts_stream_audio` (or just flipping which one is active — see the
# assignment at the bottom of this section).
#
# Edge TTS's Python SDK (`edge-tts`) is async-only (`edge_tts.Communicate`).
# The rest of this pipeline is sync, and the public interface of
# `tts_stream_audio()` must stay sync too (conversation_agent.py and
# run_voice_turn() below both call it as a plain blocking function). So the
# async work is run to completion internally with `asyncio.run()` inside a
# sync wrapper — nothing outside this function needs to know it's async
# under the hood.

import asyncio
import edge_tts

EDGE_DEFAULT_VOICE = os.getenv("EDGE_TTS_VOICE", "ur-PK-AsadNeural")
EDGE_TTS_DEBUG = os.getenv("EDGE_TTS_DEBUG", "").lower() in ("1", "true", "yes")
print(f"Using Edge TTS voice: {EDGE_DEFAULT_VOICE} (set EDGE_TTS_VOICE in .env to change)")
# ur-PK-AsadNeural / ur-PK-UzmaNeural are the two Urdu (Pakistan) neural
# voices Edge TTS ships. Neither one is UrduLish-native the way Fish Audio's
# cloned voice was, so this is a straight swap for functionality, not a
# perfect voice match — worth a listen before going to production.

_tts_warmed_up = False


async def _edge_tts_collect(text: str, voice: str):
    """Streams synthesized audio chunks from Edge TTS and returns
    (audio_bytes, latency_to_first_chunk_ms). Latency is recorded at the
    FIRST `{"type": "audio"}` message that arrives over the websocket, not
    after the whole response is collected — see the module docstring's note
    on the ~2.5s question for how this was verified against edge-tts's
    source. With EDGE_TTS_DEBUG=1, every chunk's arrival time (relative to
    the start of this call) is printed, so a real multi-second gap before
    the first audio chunk is directly visible rather than assumed."""
    start = time.monotonic()
    communicate = edge_tts.Communicate(text, voice)
    chunks = []
    first_chunk_latency_ms = None
    chunk_index = 0
    async for chunk in communicate.stream():
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if EDGE_TTS_DEBUG:
            size = len(chunk.get("data", b"")) if chunk["type"] == "audio" else 0
            print(f"  [edge-tts] +{elapsed_ms}ms chunk#{chunk_index} type={chunk['type']} bytes={size}")
        chunk_index += 1
        if chunk["type"] == "audio":
            if first_chunk_latency_ms is None:
                first_chunk_latency_ms = elapsed_ms
            chunks.append(chunk["data"])
    audio_bytes = b"".join(chunks)
    if first_chunk_latency_ms is None:
        first_chunk_latency_ms = int((time.monotonic() - start) * 1000)
    return audio_bytes, first_chunk_latency_ms


def warmup_tts(voice: Optional[str] = None):
    """
    Pays Edge TTS's one-time connection setup cost (DNS + TLS handshake +
    websocket negotiation) up front with a throwaway synthesis call, before
    any real conversation turn is timed. edge-tts opens a fresh connection
    per `Communicate` instance rather than reusing a session, so that setup
    cost lands in full on whichever call happens to go first — in a live
    call, that's the customer's first reply, which is exactly the number
    you don't want inflated. Call this once when a call/session starts (or
    once at process startup for a long-running service) rather than
    treating its latency as representative of steady-state performance.

    Safe to skip; just means the first real tts_stream_audio() call pays
    the connection cost instead.
    """
    global _tts_warmed_up
    try:
        tts_stream_audio("hi", voice_id=voice)
        _tts_warmed_up = True
    except Exception as e:
        traceback.print_exc()
        # Don't let a warmup failure block real calls — the real call will
        # surface the same error with proper context if it's still broken.
        print(f"TTS warmup call failed (non-fatal, continuing): {e}")


EDGE_TTS_MAX_RETRIES = int(os.getenv("EDGE_TTS_MAX_RETRIES", "3"))
EDGE_TTS_RETRY_BACKOFF_S = 0.5  # doubles each retry: 0.5s, 1s, 2s...


def tts_stream_audio(text: str, voice_id: Optional[str] = None):
    """
    Real Edge TTS call (sync wrapper around the async `edge-tts` SDK).
    Measures time-to-first-audio-chunk as the reported latency (what
    actually matters for "does the caller hear something soon"), while
    still returning the full synthesized audio for this sentence so it can
    be played/queued. See the module docstring for why a slow first call is
    connection setup cost, not this function buffering the whole response —
    and consider calling `warmup_tts()` once per call/session to avoid that
    cost landing on a real timed turn.

    voice_id here is an Edge TTS voice name (e.g. "ur-PK-AsadNeural"), not a
    Fish Audio reference_id — same parameter slot, different meaning, kept
    so the function signature didn't need to change.

    Retries on transient failures (e.g. edge-tts's `NoAudioReceived`, seen in
    practice on isolated short sentences against Microsoft's websocket
    endpoint with no server-side explanation) with a short exponential
    backoff, since edge-tts opens a fresh, unauthenticated websocket per call
    with no retry of its own — a single dropped connection would otherwise
    kill the rest of the caller's reply mid-sentence, which reads as a
    dropped call to the customer. Only raises once retries are exhausted.

    Returns (audio_bytes, latency_to_first_chunk_ms).
    """
    voice = voice_id or EDGE_DEFAULT_VOICE
    last_error = None
    for attempt in range(1, EDGE_TTS_MAX_RETRIES + 1):
        try:
            audio_bytes, latency_ms = asyncio.run(_edge_tts_collect(text, voice))
            if not audio_bytes:
                raise RuntimeError("Edge TTS returned no audio data.")
            return audio_bytes, latency_ms
        except Exception as e:
            last_error = e
            if attempt < EDGE_TTS_MAX_RETRIES:
                backoff_s = EDGE_TTS_RETRY_BACKOFF_S * (2 ** (attempt - 1))
                print(f"  [edge-tts] attempt {attempt}/{EDGE_TTS_MAX_RETRIES} failed "
                      f"({e}), retrying in {backoff_s}s...")
                time.sleep(backoff_s)

    traceback.print_exception(type(last_error), last_error, last_error.__traceback__)
    raise RuntimeError(f"Edge TTS failed after {EDGE_TTS_MAX_RETRIES} attempts: {last_error}") from last_error




# ---------- Text-to-Speech (Fish Audio) — DISABLED, kept for restoration ----------
#
# def tts_stream_audio(text: str, voice_id: Optional[str] = None):
#     """
#     Real Fish Audio TTS call. Streams the HTTP response body and measures
#     time-to-first-byte as the reported latency (what actually matters for
#     "does the caller hear something soon"), while still returning the full
#     synthesized audio for this sentence so it can be played/queued.
#
#     Returns (audio_bytes, latency_to_first_byte_ms).
#     """
#     if not FISH_API_KEY:
#         raise RuntimeError("FISH_AUDIO_API_KEY is not set. Set it in your .env before calling TTS.")
#
#     headers = {
#         "Authorization": f"Bearer {FISH_API_KEY}",
#         "Content-Type": "application/json",
#     }
#     payload = {
#         "text": text,
#         "reference_id": voice_id or FISH_VOICE_ID,
#         "format": "mp3",
#     }
#
#     start = time.monotonic()
#     try:
#         with requests.post(
#             "https://api.fish.audio/v1/tts",
#             headers=headers,
#             json=payload,
#             stream=True,
#             timeout=15,
#         ) as response:
#             response.raise_for_status()
#             chunks = []
#             first_byte_latency_ms = None
#             for chunk in response.iter_content(chunk_size=4096):
#                 if not chunk:
#                     continue
#                 if first_byte_latency_ms is None:
#                     first_byte_latency_ms = int((time.monotonic() - start) * 1000)
#                 chunks.append(chunk)
#             audio_bytes = b"".join(chunks)
#     except requests.RequestException as e:
#         raise RuntimeError(f"Fish Audio TTS failed: {e}") from e
#
#     if not audio_bytes:
#         raise RuntimeError("Fish Audio TTS returned no audio data.")
#
#     if first_byte_latency_ms is None:
#         first_byte_latency_ms = int((time.monotonic() - start) * 1000)
#
#     return audio_bytes, first_byte_latency_ms


# ---------- Telephony (Twilio) — integration point, not wired up ----------

def telephony_send_audio(audio_bytes: bytes):
    """
    INTEGRATION POINT — not implemented in this demo. In production this
    pushes synthesized audio into the active Twilio <Stream> media websocket
    so the caller hears it. Raises on purpose rather than pretending audio
    was delivered, so a missing integration fails loudly instead of silently
    reporting a fake "success".

    Wiring this in later doesn't change anything upstream: TTS still returns
    audio bytes the same way, this function is just what ships them to the
    phone line, and `run_voice_turn()` already accounts for a telephony
    overhead line item in the latency report (currently 0, since there's no
    live call to measure against).
    """
    raise NotImplementedError(
        "Twilio Media Streams integration is not implemented in this demo. "
        "Wire this to your active Twilio <Stream> websocket to send `audio_bytes` "
        "to the caller."
    )


def telephony_overhead():
    """Real Twilio round-trip overhead once telephony_send_audio() is wired
    up and can be measured. Returns 0 for now rather than a guessed number,
    since there's no live call in this demo to time."""
    return 0


# ---------- Pipeline orchestration ----------

@dataclass
class TurnLatencyReport:
    stt_ms: int = 0
    llm_first_sentence_ms: int = 0
    tts_first_chunk_ms: int = 0
    telephony_ms: int = 0
    total_first_audio_ms: int = 0
    under_budget: bool = True
    per_sentence_ms: list = field(default_factory=list)
    audio_chunks: list = field(default_factory=list)  # bytes per sentence, real TTS output
    audio_file_paths: list = field(default_factory=list)  # saved mp3 paths, same order as audio_chunks
    transcript: str = ""  # customer transcript actually used for this turn
    reply_text: str = ""  # agent reply actually spoken this turn
    skipped_sentences: list = field(default_factory=list)  # (sentence, error) pairs TTS couldn't synthesize


_turn_counter = 0


def _next_turn_id() -> str:
    global _turn_counter
    _turn_counter += 1
    return f"turn_{_turn_counter:03d}"


def _generate_conversation_reply(customer_text: str) -> str:
    """
    Drives conversation_agent.py's reply generation for a single, isolated
    turn — used only in OFFLINE TEST mode (see module docstring), when
    run_voice_turn() is called without an agent_reply_text and has to come
    up with the reply itself instead of receiving one from a live
    orchestrator.

    Imported lazily, inside this function, specifically to avoid a circular
    import: conversation_agent.py does `from voice_pipeline import
    run_voice_turn` at its top level, so importing conversation_agent back
    at voice_pipeline.py's top level would deadlock the import graph. By the
    time this function actually runs, both modules have already finished
    loading, so the import below just reuses conversation_agent's
    already-loaded module object.

    Builds a fresh, single-turn ConversationMemory rather than reusing any
    session state — this is a standalone per-file test, not a multi-turn
    call, so there's no prior context to carry.
    """
    import conversation_agent as _ca

    memory = _ca.ConversationMemory()
    behaviors = _ca.SpeechBehaviorLayer()

    memory.add_turn("customer", customer_text)
    memory.update_from_customer_text(customer_text)

    reply_text, used_tool = _ca._generate_reply(customer_text, memory)
    spoken_text = behaviors.wrap_reply(
        reply_text, used_tool=used_tool, is_reasoning_heavy=used_tool
    )
    return spoken_text


def _save_audio_files(audio_chunks, turn_id: str, output_dir: str):
    """Saves each sentence's synthesized audio as its own MP3 file (Edge TTS
    already returns MP3-encoded bytes). Naive byte-concatenation of
    independently synthesized MP3 clips isn't a well-formed single MP3
    stream (each carries its own frame headers), so sentences are kept as
    separate files rather than joined into one — reliable playback matters
    more here than a single output file. Returns the list of saved paths,
    same order as audio_chunks."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, audio_bytes in enumerate(audio_chunks, start=1):
        path = os.path.join(output_dir, f"{turn_id}_sentence_{i:02d}.mp3")
        with open(path, "wb") as f:
            f.write(audio_bytes)
        paths.append(path)
    return paths


def run_voice_turn(customer_speech_text, agent_reply_text: Optional[str] = None,
                    budget_ms: int = 2000, save_audio: bool = True,
                    output_dir: str = GENERATED_AUDIO_DIR):
    """
    Runs one full conversational turn through the real STT/TTS pipeline and
    returns (latency_report, spoken_sentences) — same 2-tuple shape as
    before, so conversation_agent.py's existing call
    (`run_voice_turn(customer_text, spoken_text)`) needs no changes.

    customer_speech_text: one of
        - a path to an existing audio file (.wav/.mp3/.m4a/.ogg/.flac) — the
          file is loaded from disk and transcribed with real Deepgram STT.
          This is the offline-test path: point it at a file in
          sample_audio/.
        - raw audio bytes captured from the caller for this turn — also
          transcribed with real Deepgram STT.
        - a plain string that is NOT an existing file path — treated as
          already-transcribed text (this is how conversation_agent.py calls
          it today, since there's no live audio capture wired into that
          path yet). STT is skipped (stt_ms=0) rather than faked.

    agent_reply_text: one of
        - the full, already-composed text reply (what conversation_agent.py
          passes today) — spoken as-is via TTS. See module docstring for
          why it is deliberately NOT re-run through the LLM/pipeline here.
        - None — OFFLINE TEST mode. Requires customer_speech_text to be
          audio (file path or bytes) so there's a real transcript to work
          from. The transcript is passed through conversation_agent.py's
          reply generation (`_generate_conversation_reply()`) to produce
          the text that gets spoken. Used by this file's own `__main__`
          block against sample_audio/.

    save_audio / output_dir: when save_audio is True (default), each
    sentence's synthesized audio is written to output_dir as its own MP3
    file (see `_save_audio_files()`), and the saved paths are attached at
    report.audio_file_paths. Raw bytes are still attached at
    report.audio_chunks either way.
    """
    report = TurnLatencyReport()
    turn_id = _next_turn_id()

    # ---- resolve customer_speech_text into a transcript ----
    is_audio_input = _looks_like_audio_file_path(customer_speech_text) or isinstance(
        customer_speech_text, (bytes, bytearray)
    )

    if _looks_like_audio_file_path(customer_speech_text):
        audio_bytes, mimetype = load_audio_file(customer_speech_text)
        transcript, stt_ms = stt_transcribe(audio_bytes, mimetype=mimetype)
    elif isinstance(customer_speech_text, (bytes, bytearray)):
        transcript, stt_ms = stt_transcribe(customer_speech_text)
    else:
        # already-transcribed text supplied by the caller; nothing to time
        transcript, stt_ms = customer_speech_text, 0

    report.stt_ms = stt_ms
    report.transcript = transcript

    # ---- resolve agent_reply_text ----
    if agent_reply_text is None:
        if not is_audio_input:
            raise ValueError(
                "run_voice_turn(agent_reply_text=None) needs real audio input "
                "(a file path or bytes) to transcribe and reply to — got plain "
                "text with no reply supplied. Either pass agent_reply_text "
                "explicitly, or pass real audio for offline-test mode."
            )
        agent_reply_text = _generate_conversation_reply(transcript)

    report.reply_text = agent_reply_text
    candidate_sentences = _split_into_sentences(agent_reply_text)
    spoken_sentences = []  # only sentences that actually got synthesized, in order
    running_total = report.stt_ms
    first_sentence_done = False

    for sentence in candidate_sentences:
        print("=" * 80)
        print("TTS INPUT:")
        print(repr(sentence))
        print("=" * 80)
        try:
            audio_bytes, tts_ms = tts_stream_audio(sentence)
        except RuntimeError as e:
            # Edge TTS is an unofficial, undocumented API — Microsoft's
            # backend occasionally returns zero audio for a request that
            # completes cleanly (no connection error, no explanation), even
            # for valid short text (confirmed by reading edge_tts's own
            # source: this is NOT the retry-worthy transient case
            # tts_stream_audio() already retries — it's exhausted those
            # retries and still got nothing). One unspeakable sentence
            # shouldn't kill the rest of the reply / the whole call, so it's
            # logged and skipped rather than propagated.
            print(f"  [voice_pipeline] TTS could not synthesize this sentence after "
                  f"retries, skipping it and continuing: {e}")
            report.skipped_sentences.append((sentence, str(e)))
            continue

        spoken_sentences.append(sentence)
        report.audio_chunks.append(audio_bytes)

        if not first_sentence_done:
            report.tts_first_chunk_ms = tts_ms
            running_total += tts_ms

            tel_ms = telephony_overhead()
            report.telephony_ms = tel_ms
            running_total += tel_ms

            report.total_first_audio_ms = running_total
            report.under_budget = running_total < budget_ms
            first_sentence_done = True

        report.per_sentence_ms.append(tts_ms)

    if save_audio and report.audio_chunks:
        report.audio_file_paths = _save_audio_files(report.audio_chunks, turn_id, output_dir)

    return report, spoken_sentences


# ---------- Offline end-to-end test ----------

def run_offline_test(sample_audio_dir: str = SAMPLE_AUDIO_DIR,
                      output_dir: str = OFFLINE_TEST_AUDIO_DIR):
    """
    Runs every audio file in sample_audio_dir through the complete pipeline:
    load file -> Deepgram STT -> conversation_agent.py reply generation ->
    Edge TTS -> save MP3s to output_dir (defaults to OFFLINE_TEST_AUDIO_DIR,
    a subfolder of GENERATED_AUDIO_DIR — kept separate from the live-call
    path's output so this standalone test never overwrites turn_NNN files a
    real/eval-script call already saved there). No live phone call, no mocked
    stages — this is the "offline end-to-end test" entry point.

    Calls warmup_tts() once before the timed runs so the first sample's
    latency isn't inflated by one-time connection setup (see module
    docstring). Each sample's own latency is still reported individually.
    """
    if not os.path.isdir(sample_audio_dir):
        print(f"No sample_audio directory found at {sample_audio_dir}")
        return

    audio_files = sorted(
        f for f in os.listdir(sample_audio_dir)
        if os.path.splitext(f)[1].lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac")
    )
    if not audio_files:
        print(f"No audio files found in {sample_audio_dir}")
        return

    print(f"Warming up Edge TTS connection...")
    warmup_tts()

    results = []
    for filename in audio_files:
        path = os.path.join(sample_audio_dir, filename)
        print(f"\n{'=' * 70}\n{filename}\n{'=' * 70}")
        try:
            report, sentences = run_voice_turn(path, agent_reply_text=None,
                                                save_audio=True, output_dir=output_dir)
        except Exception as e:
            traceback.print_exc()
            print(f"  FAILED: {e}")
            results.append({"file": filename, "error": str(e)})
            continue

        print(f"Transcript (Deepgram): {report.transcript!r}")
        print(f"Reply (spoken):        {report.reply_text}")
        print(f"Latency to first audio: {report.total_first_audio_ms}ms "
              f"({'within' if report.under_budget else 'OVER'} 2000ms budget)")
        print(f"Saved audio: {report.audio_file_paths}")

        results.append({
            "file": filename,
            "transcript": report.transcript,
            "reply": report.reply_text,
            "latency_ms": report.total_first_audio_ms,
            "under_budget": report.under_budget,
            "audio_files": report.audio_file_paths,
        })

    print(f"\n{'=' * 70}\nSummary: {len(results)} sample(s) processed, "
          f"output saved to {output_dir}\n{'=' * 70}")
    return results


if __name__ == "__main__":
    # This demo calls real Deepgram/Edge TTS APIs. Deepgram needs a valid key
    # in your .env (DEEPGRAM_API_KEY); Edge TTS needs no API key at all.
    # Fails loudly with a clear message if a call errors, rather than
    # silently falling back to mock numbers — that mismatch is exactly what
    # the Day 3 mock version was replaced to avoid.
    #
    # Default behavior: run the full offline end-to-end test against every
    # file in sample_audio/. Pass a single text turn instead with
    # `python3 voice_pipeline.py --single`.
    import sys

    if "--single" in sys.argv:
        reply = (
            "Ji bilkul sir, DHA Phase 6 mein hamare paas is waqt teen options available hain. "
            "Sab se pehle ek 10 marla corner house hai jo 3 crore 20 lakh ka hai. "
            "Aap chahein toh main aap ko iski details bhej doon?"
        )
        try:
            report, sentences = run_voice_turn("DHA Phase 6 mein kya options hain?", reply,
                                                output_dir=OFFLINE_TEST_AUDIO_DIR)
        except RuntimeError as e:
            print(f"Pipeline call failed: {e}")
            print("Check that DEEPGRAM_API_KEY / BASE_URL / API_KEY are set in your .env "
                  "(Edge TTS needs no key). If edge-tts itself errors, check your network "
                  "connection — it calls Microsoft's TTS service over the internet.")
            raise SystemExit(1)

        print("Spoken sentences (in order streamed to TTS):")
        for s in sentences:
            print(" -", s)
        print(f"\nSynthesized audio chunks: {len(report.audio_chunks)} "
              f"(total bytes: {sum(len(c) for c in report.audio_chunks)})")
        print(f"Saved to: {report.audio_file_paths}")
        print("\nLatency report (ms):", report)
        print(f"\nFirst audio ready in {report.total_first_audio_ms}ms "
              f"({'WITHIN' if report.under_budget else 'OVER'} 2000ms budget)")
        print("\nNote: telephony_ms is 0 — telephony_send_audio() (Twilio) is not "
              "wired up in this demo, see module docstring.")
    else:
        try:
            run_offline_test()
        except RuntimeError as e:
            print(f"Offline test failed: {e}")
            print("Check that DEEPGRAM_API_KEY / BASE_URL / API_KEY are set in your .env "
                  "(Edge TTS needs no key).")
            raise SystemExit(1)
