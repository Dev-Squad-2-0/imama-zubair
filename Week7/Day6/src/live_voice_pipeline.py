"""
Live microphone voice-agent demo with real barge-in.

Flow:
    microphone -> Deepgram Live STT -> LangGraph -> Fish Audio TTS -> speaker
                                   ^                              |
                                   |--------- barge-in -----------|

While the agent is speaking, a second Deepgram live listener keeps the
microphone active. SpeechStarted/interim transcript events set an interrupt
event; pygame playback stops immediately, Deepgram finishes the caller's
utterance, and that transcript becomes the next graph.run_turn() input.

For reliable local barge-in use headphones/headset. Without acoustic echo
cancellation, laptop speakers can physically leak Fish Audio back into the
microphone and look like caller speech.

Every agent turn is logged under:
    tests/audio/output/live/<session_id>/

The folder contains:
    turn_###_agent.txt
    turn_###_sentence_##.mp3
    conversation.jsonl

Run from the project root:
    python src/live_voice_pipeline.py --caller-id 03001234567

The caller phone is telephony metadata. It is passed to graph.run_turn(),
stored in user_profile.client_phone / CRM, and is never requested verbally.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import graph
import live_audio_io as io
import voice_pipeline as vp
import monitoring
from nodes import GOODBYE_KEYWORDS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIVE_OUTPUT_ROOT = PROJECT_ROOT / "tests" / "audio" / "output" / "live"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "live-caller")
    return cleaned.strip("._") or "live-caller"


class LiveSessionLogger:
    """Small append-only logger for text, TTS audio, user turns, and traces."""

    def __init__(self, session_id: str):
        root = Path(os.getenv("LIVE_OUTPUT_DIR", str(DEFAULT_LIVE_OUTPUT_ROOT)))
        self.output_dir = root / _safe_name(session_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.output_dir / "conversation.jsonl"
        self.agent_turn = 0

    def _event(self, payload: dict):
        row = {"timestamp": time.time(), **payload}
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def log_user(self, transcript: str, barge_in: bool = False):
        self._event({"type": "user", "text": transcript, "barge_in": barge_in})

    def begin_agent_turn(self, reply_text: str, trace=None) -> int:
        self.agent_turn += 1
        n = self.agent_turn
        text_path = self.output_dir / f"turn_{n:03d}_agent.txt"
        text_path.write_text(reply_text, encoding="utf-8")
        self._event({
            "type": "agent",
            "turn": n,
            "text": reply_text,
            "text_path": str(text_path),
            "trace": [row.get("node_name") for row in (trace or [])],
        })
        return n

    def save_tts_sentence(self, agent_turn: int, sentence_index: int, sentence: str,
                          audio_bytes: bytes, first_byte_latency_ms: int) -> Path:
        path = self.output_dir / f"turn_{agent_turn:03d}_sentence_{sentence_index:02d}.mp3"
        path.write_bytes(audio_bytes)
        self._event({
            "type": "tts",
            "turn": agent_turn,
            "sentence_index": sentence_index,
            "text": sentence,
            "audio_path": str(path),
            "bytes": len(audio_bytes),
            "first_byte_latency_ms": first_byte_latency_ms,
        })
        return path

    def log_barge_in(self, transcript: Optional[str], agent_turn: int):
        self._event({"type": "barge_in", "turn": agent_turn, "text": transcript})


def _is_goodbye(transcript: str) -> bool:
    lowered = transcript.lower()
    return any(str(kw).lower() in lowered for kw in GOODBYE_KEYWORDS)


# Rough bilingual token normalization used only to reject obvious TTS echo.
# The live TTS is Roman Urdu while Deepgram ur often returns the same words in
# Urdu script, so a literal string comparison is not enough.
_ECHO_TOKEN_ALIASES = {
    "جی": "ji", "ji": "ji",
    "ایک": "ek", "اک": "ek", "ek": "ek",
    "سیکنڈ": "second", "second": "second",
    "سر": "sir", "سال": "sir", "sir": "sir",
    "میں": "main", "main": "main",
    "آپ": "aap", "aap": "aap",
    "کا": "ka", "کی": "ki", "کے": "ke",
    "نام": "naam", "naam": "naam",
    "سب": "sab", "سے": "se", "پہلے": "pehle",
    "بتا": "bata", "دیجیے": "dijiye", "دیجئے": "dijiye",
    "ابھی": "abhi", "availability": "availability", "اویلیبیلٹی": "availability",
    "چیک": "check", "check": "check",
    "کر": "kar", "کرنا": "kar", "kar": "kar",
    "لیتا": "leta", "leta": "leta",
    "ہوں": "hoon", "ہے": "hoon", "hoon": "hoon",
    "ذرا": "zara", "زارا": "zara", "zara": "zara",
    "رکیے": "rukiye", "روکیے": "rukiye", "rukiye": "rukiye",
    "کنفرم": "confirm", "confirm": "confirm",
    "ڈیٹیلز": "details", "details": "details",
    "نکال": "nikaal", "نکل": "nikaal", "nikaal": "nikaal",
    "رہا": "raha", "raha": "raha",
    "لیے": "liye", "لئے": "liye", "liye": "liye",
}


def _echo_tokens(text: str):
    raw = re.findall(r"[A-Za-z0-9_]+|[\u0600-\u06FF]+", (text or "").lower())
    return [_ECHO_TOKEN_ALIASES.get(tok, tok) for tok in raw]


def _looks_like_tts_echo(transcript: Optional[str], spoken_sentence: str) -> bool:
    """Reject only strong matches to what the agent is currently saying.

    This is intentionally conservative. It requires at least two recognized
    tokens and either a strong token-overlap or a matching two-token prefix.
    """
    if not transcript:
        return False
    heard = _echo_tokens(transcript)
    spoken = _echo_tokens(spoken_sentence)
    if len(heard) < 2 or len(spoken) < 2:
        return False

    # Common echo case: Deepgram returns only the beginning of the sentence,
    # e.g. "اک سیکنڈ ..." for "Ek second sir ...".
    if heard[:2] == spoken[:2]:
        return True

    spoken_set = set(spoken)
    overlap = sum(1 for token in heard if token in spoken_set)
    return overlap >= 2 and (overlap / max(len(heard), 1)) >= 0.70


def _accept_or_suppress_barge_in(
    transcript: Optional[str],
    spoken_sentence: str,
    logger: LiveSessionLogger,
    agent_turn: int,
) -> Optional[str]:
    if _looks_like_tts_echo(transcript, spoken_sentence):
        print(f"  [ECHO-SUPPRESSED] ignored probable agent TTS: {transcript}")
        logger._event({
            "type": "echo_suppressed",
            "turn": agent_turn,
            "text": transcript,
            "agent_sentence": spoken_sentence,
        })
        return None
    logger.log_barge_in(transcript, agent_turn)
    return transcript



def _group_sentences_for_live_tts(
    reply_text: str,
    target_chars: int = None,
    max_chars: int = None,
):
    """Group adjacent sentences into natural TTS phrases.

    The old live path made one Fish request per sentence, which created a
    network/TTS pause at every full stop. Short replies now normally become
    one continuous TTS request. Longer replies are split into a few larger
    chunks, and the next chunk is prefetched while the current one plays.
    """
    if target_chars is None:
        target_chars = int(os.getenv("LIVE_TTS_TARGET_CHARS", "180"))
    if max_chars is None:
        max_chars = int(os.getenv("LIVE_TTS_MAX_CHARS", "320"))

    target_chars = max(80, target_chars)
    max_chars = max(target_chars, max_chars)

    sentences = vp._split_into_sentences(reply_text)
    if not sentences:
        cleaned = vp._clean_for_speech(reply_text)
        return [cleaned] if cleaned else []

    groups = []
    current = ""

    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"

        if current and len(candidate) > max_chars:
            groups.append(current)
            current = sentence
            continue

        current = candidate

        # Once we have a comfortably long phrase, finish it at this natural
        # sentence boundary instead of making Fish handle tiny fragments.
        if len(current) >= target_chars:
            groups.append(current)
            current = ""

    if current:
        groups.append(current)

    return groups


def _live_tts_text(chunk: str) -> str:
    """Create the Fish-only expressive version of a natural TTS chunk.

    Multi-sentence chunks remain continuous, but each semantic sentence can
    carry its own S2 [bracket] delivery cue. The clean reply stored in CRM and
    conversation logs is untouched.
    """
    cleaned = vp._clean_for_speech(chunk)
    if not cleaned:
        return ""
    return vp._apply_expression_tags(cleaned)


def _synthesize_live_chunk(chunk: str):
    tagged = _live_tts_text(chunk)
    if not tagged:
        raise RuntimeError("empty TTS chunk")
    return vp.tts_stream_audio(tagged)


def speak_reply(
    reply_text: str,
    logger: LiveSessionLogger,
    trace=None,
    enable_barge_in: bool = True,
) -> Optional[str]:
    """Speak an agent reply with continuous, pipelined TTS.

    Key differences from the old implementation:
    - nearby sentences are grouped into larger natural phrases;
    - Fish Audio is NOT called once per sentence;
    - the next TTS chunk is synthesized while the current chunk is playing;
    - barge-in remains active for the entire reply.

    This preserves quick first audio while removing the 1-2 second network
    pause that previously occurred after every sentence.
    """
    agent_turn = logger.begin_agent_turn(reply_text, trace=trace)
    chunks = _group_sentences_for_live_tts(reply_text)

    if not chunks:
        return None

    listener = None
    if enable_barge_in:
        listener = io.BargeInListener().start()
        print("  [barge-in enabled: you can speak over the agent]")

    # Only one chunk ahead is needed. This avoids a burst of Fish requests
    # while still hiding most network latency behind current audio playback.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fish-tts-prefetch")
    current_future = executor.submit(_synthesize_live_chunk, chunks[0])

    try:
        for index, chunk in enumerate(chunks, start=1):
            # If the caller speaks while the current chunk is being generated,
            # do not start playing it over them.
            if listener is not None and listener.interrupt_event.is_set():
                transcript = listener.wait_for_transcript()
                return _accept_or_suppress_barge_in(
                    transcript, chunk, logger, agent_turn
                )

            try:
                audio_bytes, first_byte_ms = current_future.result()
            except RuntimeError as exc:
                print(f"  [live_voice_pipeline] TTS failed for this chunk: {exc}")
                monitoring.record_voice_quality(
                    logger.output_dir.name,
                    tts_success=False,
                )

                # Try to continue with the next chunk rather than killing the
                # whole reply.
                if index < len(chunks):
                    current_future = executor.submit(
                        _synthesize_live_chunk,
                        chunks[index],
                    )
                continue

            # Start generating the NEXT chunk before current playback begins.
            # Its network/TTS latency is therefore hidden by this audio.
            next_future = None
            if index < len(chunks):
                next_future = executor.submit(
                    _synthesize_live_chunk,
                    chunks[index],  # zero-based: this is the next chunk
                )

            print(f"AGENT: {chunk}")

            audio_path = logger.save_tts_sentence(
                agent_turn,
                index,
                chunk,
                audio_bytes,
                first_byte_ms,
            )
            print(f"  TTS -> {audio_path}")
            monitoring.record_voice_quality(
                logger.output_dir.name,
                tts_first_byte_ms=first_byte_ms,
                tts_success=True,
            )

            if listener is not None and listener.interrupt_event.is_set():
                transcript = listener.wait_for_transcript()
                return _accept_or_suppress_barge_in(
                    transcript, chunk, logger, agent_turn
                )

            completed = io.play_audio_bytes(
                audio_bytes,
                interrupt_event=(
                    listener.interrupt_event if listener is not None else None
                ),
            )

            if not completed and listener is not None:
                print(
                    "  [BARGE-IN] caller speech detected; "
                    "stopping agent playback..."
                )
                transcript = listener.wait_for_transcript()
                return _accept_or_suppress_barge_in(
                    transcript, chunk, logger, agent_turn
                )

            if next_future is not None:
                current_future = next_future

        return None

    finally:
        if listener is not None:
            listener.stop()

        # Do not wait for a speculative next Fish request if the caller barged
        # in. The worker can finish in the background and be discarded.
        executor.shutdown(wait=False, cancel_futures=True)



_RAG_WARMUP_THREAD = None
_RAG_WARMUP_LOCK = threading.Lock()


def _rag_warmup_enabled() -> bool:
    return os.getenv("RAG_WARMUP_ON_LIVE_START", "1").strip().lower() not in {
        "0", "false", "no", "off"
    }


def _start_rag_warmup_in_background():
    """Warm RAG once without delaying the caller-facing greeting.

    rag_pipeline is imported inside the worker so live_voice_pipeline startup
    itself stays lightweight. The daemon thread loads the embedding model,
    opens Chroma, and executes one tiny retrieval while the greeting/TTS is
    already happening.
    """
    global _RAG_WARMUP_THREAD

    if not _rag_warmup_enabled():
        print("[RAG] background warmup disabled")
        return None

    with _RAG_WARMUP_LOCK:
        if _RAG_WARMUP_THREAD is not None and _RAG_WARMUP_THREAD.is_alive():
            return _RAG_WARMUP_THREAD

        def _worker():
            try:
                import rag_pipeline

                result = rag_pipeline.warmup()
                if result.get("success"):
                    suffix = " (cached)" if result.get("already_warm") else ""
                    print(
                        f"[RAG] background warmup complete in "
                        f"{result.get('elapsed_ms')}ms{suffix}"
                    )
                else:
                    print(
                        f"[RAG] background warmup unavailable: "
                        f"{result.get('error')}"
                    )
            except Exception as exc:
                # RAG warmup must never prevent a phone call from starting.
                print(f"[RAG] background warmup failed: {exc}")

        _RAG_WARMUP_THREAD = threading.Thread(
            target=_worker,
            name="rag-warmup",
            daemon=True,
        )
        _RAG_WARMUP_THREAD.start()
        print("[RAG] background warmup started")
        return _RAG_WARMUP_THREAD


def run_live_session(
    session_id: str = "live-caller",
    caller_id: Optional[str] = None,
    enable_barge_in: bool = True,
):
    """Run a live microphone conversation until goodbye/Ctrl+C."""
    logger = LiveSessionLogger(session_id)

    print(f"Starting live session '{session_id}'. Press Ctrl+C to end the call.")
    print(f"Output log: {logger.output_dir}")
    print(f"Deepgram: model={vp.DEEPGRAM_MODEL}, language={vp.DEEPGRAM_LANGUAGE}")
    print(f"Barge-in: {'ON' if enable_barge_in else 'OFF'}")

    if caller_id:
        print(f"Caller ID (telephony metadata): {caller_id}")
    else:
        print(
            "WARNING: no caller ID was supplied. Conversation works, but a booking "
            "cannot be finalized because the agent intentionally will not ask the "
            "caller to repeat their phone number. Use --caller-id for local testing."
        )

    print()
    vp.warmup_tts()

    # First graph turn is deliberately kept lightweight. RAG is not imported
    # on this path. Once the greeting is ready, warm RAG in a daemon thread so
    # model/Chroma startup overlaps with Fish Audio generation/playback.
    reply, trace = graph.run_turn(session_id, "", caller_id=caller_id)
    _start_rag_warmup_in_background()

    pending_barge_in = None
    if reply:
        pending_barge_in = speak_reply(
            reply,
            logger,
            trace=trace,
            enable_barge_in=enable_barge_in,
        )

    try:
        while True:
            if pending_barge_in:
                transcript = pending_barge_in
                pending_barge_in = None
                print(f"USER [barge-in]: {transcript}")
                logger.log_user(transcript, barge_in=True)
                monitoring.record_voice_quality(session_id, stt_confidence=io.get_last_stt_confidence())
            else:
                transcript = io.listen_for_utterance()
                if transcript is None:
                    continue
                print(f"USER: {transcript}")
                logger.log_user(transcript, barge_in=False)
                monitoring.record_voice_quality(session_id, stt_confidence=io.get_last_stt_confidence())

            reply, trace = graph.run_turn(
                session_id,
                transcript,
                caller_id=caller_id,
            )

            if reply:
                pending_barge_in = speak_reply(
                    reply,
                    logger,
                    trace=trace,
                    enable_barge_in=enable_barge_in,
                )

            # If the caller said goodbye, let the graph's goodbye reply finish
            # unless they barge into it; then close the session.
            if _is_goodbye(transcript) or not reply:
                print("\nCall ended.")
                break

    except KeyboardInterrupt:
        print("\nCall interrupted by user.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Live Deepgram -> LangGraph -> Fish Audio voice session with barge-in."
    )
    parser.add_argument("--session", default="live-caller", help="Session id to use/resume.")
    parser.add_argument(
        "--caller-id",
        default=os.getenv("TEST_CALLER_ID"),
        help=(
            "Caller phone supplied by telephony metadata. For local testing pass "
            "--caller-id 03001234567 or set TEST_CALLER_ID in .env."
        ),
    )
    parser.add_argument(
        "--no-barge-in",
        action="store_true",
        help="Disable interruption handling for troubleshooting.",
    )
    args = parser.parse_args()

    try:
        run_live_session(
            args.session,
            caller_id=args.caller_id,
            enable_barge_in=not args.no_barge_in,
        )
    except RuntimeError as exc:
        print(f"Live pipeline failed to start: {exc}")
        print(
            "Check DEEPGRAM_API_KEY, Fish Audio credentials, network/DNS, your "
            "microphone, and PyAudio/PortAudio. Calendar/Gmail credentials are "
            "only needed when you actually book/reschedule/cancel."
        )
        raise SystemExit(1)
