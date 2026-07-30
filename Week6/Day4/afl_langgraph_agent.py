"""
afl_langgraph_agent.py

Week 6 Day 4 deliverable, extracted from week6_day4_langgraph_app.ipynb into an
importable module so it can be reused directly in Day 5 (and beyond) instead of
having to run everything inside a notebook.

A working LangGraph app that routes an AFL question to the right place:
- factual AFL questions  -> the Day 3 chat agent (afl_chat_agent.py)
- stat lookups           -> retrieval node (reuses Day 3's lookup logic)
- win / top-score asks   -> prediction node (wraps Day 2's models via predict.py)
- anything off-topic     -> refusal node

Every retrieval/prediction result passes through a validation node before the
user sees it, so unresolved teams/players or unsupported stat types trigger a
clarification/fallback message instead of a guess. Predictions always get a
probabilistic disclaimer attached in response_formatting_node.

Needs, in the same folder:
    models/                                       (Day 2 joblib artifacts)
    predict.py                                     (Day 2)
    afl_chat_agent.py                              (Day 3)
    team_match_features_v1_2026-07-27.csv
    player_match_features_v1_2026-07-27.csv
    .env with BASE_URL and API_KEY

Import with:

    from afl_langgraph_agent import run_turn

    out = run_turn("Who will win Richmond Tigers vs Carlton Blues?")
    print(out["final_response"])

Use the same thread_id across calls to keep multi-turn context (e.g. a
follow-up question that doesn't repeat the team/player name).
"""

import pandas as pd
import numpy as np
import joblib
import json
import os

from dotenv import load_dotenv

load_dotenv()
pd.set_option('display.max_columns', None)

team = pd.read_csv('team_match_features_v1_2026-07-27.csv')
player = pd.read_csv('player_match_features_v1_2026-07-27.csv')

print("team rows:", len(team), "| player rows:", len(player))

ARTIFACT_DIR = "models"

_match_model = joblib.load(f"{ARTIFACT_DIR}/match_winner_model.joblib")
_player_models ={
    "disposals": joblib.load(f"{ARTIFACT_DIR}/top_player_model_disposals.joblib"),
    "goals": joblib.load(f"{ARTIFACT_DIR}/top_player_model_goals.joblib"),
    "fantasy_points": joblib.load(f"{ARTIFACT_DIR}/top_player_model_fantasy_points.joblib"),
}
_latest_team_features = joblib.load(f"{ARTIFACT_DIR}/latest_team_features.joblib")
_latest_player_features = joblib.load(f"{ARTIFACT_DIR}/latest_player_features.joblib")
_valid_teams = joblib.load(f"{ARTIFACT_DIR}/valid_teams.joblib")

print(f"{len(_valid_teams)} valid teams loaded")
print(f"models loaded: match winner + 3 top player models (disposals, goals, fantasy_points)")

MODEL = "smart"

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=MODEL,
    base_url=os.environ["BASE_URL"],
    api_key=os.environ["API_KEY"],
)

PREDICTION_CUES = [
    "will win","who will win","who's going to win","who is going to win","predict",
    "winner","will beat","beat","top score","top-score","who will top score",
    "who will top-score","most disposals this week","highest fantasy this week","who will get the most",
    "gonna win","going to beat","chances of","win probability","more likely to win",
    "likely to win",
]
RETRIEVAL_CUES = [
    "recent stats", "stats", "statistics", "record against", "head to head",
    "h2h", "last round", "recent form", "average", "how many disposals",
    "how many goals", "fantasy points", "results", "last season", "record",
]
OFFTOPIC_CUES = [
    "nrl", "nba", "soccer", "cricket", "weather", "pizza", "recipe", "python",
    "capital of", "joke", "world cup", "super bowl", "fifa", "stock market",
    "movie", "song",
]

# small set of team nicknames, used only so the router can tell a query is AFL-related
# even if it doesn't hit a prediction/retrieval keyword. Full alias -> exact team name
# resolution for the actual tools comes later in Task 3 (TEAM_ALIASES).
_AFL_NICKNAME_WORDS = [
    "pies", "collingwood", "cats", "geelong", "tigers", "richmond", "blues", "carlton",
    "dees", "melbourne", "swans", "sydney", "hawks", "hawthorn", "lions", "brisbane",
    "bombers", "essendon", "saints", "st kilda", "eagles", "dogs", "bulldogs", "power",
    "suns", "giants", "gws", "dockers", "freo", "fremantle", "roos", "kangaroos", "crows",
    "adelaide",
]

_known_players_lower = {p.lower(): p for p in player["player_name"].dropna().unique()}

def mentions_known_player(query):
    ql = query.lower()
    return any(p in ql for p in _known_players_lower)

def contains_afl_context(query):
    """True if the query mentions AFL, a valid team name, a common nickname, or a known player."""
    ql = query.lower()
    if "afl" in ql:
        return True
    if any(t.lower() in ql for t in _valid_teams):
        return True
    if any(w in ql for w in _AFL_NICKNAME_WORDS):
        return True
    if mentions_known_player(query):
        return True
    return False

def classify_intent(query):
    """
    Classifies a user's question into one of four intents:
    prediction, retrieval, factual, or off_topic.
    """

    query = query.lower()

    has_prediction = any(word in query for word in PREDICTION_CUES)
    has_retrieval = any(word in query for word in RETRIEVAL_CUES)
    has_offtopic = any(word in query for word in OFFTOPIC_CUES)

    # off_topic only wins if there's no prediction/retrieval signal too
    # (a query can mention "weather" style words but still clearly be AFL related)
    if has_offtopic and not has_prediction and not has_retrieval:
        return "off_topic"

    if has_prediction:
        return "prediction"

    if has_retrieval:
        return "retrieval"

    # nothing matched: only call it factual if it actually mentions AFL,
    # a team, or a player, otherwise it's off_topic by default
    if contains_afl_context(query):
        return "factual"

    return "off_topic"

from predict import predict_match_winner, predict_top_player
from predict import _match_model, _player_models, _MATCH_NUM_FEATS, _PLAYER_FEATS
from langchain.tools import tool
import difflib

TEAM_ALIASES = {
    "pies": "Collingwood Magpies",
    "collingwood": "Collingwood Magpies",

    "cats": "Geelong Cats",
    "geelong": "Geelong Cats",

    "tigers": "Richmond Tigers",
    "richmond": "Richmond Tigers",

    "blues": "Carlton Blues",
    "carlton": "Carlton Blues",

    "dees": "Melbourne Demons",
    "melbourne": "Melbourne Demons",

    "swans": "Sydney Swans",
    "sydney": "Sydney Swans",

    "hawks": "Hawthorn Hawks",
    "hawthorn": "Hawthorn Hawks",

    "lions": "Brisbane Lions",
    "brisbane": "Brisbane Lions",

    "bombers": "Essendon Bombers",
    "essendon": "Essendon Bombers",

    "dogs": "Western Bulldogs",
    "bulldogs": "Western Bulldogs",

    "dockers": "Fremantle Dockers",
    "freo": "Fremantle Dockers",

    "crows": "Adelaide Crows",
    "adelaide": "Adelaide Crows",

    "power": "Port Adelaide Power",
    "port adelaide": "Port Adelaide Power",

    "giants": "Greater Western Sydney Giants",
    "gws": "Greater Western Sydney Giants",

    "roos": "North Melbourne Kangaroos",
    "kangaroos": "North Melbourne Kangaroos",

    "eagles": "West Coast Eagles",

    "saints": "St Kilda Saints",
    "st kilda": "St Kilda Saints",

    "suns": "Gold Coast Suns"
}

def resolve_team(team_name):
    """
    Resolves a team nickname to the exact team name used by the prediction models.
    """

    if not team_name:
        return None

    name = team_name.lower().strip()

    if name in TEAM_ALIASES:
        return TEAM_ALIASES[name]

    matches = difflib.get_close_matches(
        team_name,
        _valid_teams,
        n=1,
        cutoff=0.6
    )

    if matches:
        return matches[0]

    return None

def resolve_fixture(home_team, away_team):
    """
    Resolves the requested fixture.

    This project does not use a live AFL fixture API,
    so predictions use the latest available feature table
    as the current week's matchup.
    """

    return {
        "home_team": home_team,
        "away_team": away_team,
        "fixture": "latest available matchup"
    }

# real top-3 feature grounding, computed from the models directly (not just a
# static description). Match model is logistic regression, so we can read off
# each feature's contribution to this specific prediction. Player models are
# gradient boosting, so we use the model's overall top feature importances instead
# (per-instance contribution isn't as simple to read off a tree ensemble without SHAP).

def top_match_features(X_df):
    pre = _match_model.named_steps["pre"]
    clf = _match_model.named_steps["clf"]
    X_trans = pre.transform(X_df)
    coefs = clf.coef_[0]
    contributions = X_trans[0] * coefs
    idx_sorted = sorted(range(len(_MATCH_NUM_FEATS)), key=lambda i: -abs(contributions[i]))[:3]
    out = []
    for i in idx_sorted:
        direction = "favors the home team" if contributions[i] > 0 else "favors the away team"
        out.append(f"{_MATCH_NUM_FEATS[i]} ({direction})")
    return out

def top_player_features(stat_type):
    reg = _player_models[stat_type].named_steps["reg"]
    importances = reg.feature_importances_
    idx_sorted = sorted(range(len(_PLAYER_FEATS)), key=lambda i: -importances[i])[:3]
    return [_PLAYER_FEATS[i] for i in idx_sorted]

@tool
def match_prediction_tool(home_team: str, away_team: str):
    """
    Predict the winner of an AFL match.
    """

    home = resolve_team(home_team)
    away = resolve_team(away_team)

    if home is None or away is None:
        return "One or both team names could not be recognised."

    fixture = resolve_fixture(home, away)

    prediction = predict_match_winner(
        fixture["home_team"],
        fixture["away_team"]
    )

    # build the same feature row predict_match_winner used internally, so we can
    # explain this specific prediction rather than just describing the model in general
    home_row = _latest_team_features[_latest_team_features["team_name"] == home].iloc[0]
    away_row = _latest_team_features[_latest_team_features["team_name"] == away].iloc[0]
    feat_cols = ["recent_form_5", "avg_score_last5", "win_streak_entering_match", "days_rest",
                 "points_before_match", "ladder_position_before_match",
                 "h2h_win_rate_vs_opponent", "venue_win_rate"]
    row = {}
    for c in feat_cols:
        row[f"home_{c}"] = home_row[c]
        row[f"away_{c}"] = away_row[c]
    X = pd.DataFrame([row])[_MATCH_NUM_FEATS]

    prediction["top_features"] = top_match_features(X)
    prediction["grounding"] = (
        "Prediction uses each team's recent form (last 5 matches), "
        "ladder position before the match, "
        "and average scoring performance. "
        "Top drivers for this matchup: " + "; ".join(prediction["top_features"]) + "."
    )

    return prediction

@tool
def top_player_prediction_tool(
    team: str,
    stat_type: str = "disposals"
):
    """
    Predict the top player for an AFL team.
    """

    team = resolve_team(team)

    if team is None:
        return "Team not recognised."

    if stat_type not in _player_models:
        return f"'{stat_type}' isn't a stat this system predicts. Supported: {list(_player_models.keys())}."

    prediction = predict_top_player(
        team,
        stat_type=stat_type,
        top_n=5
    )

    top_feats = top_player_features(stat_type)

    return {
        "team": team,
        "stat_type": stat_type,
        "prediction": prediction,
        "top_features": top_feats,
        "grounding": (
            "Predictions use each player's latest rolling performance features. "
            "Top drivers for this stat: " + ", ".join(top_feats) + "."
        )
    }

def format_prediction_response(result):
    """
    Formats prediction results with confidence
    and a grounding explanation.
    """

    if "winner" in result:

        probability = result["home_win_probability"]

        return (
            f"Most likely winner: {result['winner']}\n\n"
            f"Confidence: {probability:.1%}\n\n"
            f"This is a probabilistic estimate, not a certainty.\n\n"
            f"Grounding: {result['grounding']}"
        )

    if "prediction" in result:
        preds = ", ".join(f"{p['player_name']} ({p[list(p.keys())[1]]})" for p in result["prediction"])
        return (
            f"Predicted top {result['stat_type']} for {result['team']}: {preds}\n\n"
            f"This is a probabilistic estimate based on recent form, not a certainty.\n\n"
            f"Grounding: {result['grounding']}"
        )

    return result

def validation_node(tool_result):
    """
    Validates the output returned by a retrieval or prediction tool.
    """

    if tool_result is None:
        return {
            "status": "clarify",
            "message": "I couldn't find a result. Could you rephrase your question?"
        }

    if isinstance(tool_result, str):
        return {
            "status": "clarify",
            "message": tool_result
        }

    return {
        "status": "success",
        "result": tool_result
    }

SUPPORTED_PLAYER_STATS = [
    "disposals",
    "goals",
    "fantasy_points"
]

def fallback_node(intent, stat_type=None):
    """
    Handles unsupported or ambiguous requests.
    """

    if intent == "prediction":

        if stat_type and stat_type not in SUPPORTED_PLAYER_STATS:
            return (
                f"Sorry, I can't predict '{stat_type}'. "
                "I currently support predictions for disposals, goals, "
                "and fantasy points only."
            )

    return (
        "Sorry, I can't answer that request because it's outside "
        "the scope of this AFL assistant."
    )

from typing import TypedDict
from langgraph.graph import StateGraph, END

class AFLState(TypedDict):
    user_query: str
    conversation_history: list
    intent: str
    entities: dict
    tool_result: dict
    error: str
    needs_clarification: bool
    clarification_question: str
    final_response: str
    trace: list

def extract_entities(query):
    """
    Pulls out any team names, a player name, and a stat type mentioned in the query.
    Team names are resolved to the exact dataset names right away using resolve_team,
    so downstream nodes never have to deal with nicknames.
    """
    ql = query.lower()

    team_hits = []
    for candidate in list(_valid_teams) + list(TEAM_ALIASES.keys()):
        if candidate.lower() in ql:
            resolved = resolve_team(candidate)
            if resolved and resolved not in team_hits:
                team_hits.append(resolved)

    player_hit = None
    for lp, orig in _known_players_lower.items():
        if lp in ql:
            if player_hit is None or len(lp) > len(player_hit[0]):
                player_hit = (lp, orig)
    player_hit = player_hit[1] if player_hit else None

    stat_type = "disposals"
    if "goal" in ql:
        stat_type = "goals"
    elif "fantasy" in ql:
        stat_type = "fantasy_points"

    is_top_player_request = any(p in ql for p in [
        "top score", "top-score", "top player", "most disposals", "highest fantasy"
    ])

    return {
        "teams": team_hits,
        "player": player_hit,
        "stat_type": stat_type,
        "is_top_player_request": is_top_player_request,
    }


def router_node(state):

    intent = classify_intent(state["user_query"])
    entities = extract_entities(state["user_query"])

    # multi-turn fallback: reuse last turn's teams/player if this turn didn't mention any
    if not entities["teams"] and not entities["player"] and state.get("entities"):
        prev = state["entities"]
        if prev.get("teams") or prev.get("player"):
            entities = {**entities, "teams": prev.get("teams", []), "player": prev.get("player")}

    state["intent"] = intent
    state["entities"] = entities
    state["error"] = None
    state["final_response"] = None
    state["trace"].append(f"Router -> intent={intent}, entities={entities}")

    return state

def retrieval_node(state):
    ents = state["entities"]
    q = state["user_query"].lower()
    result, error = None, None

    stat_words = ("stat", "disposal", "goal", "fantasy", "average")

    if ents["player"] and any(w in q for w in stat_words):
        rows = player[player["player_name"] == ents["player"]].sort_values("match_date")
        if rows.empty:
            error = f"No player named '{ents['player']}' found."
        else:
            r = rows.iloc[-1]
            result = {
                "player_name": r["player_name"], "team": r["team"],
                "match_date": str(r["match_date"])[:10],
                "avg_disposals_last5": round(float(r["avg_disposals_last5"]), 2),
                "avg_goals_last5": round(float(r["avg_goals_last5"]), 2) if pd.notna(r["avg_goals_last5"]) else None,
                "avg_fantasy_last5": round(float(r["avg_fantasy_last5"]), 2),
            }

    elif len(ents["teams"]) >= 2:
        a, b = ents["teams"][0], ents["teams"][1]
        h2h = team[
            ((team["team_name"] == a) & (team["opponent"] == b)) |
            ((team["team_name"] == b) & (team["opponent"] == a))
        ]
        if h2h.empty:
            error = f"No matches found between {a} and {b}."
        else:
            a_wins = int(len(h2h[(h2h["team_name"] == a) & (h2h["result"] == "W")]))
            b_wins = int(len(h2h[(h2h["team_name"] == b) & (h2h["result"] == "W")]))
            result = {"team_a": a, "team_b": b, "matches_played": int(len(h2h) // 2), f"{a}_wins": a_wins, f"{b}_wins": b_wins}

    else:
        error = "need_clarification"

    state["tool_result"] = result
    state["error"] = error
    state["trace"].append(f"retrieval_node -> result={result}, error={error}")
    return state

def prediction_node(state):
    ents = state["entities"]
    result, error = None, None

    if ents["is_top_player_request"] and len(ents["teams"]) >= 1:
        out = top_player_prediction_tool.invoke({"team": ents["teams"][0], "stat_type": ents["stat_type"]})
        if isinstance(out, str):
            error = out
        else:
            result = out

    elif len(ents["teams"]) >= 2:
        out = match_prediction_tool.invoke({"home_team": ents["teams"][0], "away_team": ents["teams"][1]})
        if isinstance(out, str):
            error = out
        else:
            result = out

    else:
        error = "need_clarification"

    state["tool_result"] = result
    state["error"] = error
    state["trace"].append(f"prediction_node -> result={result}, error={error}")
    return state

def factual_node(state):
    try:
        from afl_chat_agent import chat as day3_chat
        state["final_response"] = day3_chat(state["user_query"])
    except Exception as e:
        # fallback if the Day 3 agent / LLM isn't reachable right now
        state["final_response"] = (
            "I couldn't reach the AFL chat agent right now, but that's a general AFL "
            "question I'd normally answer directly. Try again in a moment."
        )
        state["error"] = f"factual_node fallback: {e}"
    state["trace"].append("factual_node -> routed to Day 3 chat agent")
    return state


def off_topic_node(state):
    state["final_response"] = (
        "That's outside AFL, so I can't help with it. Happy to answer anything about "
        "AFL teams, players, matches, or stats though!"
    )
    state["trace"].append("off_topic_node -> refused")
    return state

def graph_validation_node(state):
    validation = validation_node(state.get("tool_result"))

    if validation["status"] == "clarify":
        state["needs_clarification"] = True
        if state.get("error") == "need_clarification":
            if state["intent"] == "prediction":
                state["clarification_question"] = "Which two teams (or which team) did you mean? Use full names or common nicknames."
            else:
                state["clarification_question"] = "Which player or which two teams did you mean?"
        else:
            state["clarification_question"] = validation["message"]
    else:
        state["needs_clarification"] = False

    state["trace"].append(f"validation_node -> needs_clarification={state['needs_clarification']}")
    return state


def response_formatting_node(state):
    if state.get("final_response"):
        state["trace"].append("response_formatting_node -> passthrough (already formatted)")
        return state

    if state.get("needs_clarification"):
        state["final_response"] = state["clarification_question"]
        state["trace"].append("response_formatting_node -> asked for clarification")
        return state

    intent = state["intent"]
    result = state["tool_result"]

    if intent == "prediction":
        state["final_response"] = format_prediction_response(result)
    elif intent == "retrieval":
        state["final_response"] = f"Here's what the data shows: {result}"
    else:
        state["final_response"] = "Sorry, I couldn't process that."

    state["trace"].append("response_formatting_node -> built final response")
    return state


def route_from_router(state):
    return state["intent"]

def route_from_validation(state):
    return "clarify" if state["needs_clarification"] else "format"

from langgraph.checkpoint.memory import InMemorySaver

graph = StateGraph(AFLState)
graph.add_node("router", router_node)
graph.add_node("retrieval", retrieval_node)
graph.add_node("prediction", prediction_node)
graph.add_node("factual", factual_node)
graph.add_node("off_topic", off_topic_node)
graph.add_node("validation", graph_validation_node)
graph.add_node("response_formatting", response_formatting_node)

graph.set_entry_point("router")
graph.add_conditional_edges("router", route_from_router, {
    "retrieval": "retrieval", "prediction": "prediction",
    "factual": "factual", "off_topic": "off_topic",
})
graph.add_edge("retrieval", "validation")
graph.add_edge("prediction", "validation")
graph.add_conditional_edges("validation", route_from_validation, {
    "clarify": "response_formatting", "format": "response_formatting",
})
graph.add_edge("factual", "response_formatting")
graph.add_edge("off_topic", "response_formatting")
graph.add_edge("response_formatting", END)

checkpointer = InMemorySaver()
app = graph.compile(checkpointer=checkpointer)

def run_turn(query, thread_id="afl-demo"):
    state = {
        "user_query": query, "conversation_history": [], "intent": None,
        "entities": {}, "tool_result": None, "error": None,
        "needs_clarification": False, "clarification_question": None,
        "final_response": None, "trace": [],
    }
    return app.invoke(state, config={"configurable": {"thread_id": thread_id}})

