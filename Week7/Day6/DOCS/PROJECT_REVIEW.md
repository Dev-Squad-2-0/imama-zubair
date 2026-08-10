# Voice Agent Project Review 

## What was actually failing

The saved Day 6 evaluation report is not an all-fail run. It records **44 scenarios, 50 passing checks, 2 failing checks, 0 scenario errors**. The runner correctly exits with process status `1` whenever even one check fails, so an IDE/terminal can label the whole command `FAILED`.

The two saved failures were:

1. A buyer said `اپارٹمنٹ چاہیے، گودام نہیں` but the routing/search logic still treated `گودام` as a positive commercial/property-type signal.
2. A caller with an existing appointment said `کیا اپوائنٹمنٹ پرسوں دن 12 بجے کر سکتے ہیں؟` without the literal word `reschedule`; the keyword-only appointment detector returned no appointment intent and the graph routed to RAG.

The saved report predates some source/test edits in this upload, so it should be regenerated rather than treated as current evidence.

## Fixes applied

- Added local negation handling to `src/call_intent.py` so `warehouse nahi`, `گودام نہیں`, `rent nahi`, etc. do not become positive intent signals.
- Hardened `src/nodes.py::_detect_property_type()`:
  - handles negation before or after a property word;
  - prevents ASCII substring collisions such as `house` being found inside `warehouse`;
  - gives a current-turn explicit property type priority over an older stored type on deterministic fallback.
- Added contextual implicit rescheduling in `src/appointment_intent.py`: with an existing appointment, an appointment reference plus a parseable new date/time can mean reschedule even without the literal `reschedule` keyword.
- `src/nodes.py` now passes existing appointment state into that detector.
- Added explicit buyer-signal detection so a sticky rental/commercial/investment/seller state can be corrected by phrases such as `Rent nahi, buy karna hai`.
- Added `tests/test_nlu_regressions.py` using only Python stdlib `unittest`, so these routing regressions can be checked without LLM, calendar, audio, or network services.
- Made `src/rag_pipeline.py` initialize its embedding model and LLM client lazily. Missing LLM credentials no longer cause a RAG-client crash merely because the module is imported.
- Converted `requirements.txt` from UTF-16/CRLF to UTF-8/LF. The original encoding is risky for normal `pip install -r requirements.txt` tooling.
- Added `.env.example` with the environment variables the code actually reads.

## `voice_pipeline.py` decision

**Do not delete it.** It is live shared infrastructure, not unused code. It is referenced by:

- `src/live_audio_io.py` — Deepgram client/configuration
- `src/live_voice_pipeline.py` — Fish Audio TTS, sentence/emotion helpers
- `src/demo_appointment_pipeline.py` — prerecorded Deepgram STT
- audio/live integration tests

One stale path inside it *was* broken: `_generate_conversation_reply()` referenced `ConversationMemory`, `SpeechBehaviorLayer`, and `_generate_reply` on the current `conversation_agent.py`, but that module is now only a LangGraph front end and no longer exposes those names. That offline fallback has been rewired to `graph.run_turn()` with a stable session id, so offline sample audio now exercises the same stateful LangGraph brain as production.

Deepgram model selection is now shared through:

```env
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=ur
```

for both prerecorded and live STT instead of hardcoding the model separately.

## Verification performed in this environment

Passed:

```text
PYTHONPATH=src python tests/test_nlu_regressions.py
Ran 4 tests ... OK

python -m compileall -q src tests
PASS
```

The complete LangGraph/voice/integration suite could not be honestly rerun in this sandbox because its third-party runtime packages and live service credentials (Deepgram, LLM, Google Calendar/Gmail, Fish Audio) are not present here. Do not overwrite the saved evaluation report with a fabricated new “pass” result; rerun it in the configured project environment.

## Important remaining architecture observations

- `graph.py` is the real conversation orchestrator. `conversation_agent.py` is a text front end; `live_voice_pipeline.py` is the microphone/speaker front end. Keep that single-brain design.
- `voice_pipeline.py` still contains a standalone `generate_llm_reply_stream()` helper, but production LangGraph does not use it. Treat it as a latency/legacy utility unless you deliberately design streaming LangGraph output; do not create a second response-generation path around the graph.
- `src/src.zip` is a redundant nested source archive and the many `__pycache__` files are build artifacts. They are not part of runtime architecture.
- The repository still lacks several final capstone/deployment artifacts such as a Dockerfile, top-level README/setup guide, CI/CD config, and production monitoring configuration. Those are separate from the current evaluation failures.

## Recommended rerun order

1. `PYTHONPATH=src python tests/test_nlu_regressions.py`
2. Existing non-live/unit tests.
3. `tests/task 1 evaluation/run_evaluation_suite.py` with configured LLM/RAG services.
4. Prompt-injection suite.
5. `tests/audio/test_full_workflow_audio.py` with Deepgram/Fish credentials and microphone/audio prerequisites.
6. Live Calendar/Gmail tests last, because they depend on external state/availability.
