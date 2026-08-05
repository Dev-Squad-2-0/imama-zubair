"""
Day 3 - Full pipeline cohesiveness test.

Runs a real multi-turn conversation through the ENTIRE stack in one continuous
call: real Deepgram STT on real audio -> conversation_agent.py's streaming
LLM reply (memory + objections + recommendations) -> real Fish Audio TTS,
with ONE shared ConversationMemory across turns.

Neither existing test covers this combination on its own:
    - voice_pipeline.py's own test: real STT + TTS, but each sample_audio
      file is an isolated single turn, no memory carried between them.
    - eval/sample_conversations.py: real memory across turns, but customer
      input is scripted text, so STT never runs.

This script closes that gap. Turns reuse existing sample_audio/ files
(already real speech, already verified against real Deepgram) in the exact
order of the Day 3 spec's own memory example:
    01_budget_3_crore.mp3   -> "Budget 3 crore hai."
    02_dha_area_query.mp3   -> "DHA mein kya options hain?"
    04_cheaper_option.mp3   -> "Us se sasti koi option?"

run_turn() (conversation_agent.py) updates memory from its customer_text
argument directly, before any STT would happen inside run_voice_turn() --
so it can't be handed a raw audio path (memory would try to regex-match
budget/area against a file path string). STT is done explicitly here
instead, and the real transcript is what gets passed to run_turn().

Output:
    agent_audio/turn_NN_sentence_NN.mp3  -- real Fish Audio TTS output
    pipeline_test_log.json               -- transcript, reply, latency, memory snapshot, per turn
"""

import os
import sys
import json
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "src"))

from conversation_memory import ConversationMemory
from speech_behaviors import SpeechBehaviorLayer
from conversation_agent import run_turn
from voice_pipeline import load_audio_file, stt_transcribe

SAMPLE_AUDIO_DIR = os.path.join(SCRIPT_DIR, "..", "sample_audio")
AGENT_AUDIO_DIR = os.path.join(SCRIPT_DIR, "agent_audio")
LOG_PATH = os.path.join(SCRIPT_DIR, "pipeline_test_log.json")

# same 3-turn memory chain as the Day 3 spec's own example, as real audio
TURNS = [
    "01_budget_3_crore.mp3",
    "02_dha_area_query.mp3",
    "04_cheaper_option.mp3",
]


def main():
    os.makedirs(AGENT_AUDIO_DIR, exist_ok=True)

    memory = ConversationMemory()
    behaviors = SpeechBehaviorLayer(seed=1)
    log = []

    for i, filename in enumerate(TURNS, start=1):
        audio_path = os.path.join(SAMPLE_AUDIO_DIR, filename)
        print(f"\n{'=' * 70}\nTurn {i}: {filename}\n{'=' * 70}")

        # explicit STT: real Deepgram call, timed separately from run_turn()
        audio_bytes, mimetype = load_audio_file(audio_path)
        transcript, stt_ms = stt_transcribe(audio_bytes, mimetype=mimetype)
        print(f"CUSTOMER (transcribed): {transcript!r}  [stt: {stt_ms}ms]")

        wall_start = time.monotonic()
        spoken, report = run_turn(transcript, memory, behaviors, output_dir=AGENT_AUDIO_DIR)
        wall_ms = int((time.monotonic() - wall_start) * 1000)

        print(f"AGENT: {spoken}")
        print(f"  latency to first audio (post-STT): {report.total_first_audio_ms}ms "
              f"({'within' if report.under_budget else 'OVER'} 2000ms budget)")

        log.append({
            "turn": i,
            "input_audio_file": filename,
            "customer_transcript": transcript,
            "agent_reply": spoken,
            "memory_slots_after_turn": {
                "budget": memory.slots.budget,
                "city": memory.slots.city,
                "area": memory.slots.area,
                "bedrooms": memory.slots.bedrooms,
                "purpose": memory.slots.purpose,
                "decline_count": memory.slots.decline_count,
            },
            "latency_ms": {
                "stt_explicit": stt_ms,
                "llm_first_sentence": report.llm_first_sentence_ms,
                "tts_first_chunk": report.tts_first_chunk_ms,
                "telephony": report.telephony_ms,
                "total_first_audio_post_stt": report.total_first_audio_ms,
                "total_first_audio_including_stt": stt_ms + report.total_first_audio_ms,
                "wall_clock_full_turn": wall_ms,
            },
            "under_2000ms_budget_post_stt": report.under_budget,
            "agent_audio_files": report.audio_file_paths,
            "skipped_sentences": report.skipped_sentences,
        })

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 70}")
    print(f"Log written to: {LOG_PATH}")
    print(f"Agent audio saved to: {AGENT_AUDIO_DIR}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
