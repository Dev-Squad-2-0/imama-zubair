# Day 3 - Task 5: Human Evaluation Rubric

Scoring rubric for the sample call transcripts in `outputs/sample_transcripts.md`.
Each category is scored 1-5. This is meant to be filled in by a human listener
(supervisor or intern) after reading/listening to a transcript, same as
`eval/hallucination_results.md` scoring worked in Day 2.

Note on scope: real audio isn't available in this environment (no live
Deepgram/Fish Audio/Twilio credentials), so "naturalness" and "fluency" here
are scored against the TEXT that would be spoken, and "latency" is scored
against the simulated timing report attached to each turn. Once this runs on
real telephony, the same rubric applies directly to recorded call audio.

## Categories

| Category | What it measures | 1 (poor) | 3 (okay) | 5 (excellent) |
|---|---|---|---|---|
| Naturalness | Does it sound like a real agent, not a script reader? | Robotic, repeats exact phrasing every turn | Mostly natural, occasional stiff line | Varied phrasing, sounds like an actual person |
| Persuasiveness | Does it move the customer toward a visit/booking without pressure? | No attempt to move forward, or pushy/aggressive | Some value-based nudge, generic | Value-based, acknowledges concern, easy exit offered |
| Fluency | Is the UrduLish grammatically natural, not a stiff translation? | Broken code-switching, feels translated | Mostly fine, a few awkward phrases | Reads exactly like natural spoken UrduLish |
| Latency | Time to first audio reaching the caller | Over 2000ms or noticeable dead air | 1500-2000ms, acceptable | Under 1500ms, feels instant |
| Conversation Flow | Does context carry across turns correctly? | Agent forgets earlier info, contradicts itself | Mostly tracks context, minor slips | Full continuity, references earlier turns naturally |

## Scored Results

Scores below were produced by reading through `outputs/sample_transcripts.md`
turn by turn. This is a first-pass self-evaluation against the rubric above;
flagged for supervisor review rather than treated as final, since a fully
independent human listener (not the system's own builder) is what the rubric
is really designed for.

| Scenario | Naturalness | Persuasiveness | Fluency | Latency | Conversation Flow | Notes |
|---|:-:|:-:|:-:|:-:|:-:|---|
| 1. Budget + area memory | 3 | 3 | 4 | 5 | 5 | Correctly tracked budget -> area -> "sasti" (cheaper) reference across 4 turns. Reply phrasing repeats "Ji bilkul sir, is waqt hamare paas N options hain" almost verbatim each time — needs more template variation. |
| 2. Price objection + double decline | 4 | 4 | 4 | 5 | 5 | Objection acknowledged before pivoting to an alternative. Correctly stopped pushing after the second decline instead of continuing to sell. |
| 3. Investment guardrail | 4 | 3 | 4 | 5 | 5 | Correctly refused to guarantee a return and offered a human advisor handoff, matching the hard guardrail in system_prompt.md. Persuasiveness scored lower on purpose here — the guardrail intentionally limits how persuasive this turn can be. |
| 4. Trust + builder + maintenance | 3 | 3 | 4 | 5 | 4 | Handled trust and maintenance concerns without inventing numbers. Both objection replies reused the identical generic template — this is the clearest gap: category-specific objections should not sound the same. |
| 5. Interruption mid-call | 4 | 3 | 4 | 5 | 5 | Barge-in handled cleanly ("Ji, main sun raha hoon"), and the corrected budget from after the interruption was picked up correctly in the next turn's recommendation. |

## Average Scores

| Category | Average |
|---|:-:|
| Naturalness | 3.6 / 5 |
| Persuasiveness | 3.2 / 5 |
| Fluency | 4.0 / 5 |
| Latency | 5.0 / 5 |
| Conversation Flow | 4.8 / 5 |

## Honest Gaps Found During Evaluation

- **Reply template repetition** is the biggest issue: `_compose_reply()` in
  `conversation_agent.py` currently builds text from a small set of fixed
  templates. This is intentional for Day 3 (no LLM call yet, keeps the demo
  runnable without API credentials), but it's exactly why Naturalness and
  Persuasiveness scored lower than Latency and Flow. Once this is wired to
  a real LLM call, the same slots/strategy data should produce more varied
  phrasing per call.
- **Trust and maintenance objections currently share one fallback template.**
  Task 4 correctly classifies both categories separately in
  `objection_handler.py`, but `conversation_agent.py`'s reply composer only
  special-cases the "price" category. This is flagged, not silently ignored.
- **Latency numbers are simulated**, not measured against real Deepgram/Fish
  Audio/Twilio calls. The pipeline shape and budget math are real (see
  `src/voice_pipeline.py` docstring for the latency budget breakdown), but
  actual numbers need to be re-measured once real API credentials are wired
  in.

## Next Step for Day 4+

Replace the template-based `_compose_reply()` with a real LLM call
(LangGraph node) that takes the same inputs already being computed here —
conversation slots, retrieved structured facts, objection strategy — as
context. Everything else in the Day 3 pipeline (memory, objection detection,
speech behaviors, latency streaming) stays the same.
