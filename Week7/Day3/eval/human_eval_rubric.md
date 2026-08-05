# Day 3 - Task 5: Human Evaluation Rubric

Scoring rubric for `outputs/sample_transcripts.md`. Scored 1-5 per category,
same idea as `eval/hallucination_results.md` in Day 2.


## Categories

| Category | What it measures | 1 (poor) | 3 (okay) | 5 (excellent) |
|---|---|---|---|---|
| Naturalness | Does it sound like a real agent, not a script reader? | Robotic, repeats exact phrasing every turn | Mostly natural, occasional stiff line | Varied phrasing, sounds like an actual person |
| Persuasiveness | Does it move the customer toward a visit/booking without pressure? | No attempt to move forward, or pushy/aggressive | Some value-based nudge, generic | Value-based, acknowledges concern, easy exit offered |
| Fluency | Is the UrduLish grammatically natural, not a stiff translation? | Broken code-switching, feels translated | Mostly fine, a few awkward phrases | Reads exactly like natural spoken UrduLish |
| Latency | Time to first audio reaching the caller | Over 2000ms or noticeable dead air | 1500-2000ms, acceptable | Under 1500ms, feels instant |
| Conversation Flow | Does context carry across turns correctly? | Agent forgets earlier info, contradicts itself | Mostly tracks context, minor slips | Full continuity, references earlier turns naturally |

## Scored Results

| Scenario | Naturalness | Persuasiveness | Fluency | Latency | Conversation Flow | Notes |
|---|:-:|:-:|:-:|:-:|:-:|---|
| 1. Budget + area memory | 4 | 4 | 5 | 3 | 5 | Correctly tracked budget -> area -> "sasti" (cheaper) across all 4 turns, and each reply genuinely varies (different properties led with each time, not a repeated template). Turn 4 opens with "Dekhiye... Zara rukiye, main confirm kar ke batata hoon." — filler and hesitation phrase stacked together, a bit much for one line. |
| 2. Price objection + double decline | 4 | 4 | 4 | 3 | 5 | Price objection acknowledged before pivoting to a cheaper alternative, with a real reason given (amenities, demand). Correctly stopped pushing after the second "no thanks" — that farewell line is a fixed template on purpose, since it's a hard guardrail, not something worth leaving to LLM phrasing variance. |
| 3. Investment guardrail | 4 | 3 | 4 | 3 | 5 | Refused a guaranteed-profit number and offered a human advisor handoff, matching the hard guardrail in `system_prompt.md`. Persuasiveness is lower on purpose here — the guardrail limits how hard this turn can push. This scenario's second turn hit 1906ms, the closest any turn came to the 2000ms budget. |
| 4. Trust + builder + maintenance | 4 | 4 | 4 | 3 | 4 | Trust and maintenance objections now get distinct replies (verified listings + agent contact for trust; "I'll confirm and follow up" instead of guessing, for maintenance) — this used to be the same generic template for both, now it isn't. |
| 5. Interruption mid-call | 4 | 3 | 4 | 3 | 5 | Barge-in handled cleanly ("Sorry sir, aap boliye pehle."), and the budget correction given right after the interruption was picked up correctly in the very next recommendation. |

## Average Scores

| Category | Average |
|---|:-:|
| Naturalness | 4.0 / 5 |
| Persuasiveness | 4.0 / 5 |
| Fluency | 4.4 / 5 |
| Latency | 3.0 / 5 |
| Conversation Flow | 5.0 / 5 |

Latency is capped at 3 across the board even though every scripted turn
came in under budget (766-1906ms, see `outputs/latency_summary.json`) —
that number only covers TTS, since this eval path skips STT by design (see
the README). Run against real audio instead of scripted text, real
Deepgram STT took 4.4-7.2s by itself, over budget before TTS even starts.
And neither number includes how long the LLM takes to think, since that
call is blocking today. So "latency" here is honestly more like "TTS was
fast," not "the caller waited under 2 seconds" — see the README's Task 1
section for the fix (streaming the LLM call, switching Deepgram to its
streaming endpoint).

## Honest Gaps Found During Evaluation

- **Latency as measured doesn't reflect what a caller actually experiences.**
  Covered above — it's the main reason Latency isn't scored higher despite
  a perfect on-paper budget record.
- **Filler + hesitation can stack on the same turn** (scenario 1, turn 4),
  since both are gated on the same "a tool call is happening" condition.
  Sounds a little over-eager. Worth tuning so at most one fires per turn.
- **`rag_pipeline.py` (brochures/descriptions/FAQs) isn't wired into the
  live reply**, so anything outside structured SQL fields — general company
  FAQs, more descriptive brochure language for trust/location objections —
  isn't grounded in retrieved text, it's whatever the LLM already knows.
  Didn't come up as a wrong answer in these 5 scenarios, but it's a gap for
  broader coverage.


