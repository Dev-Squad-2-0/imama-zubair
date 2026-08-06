# Week 7 - Day 4: Workflow Automation and CRM Logging

## Overview
Day 4 wires together everything the RealEstate Hub voice agent needs to actually run a call end to end: Calendar booking, email notifications, an n8n workflow that orchestrates the whole pipeline, and a CRM logging layer that keeps a real record of what happened on every call. Nothing here is mocked. Calendar events go through the real Google Calendar API, emails go through real Gmail, and the CRM store is a real SQLite database that persists across calls.

The five tasks build on each other: Calendar integration and email automation give the agent the ability to act, appointment management wraps those actions into safe atomic operations (a reschedule either updates both Calendar and sends the email, or neither), the workflow automation API exposes each stage as its own endpoint so n8n can orchestrate and retry them individually, and the CRM logging store gives every one of those stages somewhere honest to write down what it did.

---

## Objectives
- Connect the agent to Google Calendar so it can create, reschedule, and cancel real appointments
- Send real appointment emails (confirmation, reschedule, cancellation) through Gmail
- Make booking/rescheduling/cancelling atomic: Calendar and email either both succeed or the failure is reported honestly, never a half-done state
- Break the call pipeline into granular FastAPI endpoints so an external orchestrator (n8n) can retry and branch on each stage individually
- Build an importable n8n workflow that matches those endpoints node for node, with retries and failure branches
- Persist call transcripts, client preferences, appointment history, and follow-up reminders somewhere that survives past the call
- Fix a real date/time parsing bug found while testing appointment booking

---

## Input
- Customer transcript text (already-transcribed turns, same shape STT would produce)
- Google Calendar and Gmail OAuth credentials (real accounts, not sandboxed)
- `db/knowledge_base.db` - the same SQLite file `structured_retrieval.py` already uses for property data, extended with new tables for CRM data

---

## Tasks / Features

### Task 1-2: Calendar Integration + Email Automation
`calendar_integration.py` and `email_automation.py` handle the two external systems directly. Every appointment carries the same `AppointmentDetails` payload (client name/phone, property, employee, date/time, notes) so both modules stay in sync without duplicating logic.

### Task 3: Appointment Management
`appointment_management.py` wraps booking, rescheduling, and cancelling as atomic Calendar + email units. If the Calendar call fails, the email never goes out. `appointment_intent.py` handles the date/time parsing that feeds this, including a fix this session for a real bug: the AM/PM regex was fully optional, so it could grab an unrelated number elsewhere in the sentence (e.g. pulling "3" out of "budget 3 crore") as the hour instead of the actual time mentioned. Fixed by requiring the match to carry its own AM/PM marker or `:MM`, and resolving AM/PM only from context around that specific match, not the whole sentence. Also added a proper month-day parser (`_parse_month_day()`) for phrasing like "August 10" or "10th August", and a fallback for a bare time with no date ("10 pm").

### Task 4: Workflow Automation
`api.py` exposes each stage of Call -> Intent -> Property Match -> Appointment -> Calendar -> Email -> CRM Update as its own endpoint, so n8n can retry or branch at each step instead of treating the whole pipeline as one all-or-nothing call. `n8n/real_estate_voice_agent_workflow.json` is the importable workflow that matches those endpoints one node at a time, with `retryOnFail` on every HTTP node and an IF/Switch branch after each one to catch failures. Two branches that used to be dead ends now create follow-up reminders instead of just logging a failure: a call that never turns into a booking gets a 2-day reminder, and a booking attempt that's missing info (name, phone, property, or date/time) gets a 1-day reminder listing exactly what's missing.

### Task 5: CRM Logging Store
`crm_logger.py` adds four purpose-built SQLite tables alongside the existing generic `crm_events` log:
- **Call transcripts** - every customer turn, persisted per session
- **Client preferences** - one row per phone number, upserted from conversation memory so a returning caller's budget/area/purpose doesn't need to be repeated
- **Appointment history** - one row per booked/rescheduled/cancelled appointment, queryable by phone number
- **Follow-up reminders** - created automatically by the workflow (or manually via API), with a `get_due_reminders()` query a scheduled n8n trigger can poll

All four are additive. The original `crm_events` table and its functions are untouched.

---

## Technologies Used
- Python
- FastAPI
- n8n (workflow orchestration)
- SQLite
- Google Calendar API (OAuth)
- Gmail API (OAuth)
- Pydantic

---

## Project Structure
```
files/
├── db/
│   └── knowledge_base.db
├── n8n/
│   └── real_estate_voice_agent_workflow.json
├── config/
│   └── domain_config.yaml
├── persona/
│   └── urdulish_persona.md
├── prompts/
│   └── system_prompt.md
└── src/
    ├── api.py                     # Task 4: granular workflow endpoints for n8n
    ├── calendar_integration.py    # Task 1
    ├── email_automation.py        # Task 2
    ├── appointment_management.py  # Task 3
    ├── appointment_intent.py      # Task 3 (date/time parsing + bug fix)
    ├── crm_logger.py              # Task 5: CRM logging store
    ├── call_intent.py             # buyer/rental/commercial/investment/returning-customer routing
    ├── conversation_memory.py     # existing, unchanged
    ├── conversation_agent.py      # existing, unchanged
    ├── voice_pipeline.py          # existing, unchanged
    ├── recommendation_engine.py   # existing, unchanged
    ├── structured_retrieval.py    # existing, unchanged
    ├── rag_pipeline.py            # existing, unchanged
    ├── objection_handler.py       # existing, unchanged
    ├── speech_behaviors.py        # existing, unchanged
    ├── demo_appointment_pipeline.py
    ├── test_crm_logging.py        # Task 5 test (33 checks)
    └── test_n8n_workflow.py       # Task 4 test (14 checks)
```

---

## What I Learned
- How to make a multi-step external-API pipeline safe to retry: return HTTP 200 with an explicit `success` flag instead of relying on status codes, since a retry-worthy failure and a hard outage look identical over the wire otherwise
- Why atomic operations matter once two external systems are involved (Calendar + Gmail) - a half-booked appointment with no confirmation email is worse than a clean failure
- How a regex that's too permissive (an optional marker meant to be flexible) can silently grab the wrong match from earlier in a sentence, and why fixing it means tying the match to nearby context instead of just tightening the pattern
- Designing a database schema to be additive rather than changing what already works - four new tables next to the existing one, no migration of old data needed
- Structuring an n8n workflow so retries and failure branches are visible in the graph itself, not buried in code

---

## Skills Demonstrated
- REST API design for external orchestration (FastAPI)
- n8n workflow design (nodes, IF/Switch branching, retry configuration)
- SQLite schema design and migrations-free additive changes
- OAuth integration with Google Calendar and Gmail
- Regex debugging and root-cause analysis
- Atomic multi-system operations
- Test-driven verification without mocking external APIs

---

## Future Improvements
- Wire live microphone input once Day 5's LangGraph restructuring settles `run_turn()`'s interface (scaffolding already exists, deliberately not connected yet to avoid redoing it)
- Move session storage from an in-memory dict to Redis or Postgres for multi-instance deployment
- Add an admin/ops view over `crm_events` and the new CRM tables instead of only querying by session or phone number
- Run the n8n workflow against a live n8n instance instead of validating it structurally, once real OAuth credentials are available in the test environment

---

## Author
Imama Zubair
AI & Data Science Intern, Netixsol
