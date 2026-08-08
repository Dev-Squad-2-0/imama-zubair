"""
Generates the CUSTOMER-side input audio for test_full_workflow_audio.py.

Why per-turn files, not one continuous recording: Deepgram's batch
transcribe_file() (voice_pipeline.stt_transcribe) has no turn/utterance
segmentation of its own - that's what Deepgram's LIVE streaming endpoint's
endpointing/UtteranceEnd events do (live_audio_io.py), not the batch
endpoint this offline test harness uses. One WAV/MP3 per turn is also the
same convention Day 3's sample_audio/ already established, so this fits
the existing project shape rather than inventing a new one.

Each line below is synthesized as if the CUSTOMER were speaking it (using
the same Fish Audio voice as a stand-in mic input - there's no separate
"customer TTS voice" configured in this project, and there doesn't need to
be one for a scripted regression test). This is why the script text is
UrduLish/native-Urdu-script customer dialogue, not agent replies.

The script deliberately exercises every fix made this session:
  turn_01 - native Urdu-script self-introduction (name/budget/city/area capture)
  turn_02 - plain decline, native script (نہیں)
  turn_03 - second decline, Roman script (2-decline stop-pushing rule)
  turn_04 - factual question, native script (RAG routing, not recommendation)
  turn_05 - price objection, native script (objection category detection)
  turn_06 - booking phrase, native script (THE bug this session found and fixed -
            appointment_intent.py previously never matched this at all)
  turn_07 - real city + a MADE-UP area name (new DB-validated "ask, don't
            guess" flow - the feature just built)
  turn_08 - goodbye, native script

Requires (real credentials, real API calls - nothing here is mocked):
    DEEPGRAM_API_KEY is NOT needed for this script (TTS only)
    FISH_AUDIO_API_KEY, FISH_VOICE_ID must be set in .env

Run from tests/audio/:
    python3 generate_input_audio.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import voice_pipeline as vp  # noqa: E402  (path insert must happen first)

INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")

# (turn_id, native-Urdu-script or Roman customer line, what this turn is testing)
SCRIPT = [
    ("turn_01", "میرا نام امامہ ہے۔ میرا بجٹ تین کروڑ ہے، مجھے ڈی ایچ اے فیز 6 میں گھر چاہیے۔",
     "name/budget/city/area capture from native script"),
    ("turn_02", "نہیں",
     "plain decline, native script (decline_count -> 1)"),
    ("turn_03", "Nahi, abhi nahi chahiye.",
     "second decline, Roman script (decline_count -> 2, stop-pushing rule)"),
    ("turn_04", "ڈی ایچ اے فیز 6 میں کیا سہولیات ہیں؟",
     "factual question, native script -> should route to rag, not recommendation"),
    ("turn_05", "یہ مہنگا ہے۔",
     "price objection, native script -> objection=price should be detected"),
    ("turn_06", "ڈی ایچ اے فیز 6 کی اپوائنٹمنٹ بک کر دیں۔",
     "booking phrase, native script -> THE bug this session found: previously "
     "always misrouted to recommendation, never to booking"),
    ("turn_07", "مجھے کراچی کے کلفٹن ایریا میں پراپرٹی چاہیے۔",
     "real city (Karachi) + a made-up/unlisted area (Clifton) -> should trigger "
     "the new DB-validated clarification flow, NOT silently search unfiltered"),
    ("turn_08", "شکریہ، خدا حافظ۔",
     "goodbye, native script -> should route to goodbye node and end the call"),
]


def main():
    os.makedirs(INPUT_DIR, exist_ok=True)
    print(f"Warming up Fish Audio TTS connection...")
    vp.warmup_tts()

    manifest = []
    for turn_id, text, purpose in SCRIPT:
        print(f"\n{turn_id}: {text!r}\n  (tests: {purpose})")
        try:
            audio_bytes, latency_ms = vp.tts_stream_audio(text)
        except RuntimeError as e:
            print(f"  FAILED to synthesize: {e}")
            manifest.append({"turn_id": turn_id, "text": text, "purpose": purpose,
                              "file": None, "error": str(e)})
            continue

        path = os.path.join(INPUT_DIR, f"{turn_id}.mp3")
        with open(path, "wb") as f:
            f.write(audio_bytes)
        print(f"  Saved: {path} ({len(audio_bytes)} bytes, {latency_ms}ms to synthesize)")
        manifest.append({"turn_id": turn_id, "text": text, "purpose": purpose,
                          "file": os.path.basename(path)})

    manifest_path = os.path.join(INPUT_DIR, "script_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nWrote manifest (expected transcript per turn, for later STT-accuracy "
          f"comparison) to: {manifest_path}")
    print(f"\n{len([m for m in manifest if m.get('file')])}/{len(SCRIPT)} audio files generated in {INPUT_DIR}")
    print("Next: run test_full_workflow_audio.py to feed these through the real pipeline.")


if __name__ == "__main__":
    main()
