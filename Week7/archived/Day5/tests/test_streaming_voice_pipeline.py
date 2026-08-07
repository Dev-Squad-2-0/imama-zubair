"""
Day 3 - Task 1: Streaming Voice Pipeline latency test.

"Implement Speech -> LLM -> Voice. Keep latency under 2 seconds."

This is a real, live-mic-and-speakers test of the actual streaming
plumbing, not the push-to-talk REST path app.py/api.py use day-to-day
(that one waits for a whole recording, a whole LLM reply, and a whole
TTS clip before anything plays - fine for a demo UI, not what this task
is asking for). Three things have to be true for "under 2 seconds" to be
real rather than aspirational, and this script exercises all three live:

  1. STT is Deepgram's live websocket with tuned endpointing
     (audio_io.listen_live_utterance), not batch transcription of a
     finished recording - see DEEPGRAM_ENDPOINTING_MS / DEEPGRAM_UTTERANCE_END_MS
     in .env to tune how fast Deepgram decides you've stopped talking.
  2. The LLM reply is consumed sentence-by-sentence as it streams
     (llm_client.generate_reply_stream) - TTS for sentence 1 starts the
     moment sentence 1 is complete, the LLM is still generating sentence 2
     in the background.
  3. TTS is requested as raw PCM and streamed straight to the speaker
     (audio_io.tts_synthesize_stream) - playback starts on the first audio
     chunk back from Fish Audio, not after the whole sentence downloads.

Deliberately bypasses graph.run_turn() (the full LangGraph agent, with its
routing/tool-calls/guardrails) and instead uses a direct system-prompt +
user-transcript call, same as this project's persona/system prompt files -
Day 3 predates LangGraph in this project's own timeline, and mixing in
graph.py's routing overhead would measure the agent's business logic, not
the raw pipeline this task is actually about. Run streaming_voice_pipeline
manually alongside app.py if you want to compare the two experiences.

Requires a real microphone and speakers. Not run as part of the rest of
the test suite for that reason.

Run from tests/:
    python test_streaming_voice_pipeline.py
    python test_streaming_voice_pipeline.py --turns 5   # keep going for 5 turns instead of 1
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pyaudio

import audio_io
import llm_client

LATENCY_BUDGET_MS = 2000

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")
PERSONA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "persona")


def _load_system_prompt() -> str:
    """Reuses this project's own persona/system prompt files rather than a
    throwaway inline string, so this latency test reflects the reply
    length/style the real agent actually produces (a one-word "ok" would
    trivially hit any latency budget and prove nothing)."""
    parts = []
    for path in (
        os.path.join(PROMPTS_DIR, "system_prompt.md"),
        os.path.join(PERSONA_DIR, "urdulish_persona.md"),
    ):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                parts.append(f.read())
    if not parts:
        return (
            "You are Ali, a warm professional Pakistani real estate agent speaking "
            "UrduLish on a phone call. Reply under 60 words, plain spoken sentences, "
            "no markdown."
        )
    return "\n\n".join(parts)


class _Speaker:
    """Thin wrapper around a PyAudio output stream, opened once and reused
    across sentences within a turn so there's no re-open gap between them."""

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, output=True)

    def write(self, chunk: bytes) -> None:
        self._stream.write(chunk)

    def close(self) -> None:
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


def _report(label: str, ms: int, show_flag: bool = False) -> None:
    suffix = ""
    if show_flag:
        suffix = "   [OK]" if ms <= LATENCY_BUDGET_MS else "   [OVER]"
    print(f"  {label:<28} {ms:>6} ms{suffix}")


def run_turn(system_prompt: str, speaker: _Speaker) -> None:
    print("\nListening... (speak now)")
    result = audio_io.listen_live_utterance()
    if result is None:
        print("  No speech detected, listening again.")
        return
    transcript, stt_ms = result
    print(f"USER: {transcript}")

    turn_start = time.monotonic()
    first_audio_ms = None
    first_sentence_ms = None
    first_tts_byte_ms = None

    for sentence, llm_elapsed_ms in llm_client.generate_reply_stream(system_prompt, transcript):
        if first_sentence_ms is None:
            first_sentence_ms = llm_elapsed_ms
        print(f"AGENT: {sentence}")

        tagged = audio_io.apply_emotion_tag(sentence)
        sentence_tts_start = time.monotonic()
        try:
            for chunk, tts_elapsed_ms in audio_io.tts_synthesize_stream(tagged):
                if first_tts_byte_ms is None:
                    first_tts_byte_ms = int((sentence_tts_start - turn_start) * 1000) + tts_elapsed_ms
                if first_audio_ms is None:
                    first_audio_ms = int((time.monotonic() - turn_start) * 1000)
                speaker.write(chunk)
        except RuntimeError as e:
            print(f"  [TTS failed for this sentence, skipping] {e}")
            continue

    print("\nLatency report for this turn:")
    _report("STT endpointing", stt_ms)
    if first_sentence_ms is not None:
        _report("LLM time to first sentence", first_sentence_ms)
    if first_tts_byte_ms is not None:
        _report("TTS time to first audio byte", first_tts_byte_ms)
    if first_audio_ms is not None:
        total_ms = stt_ms + first_audio_ms
        _report("TOTAL first audio out", total_ms, show_flag=True)
        verdict = "PASS" if total_ms <= LATENCY_BUDGET_MS else "FAIL"
        print(f"  -> {verdict} against the {LATENCY_BUDGET_MS}ms budget (Day 3 Task 1)")
    else:
        print("  No audio was produced this turn (TTS failed for every sentence).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 3 Task 1 streaming voice pipeline latency test.")
    parser.add_argument("--turns", type=int, default=1, help="Number of conversation turns to run (default 1).")
    args = parser.parse_args()

    for name, present in (
        ("DEEPGRAM_API_KEY", audio_io.DEEPGRAM_API_KEY),
        ("BASE_URL", llm_client.BASE_URL),
        ("API_KEY", llm_client.API_KEY),
        ("FISH_AUDIO_API_KEY", audio_io.FISH_API_KEY),
    ):
        if not present:
            print(f"Missing {name} in .env - set it before running this test.")
            raise SystemExit(1)

    print(f"Endpointing: {audio_io.DEEPGRAM_ENDPOINTING_MS}ms, utterance_end_ms: {audio_io.DEEPGRAM_UTTERANCE_END_MS}")
    print(f"Latency budget: {LATENCY_BUDGET_MS}ms (mic stops talking -> first audio byte out)")

    system_prompt = _load_system_prompt()
    speaker = _Speaker()
    try:
        for i in range(args.turns):
            print(f"\n{'=' * 60}\nTurn {i + 1}/{args.turns}\n{'=' * 60}")
            run_turn(system_prompt, speaker)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        speaker.close()


if __name__ == "__main__":
    main()
