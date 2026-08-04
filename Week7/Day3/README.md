# Week 7 - Day 3: Voice Agent & Natural Conversation

Part of the Week 7 capstone: a real-estate AI voice agent. Same as Day 2, real
estate is the demonstration domain, but nothing in this folder is real-estate
specific. This layer sits on top of Day 2's RAG pipeline, structured
retrieval, and recommendation engine, and swaps in naturally with a different
`domain_config.yaml` + data + system prompt for another business.

Day 1 and Day 2 are not modified. `week-7-day-2/` in this delivery is a
minimal reconstruction (small sample dataset, not the full 60-property set)
just so Day 3 code has something real to call — your actual Day 2 folder
already has the full dataset and should be used as-is when these two folders
sit side by side in the real project structure.

---

## Folder Structure

```
week-7-day-3/
├── README.md
├── src/
│   ├── voice_pipeline.py       # Task 1: Speech -> LLM -> Voice, latency budget/streaming
│   ├── speech_behaviors.py     # Task 2: fillers, hesitation, interruption, laughter, ack
│   ├── conversation_memory.py  # Task 3: slot-based context memory across turns
│   ├── objection_handler.py    # Task 4: objection detection + strategy
│   └── conversation_agent.py   # orchestrator: wires Day 1/2/3 pieces into one turn loop
├── eval/
│   ├── sample_conversations.py # Task 5: generates scored transcripts
│   └── human_eval_rubric.md    # Task 5: rubric + scored results + honest gaps
└── outputs/
    ├── sample_transcripts.md   # generated call transcripts
    └── latency_summary.json    # aggregate latency stats
```

## How to Run

```bash
cd src
python3 voice_pipeline.py        # Task 1 demo: one turn with latency breakdown
python3 speech_behaviors.py      # Task 2 demo: fillers/hesitation/interruption
python3 conversation_memory.py   # Task 3 demo: budget -> area -> "cheaper" memory chain
python3 objection_handler.py     # Task 4 demo: 5 objection categories classified
python3 conversation_agent.py    # full orchestrated conversation, 5 turns

cd ../eval
python3 sample_conversations.py  # Task 5: generates outputs/sample_transcripts.md
```

---

## Task Summary

### Task 1: Streaming Voice Pipeline
`src/voice_pipeline.py` models Speech -> LLM -> Voice as Deepgram (STT) ->
LangGraph (LLM) -> Fish Audio (TTS) -> Twilio (playback), matching the Day 1
architecture decisions. No live phone audio exists in this environment, so
each stage is a function with realistic latency ranges instead of a live SDK
call, but the actual thing that keeps latency under budget is real: the LLM
reply is streamed sentence by sentence, and TTS starts synthesizing the first
sentence while the LLM is still generating the rest, instead of waiting for
the full reply.

**Latency budget:**

| Stage | Range |
|---|---|
| STT (streaming partial) | 150-300ms |
| LLM first sentence | 400-700ms |
| TTS first audio chunk | 200-400ms |
| Telephony overhead | 100-200ms |
| **Total to first audio** | **~850-1600ms** |

All 15 turns across the 5 sample scenarios in `outputs/latency_summary.json`
landed between 1087ms and 1438ms, under the 2000ms target.

---

### Task 2: Natural Speech Behaviors
`src/speech_behaviors.py` reuses the exact hesitation/acknowledgement phrases
already defined in Day 1's `urdulish_persona.md`, organized by *when* to use
them during a call rather than inventing new lines:

- **Fillers / thinking pauses** ("Hmm...", "Acha...", "Dekhiye...") before
  reasoning-heavy replies, fired probabilistically so it doesn't happen every
  turn.
- **Hesitation phrases** ("Ek second sir, main abhi availability check kar
  leta hoon") always fire while a tool call (SQL lookup, recommendation
  scoring) is in flight, because dead air during a real delay reads as a
  dropped call.
- **Acknowledgements** ("Ji bilkul samajh gaya") for light confirmation
  moments.
- **Light laughter** only offered in genuinely light conversational moments,
  never near price objections or complaints.
- **Interruption handling** ("Ji sir, boliye") for barge-in, when the
  customer starts talking while the agent's audio is still playing. The
  caller (`conversation_agent.py`) is responsible for actually stopping the
  in-flight TTS stream; this module just returns what to say.

---

### Task 3: Context Memory
`src/conversation_memory.py` is a slot dictionary plus short turn history,
not a separate vector memory store — a single phone call is a few minutes
long, so that's all that's needed and it's easy to explain in review.

Tested exactly against the required example:

```
"Budget 3 crore hai."          -> slots.budget = 30,000,000
"DHA mein kya options hain?"   -> slots.area = "DHA Phase 6" (budget carried over)
"Us se sasti koi option?"      -> reads last_shown_min_price, lowers budget below it
```

Slots map straight into `recommendation_engine.recommend_properties()`
kwargs via `as_recommendation_kwargs()`, so the orchestrator doesn't need any
extra translation code.

---

### Task 4: Objection Handling
`src/objection_handler.py` classifies customer text into one of six
categories (price, trust, location, investment, builder, maintenance) by
keyword match, then returns a **strategy** (talking points + guardrail notes
+ escalate flag), not a hardcoded sentence. The strategy operationalizes
rules that already exist in `system_prompt.md`:

- acknowledge the objection before offering an alternative (persuasion rule)
- never guarantee investment returns, hand off to a human advisor (hard
  guardrail — `investment` category always sets `escalate=True`)
- never invent numbers not present in retrieved/structured data
- stop pushing a sale after two clear declines (`should_stop_pushing()`,
  checked before objection classification so plain "no thanks" phrasing is
  caught too, not just objection-shaped text)

---

### Task 5: Human Evaluation
`eval/sample_conversations.py` runs 5 scripted call scenarios through the
full pipeline (memory + objections + retrieval + recommendation + speech
behaviors + latency) and writes transcripts to
`outputs/sample_transcripts.md`, scored against the rubric in
`eval/human_eval_rubric.md`.

| Category | Average Score |
|---|:-:|
| Naturalness | 3.6 / 5 |
| Persuasiveness | 3.2 / 5 |
| Fluency | 4.0 / 5 |
| Latency | 5.0 / 5 |
| Conversation Flow | 4.8 / 5 |

Honest gap flagged in the rubric: current replies come from fixed templates
(`_compose_reply()` in `conversation_agent.py`), not a live LLM call, which
is why Naturalness/Persuasiveness scored lower than Latency/Flow. This was a
deliberate Day 3 choice so the whole pipeline runs without API credentials.
See "Where the real LLM/voice APIs plug in" below.

---

## Where the real LLM/voice APIs plug in

Everything in this folder is built so swapping mocks for real APIs is a
small, localized change:

| File | Mock today | Real integration point |
|---|---|---|
| `voice_pipeline.py` | latency-only simulation functions | Deepgram streaming client, Fish Audio streaming client, Twilio media stream |
| `conversation_agent.py` | `_compose_reply()` uses fixed templates | single LLM call (LangGraph node), fed the same slots/retrieved facts/objection strategy this function already computes |

No other file needs to change. Memory, objection classification, speech
behavior selection, and latency streaming are all API-independent.

---

## Domain-Agnostic Design Notes

- Nothing in `src/` hardcodes "real estate" logic beyond calling
  `recommendation_engine.recommend_properties()` and
  `structured_retrieval` functions from Day 2, which are themselves
  domain-agnostic and driven by `domain_config.yaml`.
- `objection_handler.py`'s six categories (price, trust, location,
  investment, builder, maintenance) are common to most sales/booking
  conversations, not property-specific. Swapping in a clinic or restaurant
  domain would mean updating the keyword lists and category-specific talking
  points, not the classification structure.
- `conversation_memory.py`'s slot fields (budget, city, area, purpose,
  bedrooms) map to the current domain's structured fields. For a different
  domain, slots would be renamed to match that domain's
  `structured_entities.fields` in `domain_config.yaml`, same pattern as Day 2.

## Next Steps

Day 4 will move `conversation_agent.py`'s turn loop into a LangGraph state
graph, replace `_compose_reply()`'s templates with a real LLM call using
`system_prompt.md` + persona + the strategy/slots already being computed
here as context, and wire in real Deepgram/Fish Audio/Twilio calls in
`voice_pipeline.py`.
