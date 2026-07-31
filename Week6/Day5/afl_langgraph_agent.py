"""
afl_langgraph_agent.py

Week 6 Day 4 deliverable

A working LangGraph app that routes an AFL question to the right place:
- factual AFL questions  -> the Day 3 chat agent (afl_chat_agent.py)
- stat lookups           -> retrieval node (reuses Day 3's lookup logic)
- win / top-score asks   -> prediction node (wraps Day 2's models via predict.py)
- anything off-topic     -> refusal node

Every retrieval/prediction result passes through a validation node before the
user sees it, so unresolved teams/players or unsupported stat types trigger a
clarification/fallback message instead of a guess. Predictions always get a
probabilistic disclaimer attached in response_formatting_node

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
import time
import logging
import traceback
import functools
import concurrent.futures

from dotenv import load_dotenv

load_dotenv()
pd.set_option('display.max_columns', None)

# ------------------------------------------------------------------
# TASK 1 (Day 5): SYSTEM HARDENING
# ------------------------------------------------------------------
# Adds: structured JSON logging, a timeout wrapper for slow tool/LLM calls,
# a safe_node decorator so one node crashing never breaks the whole graph,
# and simple abuse handling (repeated off-topic probing + prompt-injection
# detection). None of this changes the Day 3/4 routing or prediction logic.

LOG_PATH = "afl_agent_logs.jsonl"
_logger = logging.getLogger("afl_agent")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _handler = logging.FileHandler(LOG_PATH)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)


def log_event(**fields):
    """Writes one structured JSON line per event. Feeds the monitoring plan (Task 4)."""
    fields["ts"] = time.time()
    try:
        _logger.info(json.dumps(fields, default=str))
    except Exception:
        pass


TOOL_TIMEOUT_SECONDS = 30
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)


def run_with_timeout(fn, *args, timeout=TOOL_TIMEOUT_SECONDS, **kwargs):
    """Runs fn with a hard timeout so a slow tool/LLM call can't hang a turn."""
    future = _executor.submit(fn, *args, **kwargs)
    return future.result(timeout=timeout)


def safe_node(node_fn):
    """
    Wraps a graph node so an unexpected exception never crashes the app.
    Logs the failure and sets a clear, consistent fallback response instead
    of letting the graph error out.
    """
    @functools.wraps(node_fn)
    def wrapper(state):
        try:
            return node_fn(state)
        except concurrent.futures.TimeoutError:
            state["error"] = f"{node_fn.__name__} timed out"
            state["final_response"] = (
                "That took too long to look up, so I stopped waiting. "
                "Please try again, maybe with a simpler question."
            )
            state.setdefault("trace", []).append(f"{node_fn.__name__} -> TIMEOUT")
            log_event(node=node_fn.__name__, status="timeout")
            return state
        except Exception as e:
            state["error"] = f"{node_fn.__name__} failed: {e}"
            state["final_response"] = (
                "Something went wrong answering that. Please rephrase, "
                "or ask about an AFL team, player, match, or stat."
            )
            state.setdefault("trace", []).append(f"{node_fn.__name__} -> ERROR: {e}")
            log_event(node=node_fn.__name__, status="error", error=str(e),
                      traceback=traceback.format_exc(limit=3))
            return state
    return wrapper


# ---- Prompt injection / scope-override detection -------------------------
# The router here is rule-based (keyword + entity matching), not an LLM
# decision, so it can't be talked out of its routing by clever phrasing.
# The one place an LLM sees raw user text is factual_node (Day 3 chat agent),
# so that's where injection attempts matter. We flag common override patterns
# so they get logged and the system prompt gets an extra reminder that turn,
# instead of silently trusting the user's text.

INJECTION_PATTERNS = [
    "ignore previous instructions", "ignore all previous", "ignore the above",
    "disregard your instructions", "disregard the rules", "you are now",
    "pretend you are", "new instructions:", "system prompt",
    "reveal your prompt", "forget your rules", "jailbreak",
    "you are no longer", "from now on you", "developer mode",
]


def detect_injection_attempt(query):
    ql = query.lower()
    return any(p in ql for p in INJECTION_PATTERNS)


# ---- Basic abuse / repeated off-topic probing tracking --------------------
# Simple in-memory counters per thread_id. Not a production rate limiter, but
# enough to show the pattern: after repeated off-topic or injection attempts
# on the same thread, the refusal gets firmer instead of staying identical.

_thread_offtopic_streak = {}
_thread_injection_count = {}

OFFTOPIC_STREAK_WARNING = 3
INJECTION_COUNT_WARNING = 2

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

# MODEL = "smart"

# from langchain_openai import ChatOpenAI

# llm = ChatOpenAI(
#     model=MODEL,
#     base_url=os.environ["BASE_URL"],
#     api_key=os.environ["API_KEY"],
# )

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
    "how many goals", "fantasy points", "results", "last season", "record", "vs", "versus"
]
OFFTOPIC_CUES = [
    "nrl", "nba", "soccer", "cricket", "weather", "pizza", "recipe", "python",
    "capital of", "joke", "world cup", "super bowl", "fifa", "stock market",
    "movie", "song",
]

#for day 5, im adding these follow_up_words so that the router can detect follow-up questions that don't explicitly mention a team/player name, but are clearly related to the previous turn's context. This helps maintain multi-turn context in the conversation.
# FOLLOW_UP_WORDS = {
#     "yes","yeah", "ye","yep","sure","ok","okay","pls","please", "plz", "ofcouse", "absolutely", "definitely", "certainly", "indeed"
# }


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
    thread_id: str
    conversation_history: list
    intent: str
    entities: dict
    tool_result: dict
    error: str
    needs_clarification: bool
    clarification_question: str
    final_response: str
    trace: list
    injection_flagged: bool
    offtopic_streak: int

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


@safe_node
def router_node(state):

    thread_id = state.get("thread_id", "default")
    query = state["user_query"].lower().strip()

    history = state.get("conversation_history", [])

    FOLLOW_UP_WORDS = {
        "yes", "yeah", "yep", "sure",
        "ok", "okay", "pls", "please",
        "yes please"
    }

    # ----------------------------------------------------
    # Follow-up to previous clarification
    # ----------------------------------------------------
    if history and query in FOLLOW_UP_WORDS:

        last = history[-1]

        if (
            last.get("role") == "assistant"
            and last.get("needs_clarification")
        ):

            state["intent"] = last["intent"]
            state["entities"] = last["entities"]
            state["trace"].append("Router -> follow-up clarification")

            return state

    intent = classify_intent(query)
    entities = extract_entities(query)

    # multi-turn fallback: reuse last turn's teams/player if this turn didn't mention any
    if not entities["teams"] and not entities["player"] and state.get("entities"):
        prev = state["entities"]
        if prev.get("teams") or prev.get("player"):
            entities = {**entities, "teams": prev.get("teams", []), "player": prev.get("player")}

    # abuse handling: prompt-injection attempts never change routing (it's rule
    # based), we just flag + log them and force the query off-topic-safe if the
    # injected text is trying to smuggle in an unrelated request.
    injection = detect_injection_attempt(query)
    if injection:
        _thread_injection_count[thread_id] = _thread_injection_count.get(thread_id, 0) + 1
        log_event(event="injection_attempt", thread_id=thread_id, query=query,
                  count=_thread_injection_count[thread_id])

    # abuse handling: track consecutive off-topic turns per thread
    if intent == "off_topic":
        _thread_offtopic_streak[thread_id] = _thread_offtopic_streak.get(thread_id, 0) + 1
    else:
        _thread_offtopic_streak[thread_id] = 0

    state["intent"] = intent
    state["entities"] = entities
    state["error"] = None
    state["final_response"] = None
    state["injection_flagged"] = injection
    state["offtopic_streak"] = _thread_offtopic_streak.get(thread_id, 0)
    state["trace"].append(f"Router -> intent={intent}, entities={entities}, injection_flagged={injection}")

    return state

@safe_node
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

    elif len(ents["teams"]) == 1:

        team_name = ents["teams"][0]

        rows = team[
            team["team_name"] == team_name
        ].sort_values("match_date")

        if rows.empty:
            error = f"No data found for {team_name}."

        else:
            r = rows.iloc[-1]

            result = {
                "team": str(r["team_name"]),
                "recent_form_5": int(r["recent_form_5"]),
                "avg_score_last5": round(float(r["avg_score_last5"]), 1),
                "win_streak": int(r["win_streak_entering_match"]),
                "days_rest": int(r["days_rest"]),
                "ladder_position": int(r["ladder_position_before_match"]),
                "points": int(r["points_before_match"]),
                "venue_win_rate": round(float(r["venue_win_rate"]), 2),
                "h2h_win_rate": round(float(r["h2h_win_rate_vs_opponent"]), 2)
            }
                    
    else:
        error = "need_clarification"

    state["tool_result"] = result
    state["error"] = error
    state["trace"].append(f"retrieval_node -> result={result}, error={error}")
    return state

@safe_node
def prediction_node(state):
    ents = state["entities"]
    result, error = None, None

    if ents["is_top_player_request"] and len(ents["teams"]) >= 1:
        out = run_with_timeout(
            top_player_prediction_tool.invoke,
            {"team": ents["teams"][0], "stat_type": ents["stat_type"]},
        )
        if isinstance(out, str):
            error = out
        else:
            result = out

    elif len(ents["teams"]) >= 2:
        out = run_with_timeout(
            match_prediction_tool.invoke,
            {"home_team": ents["teams"][0], "away_team": ents["teams"][1]},
        )
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

@safe_node
def factual_node(state):
    query = state["user_query"]
    if state.get("injection_flagged"):
        # the query looked like a scope-override attempt, so we don't send it
        # to the LLM as-is. The Day 3 agent already has an AFL-only system
        # prompt, this is just belt-and-braces logging + a direct refusal
        # instead of trusting the LLM to resist every phrasing on its own.
        state["final_response"] = (
            "I can't follow instructions that try to change what I do. "
            "I only answer AFL questions, happy to help with one of those."
        )
        state["trace"].append("factual_node -> blocked (injection pattern detected)")
        log_event(event="injection_blocked", query=query)
        return state

    try:
        from afl_chat_agent import chat as day3_chat

        result = run_with_timeout(
            day3_chat,
            query,
            timeout=TOOL_TIMEOUT_SECONDS
        )

        state["final_response"] = result["answer"]
        state["token_usage"] = result.get("token_usage")
    except concurrent.futures.TimeoutError:
        state["final_response"] = (
            "That took too long to answer. Please try again, or ask something more specific."
        )
        state["error"] = "factual_node timeout"
    except Exception as e:
        # fallback if the Day 3 agent / LLM isn't reachable right now
        state["final_response"] = (
            "I couldn't reach the AFL chat agent right now, but that's a general AFL "
            "question I'd normally answer directly. Try again in a moment."
        )
        state["error"] = f"factual_node fallback: {e}"
    state["trace"].append("factual_node -> routed to Day 3 chat agent")
    return state


@safe_node
def off_topic_node(state):
    streak = state.get("offtopic_streak", 0)
    if streak >= OFFTOPIC_STREAK_WARNING:
        state["final_response"] = (
            "That's still outside AFL. This assistant only covers AFL teams, players, "
            "matches, and stats, so unrelated questions won't get an answer here no "
            "matter how they're phrased."
        )
    else:
        state["final_response"] = (
            "That's outside AFL, so I can't help with it. Happy to answer anything about "
            "AFL teams, players, matches, or stats though!"
        )
    state["trace"].append(f"off_topic_node -> refused (streak={streak})")
    return state

@safe_node
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


@safe_node
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

        # Head-to-head
        if isinstance(result, dict) and "matches_played" in result:
            state["final_response"] = (
                f"{result['team_a']} and {result['team_b']} have played "
                f"{result['matches_played']} matches.\n\n"
                f"• {result['team_a']} wins: {result[result['team_a'] + '_wins']}\n\n"
                f"• {result['team_b']} wins: {result[result['team_b'] + '_wins']}"
            )

        # Player stats
        elif isinstance(result, dict) and "player_name" in result:

            goals = result.get("avg_goals_last5")

            if goals is None or pd.isna(goals):
                goals_text = "N/A"
            else:
                goals_text = f"{goals:.1f}"

            state["final_response"] = (
                f"Here are the latest rolling stats for {result['player_name']} "
                f"({result['team']}) as of {result['match_date']}:\n\n"
                f"• Average disposals (last 5): {result['avg_disposals_last5']:.1f}\n\n"
                f"• Average goals (last 5): {goals_text}\n\n"
                f"• Average fantasy points (last 5): {result['avg_fantasy_last5']:.1f}"
            )

        # team stats
        # Team stats
        elif isinstance(result, dict) and "recent_form_5" in result:
                state["final_response"] = (
                    f"Here are the latest stats for **{result['team']}**:\n\n"
                    f"• Ladder position: {result['ladder_position']}\n\n"
                    f"• Ladder points: {result['points']}\n\n"
                    f"• Average score (last 5): {result['avg_score_last5']:.1f}\n\n"
                    f"• Wins in last 5 matches: {result['recent_form_5']}/5\n\n"
                    f"• Current win streak: {result['win_streak']}\n\n"
                    f"• Days since last match: {result['days_rest']}\n\n"
                    f"• Venue win rate: {result['venue_win_rate']:.0%}\n\n"
                    f"• Head-to-head win rate: {result['h2h_win_rate']:.0%}"
                )

        else:
            state["final_response"] = str(result)

    else:
        state["final_response"] = "Sorry, I couldn't process that."

    # -----------------------------
    # Update conversation history
    # -----------------------------
    history = state.get("conversation_history", []).copy()

    history.append({
        "role": "user",
        "content": state["user_query"]
    })

    history.append({
        "role": "assistant",
        "content": state["final_response"],
        "intent": state["intent"],
        "entities": state["entities"],
        "needs_clarification": state.get("needs_clarification", False)
    })

    # keep last 20 messages
    state["conversation_history"] = history[-20:]

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
    # BUGFIX (Day 5 hardening, found via multi-turn eval cases): passing a
    # fully reset state dict on every call overwrites the checkpointed
    # "entities" from the previous turn *before* the router even runs, since
    # LangGraph does a last-write-wins merge on plain (non-reducer) keys. That
    # silently broke pronoun/topic follow-ups like "who's more likely to win
    # between them". Fix: only send the full reset state on a thread's first
    # turn; after that, send a partial update so the checkpointed entities,
    # trace, etc. survive into router_node's multi-turn fallback.
    config = {"configurable": {"thread_id": thread_id}}
    existing = app.get_state(config)

    if not existing.values:
        state = {
            "user_query": query, "thread_id": thread_id, "conversation_history": [], "intent": None,
            "entities": {}, "tool_result": None, "error": None,
            "needs_clarification": False, "clarification_question": None,
            "final_response": None, "trace": [], "injection_flagged": False, "offtopic_streak": 0,
            "token_usage": None,
        }
    else:
        state = {
            "user_query": query, "thread_id": thread_id,
            "final_response": None, "tool_result": None, "error": None, "token_usage": None,
        }

    start = time.time()
    out = app.invoke(state, config=config)
    print(out["conversation_history"])
    latency_ms = round((time.time() - start) * 1000, 1)

    tools_called = []
    if out.get("intent") == "prediction":
        tools_called = ["match_prediction_tool" if len(out.get("entities", {}).get("teams", [])) >= 2
                         else "top_player_prediction_tool"]
    elif out.get("intent") == "retrieval":
        tools_called = ["retrieval_lookup"]
    elif out.get("intent") == "factual":
        tools_called = ["day3_chat_agent"]

    log_event(
        event="turn_complete",
        thread_id=thread_id,
        query=query,
        intent=out.get("intent"),
        tools_called=tools_called,
        latency_ms=latency_ms,
        error=out.get("error"),
        injection_flagged=out.get("injection_flagged", False),
        needs_clarification=out.get("needs_clarification", False),
    )

    out["latency_ms"] = latency_ms
    out["tools_called"] = tools_called
    out["token_usage"] = out.get("token_usage")
    return out


