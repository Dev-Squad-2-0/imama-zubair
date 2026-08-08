"""
Full-workflow audio test: real Deepgram STT -> real graph.run_turn() ->
real Fish Audio TTS, run over every file in input/, output written to output/.


Folder layout:
    input/   - customer audio, one file per turn (see generate_input_audio.py)
    output/  - agent's synthesized reply audio, one file per turn

Requires (.env, real credentials, nothing mocked):
    DEEPGRAM_API_KEY, DEEPGRAM_LANGUAGE (defaults to "ur")
    BASE_URL, API_KEY (primary LLM)
    GEMINI_API_KEY (fallback LLM)
    FISH_AUDIO_API_KEY, FISH_VOICE_ID
    db/knowledge_base.db must be built (structured_retrieval.py's DB_PATH)

Run from tests/audio/:
    python3 test_full_workflow_audio.py
"""

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import graph          # noqa: E402
import voice_pipeline as vp  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(HERE, "input")
OUTPUT_DIR = os.path.join(HERE, "output")

SESSION_ID = f"audio-workflow-test-{time.strftime('%Y%m%d%H%M%S')}"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
checks = []


def check(label, condition):
    status = PASS if condition else FAIL
    checks.append((label, status))
    print(f"    [{status}] {label}")


def load_manifest():
    """Optional - only used to print the expected transcript alongside the
    real Deepgram one, for an eyeballed STT-accuracy comparison. The test
    still runs fine without it (falls back to sorted input/ filenames)."""
    manifest_path = os.path.join(INPUT_DIR, "script_manifest.json")
    if not os.path.exists(manifest_path):
        return {}
    with open(manifest_path, encoding="utf-8") as f:
        entries = json.load(f)
    return {e["turn_id"]: e for e in entries if e.get("file")}


def input_audio_files():
    if not os.path.isdir(INPUT_DIR):
        return []
    files = sorted(
        f for f in os.listdir(INPUT_DIR)
        if os.path.splitext(f)[1].lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac")
    )
    return files


def run_one_turn(turn_id, audio_path):
    """Real STT -> real graph.run_turn() -> real TTS for one turn. Returns
    a result dict; never raises (a failure here shouldn't kill the rest of
    the run, same "one bad turn doesn't crash the whole test" spirit
    voice_pipeline.run_voice_turn() already uses per-sentence)."""
    result = {"turn_id": turn_id, "audio_in": audio_path}

    try:
        audio_bytes, mimetype = vp.load_audio_file(audio_path)
        transcript, stt_ms = vp.stt_transcribe(audio_bytes, mimetype=mimetype)
    except RuntimeError as e:
        result["error"] = f"STT failed: {e}"
        return result

    result["transcript"] = transcript
    result["stt_ms"] = stt_ms
    print(f"  Deepgram transcript: {transcript!r}  ({stt_ms}ms)")

    t0 = time.monotonic()
    try:
        reply, trace = graph.run_turn(SESSION_ID, transcript)
    except Exception as e:
        traceback.print_exc()
        result["error"] = f"graph.run_turn failed: {e}"
        return result
    result["turn_ms"] = int((time.monotonic() - t0) * 1000)
    result["reply"] = reply
    result["trace"] = [{"node": t["node_name"], "duration_ms": t.get("duration_ms")} for t in trace]
    print(f"  AGENT: {reply}")
    print(f"  Trace: {' -> '.join(t['node_name'] for t in trace)}  ({result['turn_ms']}ms)")

    if reply:
        try:
            audio_out, tts_ms = vp.tts_stream_audio(reply)
            out_path = os.path.join(OUTPUT_DIR, f"{turn_id}_agent_reply.mp3")
            with open(out_path, "wb") as f:
                f.write(audio_out)
            result["audio_out"] = out_path
            result["tts_ms"] = tts_ms
            print(f"  Saved reply audio: {out_path} ({tts_ms}ms)")
        except RuntimeError as e:
            result["tts_error"] = str(e)
            print(f"  TTS failed for this reply (non-fatal, continuing): {e}")

    return result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    manifest = load_manifest()
    files = input_audio_files()

    if not files:
        print(f"No audio files found in {INPUT_DIR}. Run generate_input_audio.py first.")
        sys.exit(1)

    print(f"Session: {SESSION_ID}")
    print(f"Warming up Fish Audio TTS connection...")
    vp.warmup_tts()

    results = []
    for filename in files:
        turn_id = os.path.splitext(filename)[0]
        path = os.path.join(INPUT_DIR, filename)
        print(f"\n{'=' * 70}\n{turn_id}", end="")
        if turn_id in manifest:
            print(f"  (expected: {manifest[turn_id]['text']!r})")
        else:
            print()
        print("=" * 70)

        result = run_one_turn(turn_id, path)
        results.append(result)

        if "error" in result:
            check(f"{turn_id}: turn completed without error", False)
            continue

        # ---- assertions tied to this session's specific fixes ----
        node_names = [t["node"] for t in result["trace"]]

        if turn_id == "turn_02":
            state = graph.get_session_state(SESSION_ID)
            check(f"{turn_id}: نہیں registered as a decline (decline_count >= 1)",
                  state is not None and state.get("decline_count", 0) >= 1)

        elif turn_id == "turn_03":
            state = graph.get_session_state(SESSION_ID)
            check(f"{turn_id}: second decline reached the 2-decline threshold",
                  state is not None and state.get("decline_count", 0) >= 2)

        elif turn_id == "turn_04":
            check(f"{turn_id}: native-script factual question routed to rag, not recommendation",
                  "rag" in node_names)

        elif turn_id == "turn_05":
            state = graph.get_session_state(SESSION_ID)
            check(f"{turn_id}: price objection detected (native script)",
                  state is not None and state.get("intent", {}).get("objection") == "price")

        elif turn_id == "turn_06":
            check(f"{turn_id}: native-script booking phrase routed to booking "
                  f"(the exact bug this session found and fixed)",
                  "booking" in node_names)

        elif turn_id == "turn_07":
            state = graph.get_session_state(SESSION_ID)
            check(f"{turn_id}: unrecognized area triggered clarification_needed "
                  f"(asks instead of silently guessing)",
                  state is not None and state.get("clarification_needed") is True)
            check(f"{turn_id}: reply does not silently proceed with a firm recommendation",
                  "?" in result.get("reply", ""))  # a real clarifying question, not a flat statement

        elif turn_id == "turn_08":
            check(f"{turn_id}: goodbye routed to goodbye node and ended the call",
                  "goodbye" in node_names)

    log_path = os.path.join(HERE, "full_workflow_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"session_id": SESSION_ID, "results": results,
                    "checks": [{"label": l, "status": s} for l, s in checks]},
                   f, ensure_ascii=False, indent=2)

    passed = sum(1 for _, s in checks if s == PASS)
    failed = sum(1 for _, s in checks if s == FAIL)
    print(f"\n{'=' * 70}\nSummary: {passed} passed, {failed} failed, {len(checks)} total checks")
    print(f"Full transcript/trace log: {log_path}")
    print(f"Input audio:  {INPUT_DIR}")
    print(f"Output audio: {OUTPUT_DIR}")
    if failed:
        print("\nFailed checks:")
        for label, status in checks:
            if status == FAIL:
                print(f"  - {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
