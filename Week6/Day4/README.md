# Week 6 Day 4: LangGraph Integration — Routing Between Chat, Retrieval & Prediction

## Overview
This is Day 4 of Week 6. The goal was to connect everything built so far into one working system. Day 2 built the prediction models (match winner, top player by stat). Day 3 built the AFL-only chat agent with retrieval tools. Today's job was to wire both of those together using LangGraph, so one app can tell the difference between "answer a general AFL question," "look up a stat," and "make a prediction," and send each one to the right place instead of leaving that decision up to one agent.

---

## Objectives
- Design a state schema that carries the query, conversation history, intent, entities, tool results, and final response through the graph
- Build a router node that sorts each query into factual, retrieval, prediction, or off-topic
- Wrap the Day 2 prediction models as LangGraph tools, with team nickname resolution and grounding explanations
- Add a validation node so unresolved teams/players trigger a clarification question instead of a guess
- Make sure every prediction is worded as a probability, never a certainty
- Run enough real conversations through the graph to prove out every path, not just the happy one

---

## Input
No new data was needed for this task. Everything reuses what was already built earlier in the week:
- `team_match_features_v1_2026-07-27.csv`, `player_match_features_v1_2026-07-27.csv` (Day 1)
- `models/` folder — match winner model, three top player models (disposals, goals, fantasy_points), latest team/player feature snapshots, valid team list (Day 2)
- `predict.py` — the `predict_match_winner` and `predict_top_player` functions (Day 2)
- `afl_chat_agent.py` — the AFL-only chat agent and its retrieval tools (Day 3)

---

## Tasks

# Day 4: LangGraph Agent Workflow

## Task 1: Graph Design for the Full System

The first step was designing the complete LangGraph workflow and defining how information would move through the system. Instead of allowing a single LLM agent to decide everything on its own, the workflow was broken into dedicated nodes, each responsible for one specific task.

The graph state schema was designed to store all information required throughout execution. The following fields were included:

| State | Purpose |
|-------|---------|
| `user_query` | The user's current question. |
| `conversation_history` | Previous conversation used for multi-turn context. |
| `intent` | The routing decision made by the router node. |
| `entities` | Extracted teams, players, or other AFL entities. |
| `tool_result` | Output returned from retrieval or prediction tools. |
| `error` | Any error encountered during execution. |
| `needs_clarification` | Indicates whether additional user input is required. |
| `clarification_question` | Question shown when clarification is needed. |
| `final_response` | Final formatted response returned to the user. |
| `trace` | Execution log recording what every node did, used later for debugging and annotations. |

The workflow follows a structured execution path:

<img width="489" height="555" alt="graph" src="https://github.com/user-attachments/assets/76ef388e-d290-43e0-9935-f768a40d0472" />


This explicit routing was chosen instead of using a single autonomous agent.

A traditional LangChain agent decides which tool to call and how to respond entirely from its prompt. While instructions such as *"prediction responses must include a disclaimer"* can be written into the prompt, they remain recommendations that the model has to remember every time.

With LangGraph, every prediction request always follows the same execution path:

```text
prediction_node
        │
        ▼
validation_node
        │
        ▼
response_formatting_node
```

Because every prediction passes through these nodes, validation checks and probabilistic disclaimers are enforced by the graph itself rather than relying on the model to remember them. This makes the workflow deterministic, easier to debug, and much more reliable.

---

## Task 2: Building the Router Node

The router node determines which workflow branch should handle each user query.

Rather than using another LLM call, a lightweight rule-based classifier was implemented. Since the system only needs to distinguish between four categories, keyword matching was sufficient while also being significantly faster and completely deterministic.

The router classifies every query into one of four intents:

- Prediction
- Retrieval
- Factual
- Off-topic

Separate keyword cue lists were created for prediction, retrieval, and off-topic language. If a query did not match any explicit cues, an additional AFL context check was performed before deciding whether it should be treated as factual or off-topic. This prevents unrelated questions from accidentally entering the factual pipeline.

Using a rule-based approach provides several advantages:

- Instant execution with no additional LLM calls.
- No API cost.
- Deterministic behaviour where identical inputs always produce identical outputs.
- Easy debugging by simply updating keyword lists instead of modifying prompts.

The router was evaluated using 20 manually created test queries covering all supported intents.

After one round of improvements, the router achieved **100% routing accuracy**.

Testing also uncovered two genuine implementation issues:

- A keyword list variable had been referenced with the wrong name, which would have caused the classifier to crash.
- The initial prediction pattern failed on questions such as **"Will X beat Y?"** because the team name appeared between the keywords.

Both issues were resolved by correcting the keyword mappings and expanding the cue patterns to cover additional phrasing.

---

## Task 3: Wiring Prediction Models as LangGraph Tools

The prediction models developed earlier in the project were wrapped as LangGraph tools so they could be called directly from the prediction node.

Two prediction tools were integrated:

- `predict_match_winner`
- `predict_top_player`

Since the prediction models only accept official team names, an additional preprocessing layer was added to resolve user input before inference.

This resolver supports:

- Common team nicknames (e.g. **"Pies" → "Collingwood Magpies"**)
- Team aliases
- Fuzzy string matching as a fallback for misspellings or unknown variations

This makes the prediction tools much more tolerant of natural user language.

The system also accounts for a known project limitation. Since there is no live AFL fixture feed available, requests such as *"this week"* cannot reference future scheduled matches.

Instead, these requests are resolved using each team's or player's latest available rolling form, matching the same limitation identified during Day 2.

Prediction responses include more than just the final output.

Every prediction returns:

- The predicted winner or player statistic.
- The corresponding probability or predicted value.
- A computed explanation showing the three most influential features used by the model.

These explanations are generated directly from the trained models rather than using generic descriptions.

Specifically:

- Match winner predictions use coefficient-based feature contributions from the Logistic Regression model.
- Player statistic predictions use feature importances from the Gradient Boosting models.

This allows every prediction to explain *why* the model reached its conclusion instead of only reporting the result.

---

## Task 4: Self-Correction and Fallbacks

To improve reliability, a validation node was placed immediately after both retrieval and prediction branches.

Its responsibility is to verify that each tool successfully produced usable output before the response is returned.

Several validation checks were implemented.

If a team or player cannot be matched successfully, the graph does not attempt to guess.

Instead, it asks the user for clarification.

For example:

> "Who will win?"

does not provide enough information to make a prediction because no teams are specified.

Rather than hallucinating an answer, the workflow sets `needs_clarification` and returns a clarification question requesting the missing teams.

Additional fallback logic was also implemented.

If the user requests a player statistic that the trained models do not support, the graph explicitly explains that the statistic is unavailable instead of fabricating a prediction.

These validation and fallback mechanisms ensure that every prediction returned by the system is based on valid model inputs rather than assumptions.

---

## Task 5: End-to-End Testing

The completed workflow was evaluated by running ten complete conversations through the compiled LangGraph.

The evaluation covered every major execution path:

- Retrieval queries
- Match winner predictions
- Player statistic predictions
- Off-topic requests
- Ambiguous questions requiring clarification
- Multi-turn conversations using stored conversation state

One of the multi-turn tests specifically verified that previously mentioned team names could be recovered from `conversation_history`, allowing the second user message to omit them while still producing the correct prediction.

For debugging and documentation, the complete execution trace was logged for representative conversations.

Each trace records the sequence of graph execution, including:

```text
Router Decision
        │
        ▼
Tool Invocation
        │
        ▼
Validation
        │
        ▼
Response Formatting
        │
        ▼
Final Response
```

These traces make it easy to identify exactly where a failure occurs within the workflow.

Finally, the completed LangGraph implementation was compared with a traditional monolithic LangChain agent.

The graph-based workflow provides several advantages:

- Every prediction automatically passes through the same validation and formatting pipeline.
- Probabilistic disclaimers are guaranteed rather than relying on prompt instructions.
- Clarification is requested whenever information is missing instead of allowing the model to guess.
- Debugging is significantly simpler because routing errors can be traced directly to the router node instead of analysing an entire agent reasoning chain.
- The modular node structure also makes future extensions easier, since new capabilities can be added as independent nodes without redesigning the entire workflow.

Overall, the LangGraph architecture provides a more reliable, maintainable, and deterministic solution than a single free-form agent while preserving the same end-user functionality.

---

## Module Reference: `afl_langgraph_agent.py`

Everything from the notebook was pulled out into this standalone module, so the graph can be imported and reused anywhere (a script, an API, Day 5) instead of needing a notebook to run. Needs `models/`, `predict.py`, `afl_chat_agent.py`, both CSVs, and a `.env` file with `BASE_URL`/`API_KEY` in the same folder.

**Main entry point**
- `run_turn(query, thread_id="afl-demo")` — sends one message through the full graph and returns the full state (`final_response`, `intent`, `entities`, `trace`, etc.). Use the same `thread_id` across calls to keep multi-turn context; use a different one per user or session.

**Routing**
- `classify_intent(query)` — the rule-based classifier, returns `"prediction"`, `"retrieval"`, `"factual"`, or `"off_topic"`
- `contains_afl_context(query)` / `mentions_known_player(query)` — helpers the router uses to tell an AFL-related query apart from a genuinely off-topic one
- `extract_entities(query)` — pulls out team names, a player name, and a stat type from the query
- `route_from_router(state)` / `route_from_validation(state)` — the functions that decide which node runs next

**Team & fixture resolution**
- `resolve_team(team_name)` — turns a nickname or partial name (e.g. "Pies") into the exact team name the models expect, with a fuzzy-match fallback
- `resolve_fixture(home_team, away_team)` — stands in for a live fixture lookup; since there's no fixture feed, it just returns the matchup using each team's latest known form

**Prediction tools**
- `match_prediction_tool(home_team, away_team)` — LangGraph tool wrapping `predict_match_winner`, adds team resolution and a grounding explanation
- `top_player_prediction_tool(team, stat_type="disposals")` — LangGraph tool wrapping `predict_top_player`, same team resolution and grounding
- `top_match_features(X_df)` / `top_player_features(stat_type)` — work out the actual top 3 features driving a given prediction (coefficients for the match model, feature importances for the player models)
- `format_prediction_response(result)` — turns a raw prediction result into the final wording, always framed as a probability, never a certainty

**Validation & fallback**
- `validation_node(tool_result)` — checks whether a tool call actually returned something usable
- `fallback_node(intent, stat_type=None)` — handles requests that are out of scope (like an unmodeled stat type) or off-topic
- `graph_validation_node(state)` — the graph-facing wrapper around `validation_node` that sets `needs_clarification` and `clarification_question` on the state

**Graph nodes**
- `router_node(state)` — sorts intent and pulls out entities, with a fallback to the previous turn's entities for follow-up questions
- `retrieval_node(state)` — looks up player stats or team head-to-head records
- `prediction_node(state)` — calls the match or top player prediction tool
- `factual_node(state)` — sends general AFL questions to the Day 3 chat agent
- `off_topic_node(state)` — returns the standard refusal message
- `response_formatting_node(state)` — builds the final response, including the clarification question if one's needed

**State schema**
- `AFLState` — the `TypedDict` that carries `user_query`, `conversation_history`, `intent`, `entities`, `tool_result`, `error`, `needs_clarification`, `clarification_question`, `final_response`, and `trace` through the graph

**Compiled objects**
- `graph` — the `StateGraph` before compiling
- `app` — the compiled, checkpointed graph (what `run_turn` actually calls)

---

### Example Usage

```python
from afl_langgraph_agent import run_turn

response = run_turn(
    "Will the Pies beat the Cats this week?",
    thread_id="demo"
)

print(response["final_response"])
```

## Technologies Used
- Python
- Pandas
- LangChain
- LangGraph
- scikit-learn (for the underlying Day 2 models)
- Jupyter Notebook
- python-dotenv

---

## Project Structure
```
Week6_Day4/
│
├── models/
│   ├── match_winner_model.joblib
│   ├── top_player_model_disposals.joblib
│   ├── top_player_model_goals.joblib
│   ├── top_player_model_fantasy_points.joblib
│   ├── latest_team_features.joblib
│   ├── latest_player_features.joblib
│   └── valid_teams.joblib
├── team_match_features_v1_2026-07-27.csv
├── player_match_features_v1_2026-07-27.csv
├── predict.py
├── afl_chat_agent.py
├── afl_langgraph_agent.py
├── week6_day4_langgraph_app.ipynb
├── routing_accuracy_table.csv
├── annotated_state_traces.md
└── README.md
```

---

## Key Insights
- A rule-based router is more than enough for a small, well-defined set of intents. No need for an LLM call just to sort a query into one of four buckets
- Forcing predictions through a fixed validation and formatting path is what actually guarantees the probabilistic wording. A prompt instruction alone isn't reliable enough
- Team nickname resolution needs a fuzzy-match fallback. A fixed alias dictionary alone misses anything not explicitly listed
- Real per-prediction grounding (actual top features from the model) is a lot more useful than a static description of what the model generally uses
- Multi-turn follow-ups work cleanly once the router has a fallback to the previous turn's resolved entities. Without that, it has no way to know who "they" refers to

---

## Skills Demonstrated
- LangGraph state machine design
- Intent classification (rule-based)
- Tool wrapping and orchestration
- Entity resolution (team/player alias matching)
- Model interpretability (coefficient and feature importance based grounding)
- Validation and fallback handling
- Multi-turn conversation state management
- Python Programming (Pandas, LangChain, LangGraph)

---

## Future Improvements
- Swap the rule-based router for a structured-output LLM classifier if question phrasing gets a lot more varied
- Wire in a real fixture/schedule source so "this week" resolves to an actual upcoming match instead of the latest known form
- Expand the clarification flow to accept a follow-up answer and re-run the original request automatically
- Add logging/observability so a real deployment could track routing accuracy over time on live traffic

---

## Author
*Imama Zubair*

AI & Data Science Intern @ Netixsol
