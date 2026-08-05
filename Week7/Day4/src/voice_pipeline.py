"""
Day 3 - Task 1: Streaming Voice Pipeline

Pipeline: customer audio -> Deepgram (STT) -> conversation_agent.py (reply) -> Fish Audio (TTS) -> caller.
Target: under 2000ms to first audio out. Reply generation lives in conversation_agent.py, not here —
run_voice_turn() speaks agent_reply_text as-is when given one, it never re-runs it through the LLM.
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
from deepgram import DeepgramClient, PrerecordedOptions, FileSource  #type: ignore

load_dotenv()

# Replies are natural Urdu/UrduLish and routinely contain characters outside
# cp1252 (Windows' default console/file encoding)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sample_audio")

GENERATED_AUDIO_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "generated_audio", "fish_audio"
)
OFFLINE_TEST_AUDIO_DIR = os.path.join(GENERATED_AUDIO_DIR, "offline_test")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
# nova-3 supports Urdu natively (language=ur) — without this, transcribe_file()
# defaults to English 
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "ur")
FISH_API_KEY = os.getenv("FISH_AUDIO_API_KEY")
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "")  # reference_id of the cloned/selected voice

FISH_MODEL = os.getenv("FISH_MODEL", "s2.1-pro-free")
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")


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
    """Returns (audio_bytes, mimetype), mimetype guessed from extension."""
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
    # only true for a real, existing audio file, so transcript text is never mistaken for a path
    if not isinstance(value, str):
        return False
    ext = os.path.splitext(value)[1].lower()
    return ext in (".wav", ".mp3", ".m4a", ".ogg", ".flac") and os.path.exists(value)


# ---------- Live microphone capture (commented out — needs `pip install sounddevice`) ----------
#
# Not wired into any active code path. Records duration_s seconds from the
# default input device and returns (wav_bytes, "audio/wav") — same shape as
# load_audio_file(), so it's a drop-in replacement anywhere audio_bytes/
# mimetype are used: stt_transcribe(audio_bytes, mimetype), or
# run_voice_turn(audio_bytes) directly (it already accepts raw bytes).
# 16kHz mono int16 is a safe default for speech STT, no resampling needed.
#
# import sounddevice as sd
# import wave
# import io
#
# def record_microphone_audio(duration_s: float = 5.0, sample_rate: int = 16000) -> tuple:
#     print(f"Recording {duration_s}s from microphone... speak now.")
#     frames = sd.rec(int(duration_s * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
#     sd.wait()  # blocks until recording finishes
#
#     buffer = io.BytesIO()
#     with wave.open(buffer, "wb") as wf:
#         wf.setnchannels(1)
#         wf.setsampwidth(2)  # int16 = 2 bytes
#         wf.setframerate(sample_rate)
#         wf.writeframes(frames.tobytes())
#
#     return buffer.getvalue(), "audio/wav"


# ---------- Speech-to-Text (Deepgram) ----------

def stt_transcribe(audio_bytes: bytes, mimetype: str = "audio/wav"):
    """Batch (not streaming) Deepgram transcription. Returns (transcript, latency_ms)."""
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


# ---------- Reply generation (LLM streaming) ----------

_STREAM_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s*")


def generate_llm_reply_stream(prompt: str, model: str = "smart", system_prompt: Optional[str] = None):
    """Streaming LLM call. Yields (sentence, latency_ms) so TTS can start on the first sentence."""
    client = _get_llm_client()
    start = time.monotonic()
    buffer = ""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        stream = client.chat.completions.create(
            model=model,
            stream=True,
            messages=messages,
        )
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            buffer += token
            # a delta can carry multiple words or whole sentences at once (gateway-dependent),
            # so scan the buffer for every complete sentence rather than checking one token
            while True:
                m = _STREAM_SENTENCE_BOUNDARY.search(buffer)
                if not m or m.end() == len(buffer):
                    break  # no confirmed sentence end yet — more text may still follow
                sentence, buffer = buffer[:m.end()].strip(), buffer[m.end():]
                if sentence:
                    yield sentence, int((time.monotonic() - start) * 1000)
                    start = time.monotonic()
        if buffer.strip():
            yield buffer.strip(), int((time.monotonic() - start) * 1000)
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
    # strips emoji, markdown, list markers, and Devanagari (LLM sometimes
    # drifts into Hindi script, which the Urdu voice can't speak) before TTS
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
    """Splits a reply into sentences for streaming TTS. Pure text splitting, no LLM call."""
    cleaned = _clean_for_speech(text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    return [s for s in sentences if s and re.search(r"\w", s, flags=re.UNICODE)]


# ---------- Emotion tagging for Fish Audio ([tag] syntax) ----------
# Fish Audio reads a leading `[emotion]` marker and shifts delivery
# accordingly. Punctuation/keyword heuristic only, applied to the TTS copy only.

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


def _apply_emotion_tag(sentence: str) -> str:
    tag = _emotion_tag_for_sentence(sentence)
    return f"[{tag}] {sentence}" if tag else sentence


# Edge TTS implementation (used before switching to Fish Audio) is in git history.


# ---------- Text-to-Speech (Fish Audio) ----------

_tts_warmed_up = False


def warmup_tts(voice: Optional[str] = None):
    """Pays the one-time connection setup cost before a real turn is timed. Safe to skip."""
    global _tts_warmed_up
    try:
        tts_stream_audio("hi", voice_id=voice)
        _tts_warmed_up = True
    except Exception as e:
        traceback.print_exc()
        print(f"TTS warmup call failed (non-fatal, continuing): {e}")


def tts_stream_audio(text: str, voice_id: Optional[str] = None):
    """Real Fish Audio TTS call. Returns (audio_bytes, latency_to_first_byte_ms)."""
    if not FISH_API_KEY:
        raise RuntimeError("FISH_AUDIO_API_KEY is not set. Set it in your .env before calling TTS.")

    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": FISH_MODEL,  # s2.1-pro-free: the free-tier model, no usage cap
    }
    payload = {
        "text": text,
        "reference_id": voice_id or FISH_VOICE_ID,
        "format": "mp3",
    }

    start = time.monotonic()
    try:
        with requests.post(
            "https://api.fish.audio/v1/tts",
            headers=headers,
            json=payload,
            stream=True,
            timeout=15,
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


# ---------- Telephony (Twilio) — integration point, not wired up ----------

def telephony_send_audio(audio_bytes: bytes):
    """Not implemented — raises on purpose instead of faking delivery. Wire to Twilio <Stream>."""
    raise NotImplementedError(
        "Twilio Media Streams integration is not implemented in this demo. "
        "Wire this to your active Twilio <Stream> websocket to send `audio_bytes` "
        "to the caller."
    )


def telephony_overhead():
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
    """Offline-test-only: generates a reply when run_voice_turn() gets no agent_reply_text."""
    # imported lazily to avoid a circular import with conversation_agent.py
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
    """Saves each sentence as its own MP3 (can't concatenate separately-encoded MP3s cleanly)."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, audio_bytes in enumerate(audio_chunks, start=1):
        path = os.path.join(output_dir, f"{turn_id}_sentence_{i:02d}.mp3")
        with open(path, "wb") as f:
            f.write(audio_bytes)
        paths.append(path)
    return paths


def run_voice_turn(customer_speech_text, agent_reply_text: Optional[str] = None,
                    agent_reply_stream=None,
                    budget_ms: int = 2000, save_audio: bool = True,
                    output_dir: str = GENERATED_AUDIO_DIR):
    """
    Runs one full conversational turn through STT/TTS. Returns (latency_report, spoken_sentences).

    customer_speech_text: audio file path, raw audio bytes, or already-transcribed text.
    agent_reply_text: text to speak as-is, or None to generate it (offline-test mode, needs audio input).
    agent_reply_stream: iterable of (sentence, llm_latency_ms), e.g. from generate_llm_reply_stream() —
        used instead of agent_reply_text when the caller wants TTS to start before the LLM finishes.
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

    # ---- resolve the reply into a stream of (raw_sentence, llm_latency_ms) ----
    if agent_reply_stream is not None:
        candidate_chunks = agent_reply_stream
    else:
        if agent_reply_text is None:
            if not is_audio_input:
                raise ValueError(
                    "run_voice_turn(agent_reply_text=None) needs real audio input "
                    "(a file path or bytes) to transcribe and reply to — got plain "
                    "text with no reply supplied. Either pass agent_reply_text "
                    "explicitly, or pass real audio for offline-test mode."
                )
            agent_reply_text = _generate_conversation_reply(transcript)
        candidate_chunks = ((s, 0) for s in _split_into_sentences(agent_reply_text))

    spoken_sentences = []  # only sentences that actually got synthesized, in order
    reply_parts = []
    running_total = report.stt_ms
    first_sentence_done = False

    for raw_sentence, llm_ms in candidate_chunks:
        cleaned = _clean_for_speech(raw_sentence)
        if not cleaned or not re.search(r"\w", cleaned, flags=re.UNICODE):
            continue
        reply_parts.append(cleaned)

        tagged_sentence = _apply_emotion_tag(cleaned)
        print("=" * 80)
        print("TTS INPUT:")
        print(repr(tagged_sentence))
        print("=" * 80)
        try:
            audio_bytes, tts_ms = tts_stream_audio(tagged_sentence)
        except RuntimeError as e:
            # one bad sentence shouldn't kill the rest of the reply
            print(f"  [voice_pipeline] TTS could not synthesize this sentence after "
                  f"retries, skipping it and continuing: {e}")
            report.skipped_sentences.append((cleaned, str(e)))
            continue

        spoken_sentences.append(cleaned)
        report.audio_chunks.append(audio_bytes)

        if not first_sentence_done:
            report.llm_first_sentence_ms = llm_ms
            running_total += llm_ms

            report.tts_first_chunk_ms = tts_ms
            running_total += tts_ms

            tel_ms = telephony_overhead()
            report.telephony_ms = tel_ms
            running_total += tel_ms

            report.total_first_audio_ms = running_total
            report.under_budget = running_total < budget_ms
            first_sentence_done = True

        report.per_sentence_ms.append(tts_ms)

    report.reply_text = " ".join(reply_parts)

    if save_audio and report.audio_chunks:
        report.audio_file_paths = _save_audio_files(report.audio_chunks, turn_id, output_dir)

    return report, spoken_sentences


# ---------- Offline end-to-end test ----------

def run_offline_test(sample_audio_dir: str = SAMPLE_AUDIO_DIR,
                      output_dir: str = OFFLINE_TEST_AUDIO_DIR):
    """Runs every file in sample_audio_dir through STT -> reply generation -> TTS."""
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

    print(f"Warming up Fish Audio TTS connection...")
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
    # default: offline test against sample_audio/. `--single` runs one text turn instead.
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
            print("Check that DEEPGRAM_API_KEY / BASE_URL / API_KEY / FISH_AUDIO_API_KEY are "
                  "set in your .env. If Fish Audio itself errors, check your network "
                  "connection and that FISH_VOICE_ID is a valid reference_id.")
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
            print("Check that DEEPGRAM_API_KEY / BASE_URL / API_KEY / FISH_AUDIO_API_KEY are "
                  "set in your .env.")
            raise SystemExit(1)
