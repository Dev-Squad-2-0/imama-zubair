# Week 6 Day 4: LangGraph Integration — Routing Between Chat, Retrieval & Prediction

## Overview
This is Day 4 of Week 6, and the goal was to connect everything built so far into one working system. Day 2 produced the prediction models (match winner, top player by stat) and Day 3 produced the AFL-only chat agent with retrieval tools. Today's job was to wire both of those together through LangGraph, so a single app can tell the difference between "answer a general AFL question," "look up a stat," and "make a prediction," and route each one to the right place instead of relying on one agent to freely decide everything on its own.

---

## Objectives
- Design a state schema that carries the user's query, conversation history, detected intent, entities, tool results, and final response through the whole graph
- Build a router node that classifies each query into factual, retrieval, prediction, or off-topic
- Wrap the Day 2 prediction models as LangGraph tools, with team nickname resolution and grounding explanations
- Add a validation node so unresolved teams/players or unsupported requests trigger a clarification question instead of a guess
- Make sure every prediction response is worded as probabilistic, never certain
- Run enough real conversations through the graph to prove out every path, not just the happy path

---

## Input
No new data was pulled in for this task. Everything reuses artifacts from earlier in the week:
- `team_match_features_v1_2026-07-27.csv`, `player_match_features_v1_2026-07-27.csv` (Day 1)
- `models/` folder — match winner model, three top player models (disposals, goals, fantasy_points), latest team/player feature snapshots, valid team list (Day 2)
- `predict.py` — `predict_match_winner` and `predict_top_player` functions (Day 2)
- `afl_chat_agent.py` — the AFL-only chat agent and its retrieval tools (Day 3)

---

## Tasks Completed

### **Task 1: Graph Design for the Full System**

Defined the state schema: `user_query`, `conversation_history`, `intent`, `entities`, `tool_result`, `error`, `needs_clarification`, `clarification_question`, `final_response`, and `trace` (a running log of what each node did, used later for annotating runs). Sketched the graph as a router node branching into retrieval, prediction, factual, or off-topic nodes, converging through a validation node into a response formatting node.

The reasoning for using explicit LangGraph routing instead of one free agent: a single agent decides tool use and wording turn by turn based on its system prompt, which means rules like "predictions must sound probabilistic" are only ever suggestions the model has to remember. With LangGraph, every prediction is forced through the same `prediction_node → validation_node → response_formatting_node` path, so the disclaimer and the validation check are guaranteed, not hoped for.

### **Task 2: Building the Router Node**

Went with a lightweight rule-based classifier instead of an LLM call, since four categories can be identified reliably with keyword cues, and a rule-based router is instant, free, deterministic, and easy to test. Built cue lists for prediction, retrieval, and off-topic language, plus a fallback AFL-context check so unmatched queries default to off-topic instead of silently becoming factual.

Tested on 20 varied queries and got 100% routing accuracy after one round of fixing. The first pass caught a real bug (a keyword list name mismatch that would have crashed the classifier) and one genuine misroute (a "will X beat Y" phrasing where the team name sat between the keywords), both fixed by refining the cue list.

### **Task 3: Wiring Prediction Models as LangGraph Tools**

Wrapped `predict_match_winner` and `predict_top_player` as tools callable from the prediction node. Built a team alias/nickname resolver (e.g. "Pies" → "Collingwood Magpies") with a fuzzy-match fallback for anything not in the nickname list, since the prediction models only accept exact dataset team names. Since there's no live fixture feed, "this week" resolves to each team or player's latest known rolling form as a stand-in, same limitation Day 2 already flagged.

Every prediction response includes the win probability (or predicted stat) plus a real, computed top-3 feature explanation: coefficient-based contributions for the match winner model (logistic regression), and feature importances for the player stat models (gradient boosting), not just a generic description of what the model uses.

### **Task 4: Self-Correction & Fallbacks**

Added a validation node after retrieval and prediction that checks whether the tool actually returned a usable result. If a team or player can't be resolved, or the request is genuinely ambiguous (e.g. "who will win?" with no teams named), the graph asks the user for clarification instead of guessing. A separate fallback path catches requests for stat types the system doesn't model and says so directly, rather than making something up.

### **Task 5: End-to-End Testing**

Ran 10 full conversations through the compiled graph, covering retrieval, both prediction types, off-topic refusal, ambiguous input needing clarification, and a multi-turn follow-up where the second message doesn't repeat the team names and the router has to pull them from the checkpointed state. Logged and annotated the full state trace (router decision → tool called → validation → final response) for 3 representative runs.

Comparing this to a single monolithic LangChain agent: routing every prediction through the same validation and formatting nodes makes the probabilistic disclaimer and the clarify-over-guess behavior structurally guaranteed instead of dependent on the model remembering the rule that turn. It also made debugging much easier, since a misroute points at one specific place to fix (the router's cue list) instead of a full agent reasoning trace.

---

## Module Reference: `afl_langgraph_agent.py`

Everything from the notebook was extracted into this standalone module so the graph can be imported and reused anywhere (a script, an API, Day 5) instead of needing to run inside a notebook. Needs `models/`, `predict.py`, `afl_chat_agent.py`, both CSVs, and a `.env` with `BASE_URL`/`API_KEY` in the same folder.

**Main entry point**
- `run_turn(query, thread_id="afl-demo")` — sends one message through the full graph and returns the complete state dict (`final_response`, `intent`, `entities`, `trace`, etc.). Pass the same `thread_id` across calls to keep multi-turn context; use a different one per user/session.

**Routing**
- `classify_intent(query)` — rule-based classifier, returns `"prediction"`, `"retrieval"`, `"factual"`, or `"off_topic"`
- `contains_afl_context(query)` / `mentions_known_player(query)` — helpers used by the router to tell an AFL-related query apart from a genuinely off-topic one
- `extract_entities(query)` — pulls out any team names, a player name, and a stat type mentioned in the query
- `route_from_router(state)` / `route_from_validation(state)` — the conditional edge functions that decide which node runs next

**Team & fixture resolution**
- `resolve_team(team_name)` — resolves a nickname or partial name (e.g. "Pies") to the exact team name the models expect, with a fuzzy-match fallback
- `resolve_fixture(home_team, away_team)` — stands in for a live fixture lookup; since there's no fixture feed, it just returns the matchup using each team's latest known form

**Prediction tools**
- `match_prediction_tool(home_team, away_team)` — LangGraph tool wrapping `predict_match_winner`, adds team resolution and a grounding explanation
- `top_player_prediction_tool(team, stat_type="disposals")` — LangGraph tool wrapping `predict_top_player`, same team resolution and grounding
- `top_match_features(X_df)` / `top_player_features(stat_type)` — compute the actual top 3 features driving a given prediction (coefficients for the match model, feature importances for the player models)
- `format_prediction_response(result)` — turns a raw prediction result into the final worded response, always framed as a probability, never a certainty

**Validation & fallback**
- `validation_node(tool_result)` — checks whether a tool call actually returned a usable result
- `fallback_node(intent, stat_type=None)` — handles requests that are out of scope (e.g. an unmodeled stat type) or off-topic
- `graph_validation_node(state)` — the graph-facing wrapper around `validation_node` that sets `needs_clarification` and `clarification_question` on the state

**Graph nodes**
- `router_node(state)` — classifies intent and extracts entities, with a fallback to the previous turn's entities for follow-up questions
- `retrieval_node(state)` — looks up player stats or team head-to-head records
- `prediction_node(state)` — calls the match or top player prediction tool
- `factual_node(state)` — routes general AFL questions to the Day 3 chat agent
- `off_topic_node(state)` — returns the standard refusal message
- `response_formatting_node(state)` — builds the final response, including the clarification question if one is needed

**State schema**
- `AFLState` — the `TypedDict` carrying `user_query`, `conversation_history`, `intent`, `entities`, `tool_result`, `error`, `needs_clarification`, `clarification_question`, `final_response`, and `trace` through the graph

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
- A rule-based router is more than enough for a small, well-defined set of intents, no need for an LLM call just to sort a query into one of four buckets
- Forcing predictions through a fixed validation and formatting path is what actually guarantees the probabilistic wording, a prompt instruction alone isn't reliable enough
- Team nickname resolution needs a fuzzy-match fallback, a fixed alias dictionary alone misses anything not explicitly listed
- Real per-prediction grounding (actual top features from the model) is meaningfully better than a static description of what the model generally uses
- Multi-turn follow-ups work cleanly once the router has a fallback to the previous turn's resolved entities, without that it has no way to know who "they" refers to

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