# Voice pipeline review

## `src/voice_pipeline.py` is used — do not delete it

It is imported by:

- `src/live_audio_io.py` for the shared Deepgram client/configuration.
- `src/live_voice_pipeline.py` for Fish Audio TTS helpers and sentence/emotion handling.
- `src/demo_appointment_pipeline.py` for prerecorded Deepgram STT.
- `tests/audio/test_full_workflow_audio.py` and live integration tests.

The production conversation orchestrator remains **LangGraph (`src/graph.py`)**. `voice_pipeline.py` is now documented as a shared audio utility layer, not a second agent/orchestrator. Its offline reply fallback was also rewired to `graph.run_turn()` because the old code referenced `ConversationMemory`, `SpeechBehaviorLayer`, and `_generate_reply` on `conversation_agent.py`, which no longer exposes those symbols.

## Urdu + English / UrduLish

The code now uses one shared pair of environment variables for both prerecorded and live Deepgram STT:

```env
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=ur
```

`ur` is the safe Urdu-first default. Do **not** assume `DEEPGRAM_LANGUAGE=multi` solves Urdu+English code-switching: Deepgram's current documented Nova-3 multilingual code-switching set does not list Urdu. Test both modes against real UrduLish audio before changing the production default.

For domain words such as DHA, Bahria Town, Johar Town, appointment, plot, apartment, commercial, investment, rent, crore, and marla, Deepgram Nova-3 Keyterm Prompting is worth evaluating separately because it is designed to improve recognition of domain-specific terminology. It has not been enabled here because the project pins an older Deepgram Python SDK and the exact option shape should be validated in that installed SDK before changing a production request schema.

## Evaluation result interpretation

`tests/task 1 evaluation/run_evaluation_suite.py` intentionally exits with status 1 if **any** assertion fails. The saved report in this upload was generated before the latest source/test edits and showed 50 passing checks and 2 failing checks; a shell/IDE therefore labels the whole run `FAILED` even though most scenarios passed. Re-run the suite after installing dependencies and configuring the required services to regenerate the report from the current code.
