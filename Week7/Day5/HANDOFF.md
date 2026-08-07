# Day 5 Session Handoff — LangGraph Orchestration & Tool Calling

Paste this into a new session (or just point me at this file) to pick up exactly where we left off.

## Where things stand right now

**Done and verified:** Day 5's LangGraph core — Tasks 1–5 (State Design, Graph Design, Tool Integration, Validation, State Logging). 29/29 checks passing in `Day5/src/test_langgraph_workflow.py`, run against real Google Calendar + Gmail, not mocked.

**Not started yet (explicitly deferred, approved plan):**
1. Live microphone input + streaming TTS playback, with agent text shown in the terminal as it runs.
2. A Streamlit UI showing logs and the conversation back-and-forth.

These were sequenced *after* the LangGraph core specifically so each phase could be reviewed on its own — that's still the plan, just not executed yet.

## How this session was structured

This was one long session covering two separate pieces of work:

**Part 1 — Day 4 bug hunt/fixes** (in `Day4/`, this is the Week 7 capstone's n8n + FastAPI voice agent). Found and fixed, in order:
1. `/intent` never echoed `customer_text` back, so downstream n8n nodes referencing `$('POST /intent').item.json.customer_text` got `undefined` → 422 → silent `workflow_failed`.
2. Uncaught network exceptions in `calendar_integration.py`/`email_automation.py` crashed to raw 500s instead of honest `{success: false}` — added broad `except Exception` fallbacks.
3. `/property-match` didn't expose `pending_appointment_event_id`, so n8n's reschedule/cancel nodes couldn't get a real event id — same bug class as #1.
4. Reschedule/cancel email nodes sent malformed data (reschedule sent the wrong object shape; cancel referenced a node that never executes on that branch at all) — fixed by having `/calendar/reschedule` and `/calendar/cancel` return a proper `appointment` dict.
5. `GOOGLE_CREDENTIALS_PATH=credentials.json` in `.env` was a bare relative path resolved against whatever directory the process launched from — broke outside one exact working directory. Fixed by anchoring it to `.env`'s own location via `find_dotenv()`.
6. `parse_appointment_datetime()` couldn't tell an *old* appointment date from a *newly requested* one in a single reschedule sentence ("August 1 ki appointment ko August 7 ko... reschedule kar dein") — added `parse_reschedule_datetime()` which picks the date/time nearest the reschedule verb.
7. Root-caused an intermittent Google API timeout (`WinError 10060`) to `httplib2`'s IPv6 handling on this dual-stack Windows machine (likely interacting with a Radmin VPN virtual adapter) — fixed by forcing IPv4-only DNS resolution process-wide in `calendar_integration.py`.
8. Found conversation_agent.py's live voice-pipeline path (used for direct mic-input calls, separate from the n8n/API path) never logged anything to CRM at all — wired `crm_logger` into `appointment_management.py` and `conversation_agent.py`.
9. Added prompt-injection hardening to `system_prompt.md` and the user-prompt template (explicit instruction-hierarchy language).

All verified live, all committed to `Day4/` (untouched since). `Day4/src/test_appointment_workflow.py` is the regression test for the appointment lifecycle bugs.

**Part 2 — Day 5 build** (this is the current/active work): see below.

## Day 5 architecture (the decisions that matter if resuming)

- **Day5/ is a copy of Day4/**, not a replacement — Day 4's n8n workflow and FastAPI endpoints still work as-is. Day 5 adds a LangGraph layer on top.
- **Graph routing is deterministic**, driven by Day 4's proven keyword classifiers (`call_intent.py`, `appointment_intent.py`), never by LLM judgement. This was a deliberate choice (confirmed with the user) to preserve Day 4's "the LLM never invents a booking confirmation" safety property, since Task 4 requires hard guardrails (never book an unavailable slot, never recommend an unavailable property), not just prompted-for ones.
- **The one place with real LLM tool-calling** is the `rag` node — the model chooses between semantic search (`rag_search_tool`) and exact structured lookup (`property_lookup_tool`). Everywhere else, nodes call tools directly in code.
- **LLM fallback**: every LLM call goes through `Day5/src/llm_client.py` — tries the primary "smart" model (`BASE_URL`/`API_KEY`) first, falls back to Gemini on *any* exception. **Important gotcha**: `gemini-2.5-flash` is listed as available via the API but actually 404s for this API key ("no longer available to new users"). Using `gemini-flash-latest` instead — confirmed working. If Gemini calls start failing after a session gap, check this model alias still resolves.
- **`check_availability()` is new** in `Day5/src/calendar_integration.py` only (not backported to Day4) — uses Google Calendar's `freebusy.query`, which needs **timezone-aware** ISO timestamps (unlike `events().insert()`, which takes naive datetimes + a separate `timeZone` field). Fails closed (unavailable=True on any error).
- **IPv4 patch and `.env` path-resolution fix carry over** into Day5's copy of `calendar_integration.py` automatically (copied after those fixes landed).

## File map (`Day5/src/`)

| File | Role |
|---|---|
| `graph_logger.py` | Task 5. `@traced_node` decorator — terminal print + `graph_traces` SQLite table. Built first. |
| `state.py` | Task 1. `AgentState` TypedDict + `SessionStore`. Reuses `conversation_memory.py`'s slot parsers. |
| `llm_client.py` | `generate_reply()` / `generate_with_tools()`, both with the Gemini fallback described above. |
| `tools.py` | Task 3. 6 tool categories as `@tool` functions — thin wrappers, no reimplemented logic. |
| `nodes.py` | Task 2/4. The 9 node functions + Task 4 validation gates (in `booking_node`/`rescheduling_node`). |
| `graph.py` | Assembles the `StateGraph`, routing table, `run_turn(session_id, customer_text)` entry point, `save_graph_diagram()`. |
| `test_langgraph_workflow.py` | End-to-end test, real side effects. Set `SKIP_LIVE_CALENDAR=1` to skip Calendar/Gmail sections. |
| everything else (`api.py`, `conversation_agent.py`, `voice_pipeline.py`, `calendar_integration.py`, etc.) | Copied from Day4 unchanged except where noted above. |

`Day5/graph_diagram.png` — visual of the compiled graph's routing (regenerate via `python graph.py`).

The approved implementation plan (architecture rationale, full task breakdown) is saved at `C:\Users\imama\.claude\plans\purrfect-coalescing-cook.md` if more detail is needed than this summary has.



## What "next session" should do first

Resume with **live microphone input + TTS**, per the approved phasing. Relevant existing pieces already in place (all in `Day5/src/voice_pipeline.py`, copied from Day4, currently **not wired up**):
- `sounddevice`/`soundfile` are already installed (`requirements.txt`) — `record_microphone_audio()` exists but is **commented out** in `voice_pipeline.py`.
- `stt_transcribe()` (Deepgram) and `tts_stream_audio()` (Fish Audio) both work but TTS output is only ever **saved to file**, never played through speakers — audio playback needs to be added.
- Fish Audio TTS currently requests `"format": "mp3"` — for live playback via `sounddevice`, requesting `"format": "wav"` instead would avoid needing an MP3 decoder (sounddevice/soundfile play raw PCM/WAV natively).
- The integration point for the new graph: replace `conversation_agent.run_turn()`'s role in the live loop with `graph.run_turn(session_id, customer_text)` from Day 5's new module — that's what actually needs to happen for "my agent answers live" to mean the LangGraph agent, not the old Day 4 path.
- "Text shown in terminal while the agent runs" is already halfway solved — `graph_logger.py`'s `@traced_node` already prints live node-entry/exit lines; this phase adds the actual transcript (STT output) and spoken reply text alongside that.

After live audio is working and reviewed, the last phase is the **Streamlit UI** (logs + conversation back-and-forth) — not started, no design decisions made yet.
