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

### **Task 1: Graph Design for the Full System**

Defined the state schema: `user_query`, `conversation_history`, `intent`, `entities`, `tool_result`, `error`, `needs_clarification`, `clarification_question`, `final_response`, and `trace` (a log of what each node did, used later to annotate runs). The graph is a router node that branches into retrieval, prediction, factual, or off-topic nodes, all converging through a validation node into a response formatting node.

Why explicit routing instead of one free agent: a single agent decides tool use and wording on its own each turn, based on its system prompt, so a rule like "predictions must sound probabilistic" is only ever a suggestion the model has to remember. With LangGraph, every prediction goes through the same `prediction_node → validation_node → response_formatting_node` path every time, so the disclaimer and the validation check are guaranteed, not just hoped for.

### **Task 2: Building the Router Node**

Used a simple rule-based classifier instead of an LLM call, since four categories can be told apart reliably with keyword cues. A rule-based router is instant, free, deterministic, and easy to test. Built cue lists for prediction, retrieval, and off-topic language, plus a fallback check for AFL-related context so an unmatched query defaults to off-topic instead of quietly becoming factual.

Tested on 20 varied queries and got 100% routing accuracy after one round of fixes. The first pass turned up a real bug (a keyword list name that didn't match, which would have crashed the classifier) and one real misroute (a "will X beat Y" phrasing where the team name sat between the two keywords). Both got fixed by adjusting the cue list.

### **Task 3: Wiring Prediction Models as LangGraph Tools**

Wrapped `predict_match_winner` and `predict_top_player` as tools the prediction node can call. Built a team alias/nickname resolver (e.g. "Pies" → "Collingwood Magpies") with a fuzzy-match fallback for anything not in the nickname list, since the prediction models only accept exact team names. There's no live fixture feed, so "this week" resolves to each team or player's latest known rolling form instead, the same limitation flagged back on Day 2.

Every prediction response includes the win probability (or predicted stat) plus a real, computed top-3 feature explanation: coefficient-based contributions for the match winner model (logistic regression), and feature importances for the player stat models (gradient boosting). Not just a generic description of what the model uses in general.

### **Task 4: Self-Correction & Fallbacks**

Added a validation node after retrieval and prediction that checks whether the tool actually returned something usable. If a team or player can't be resolved, or the request is genuinely ambiguous (e.g. "who will win?" with no teams named), the graph asks for clarification instead of guessing. A separate fallback path catches requests for stat types the system doesn't model and says so directly, instead of making something up.

### **Task 5: End-to-End Testing**

Ran 10 full conversations through the compiled graph, covering retrieval, both prediction types, off-topic refusal, ambiguous input that needs clarification, and a multi-turn follow-up where the second message doesn't repeat the team names and the router has to pull them from the saved state. Logged and annotated the full state trace (router decision → tool called → validation → final response) for 3 representative runs.

Compared to a single monolithic LangChain agent: routing every prediction through the same validation and formatting nodes makes the probabilistic disclaimer and the clarify-over-guess behavior guaranteed by design, instead of depending on the model remembering the rule each turn. It also made debugging easier, since a misroute points to one specific place to fix (the router's cue list) instead of digging through a full agent reasoning trace.

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