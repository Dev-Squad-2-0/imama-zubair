"""
predict.py

Callable wrapper functions around the Day 2 AFL prediction models
These are the exact functions the Day 4 LangChain/LangGraph agent tools will wrap.

Models and lookup tables are loaded from the .joblib artifacts saved in this same folder
(produced by week6_day2_afl.ipynb, Task 5).

Two public functions:
- predict_match_winner(home_team, away_team) -> dict
- predict_top_player(team, stat_type="disposals", top_n=5) -> list[dict]
"""

import joblib
import pandas as pd

ARTIFACT_DIR = "models"

_match_model = joblib.load(f"{ARTIFACT_DIR}/match_winner_model.joblib")
_player_models = {
    "disposals": joblib.load(f"{ARTIFACT_DIR}/top_player_model_disposals.joblib"),
    "goals": joblib.load(f"{ARTIFACT_DIR}/top_player_model_goals.joblib"),
    "fantasy_points": joblib.load(f"{ARTIFACT_DIR}/top_player_model_fantasy_points.joblib"),
}
_latest_team_features = joblib.load(f"{ARTIFACT_DIR}/latest_team_features.joblib")
_latest_player_features = joblib.load(f"{ARTIFACT_DIR}/latest_player_features.joblib")
_valid_teams = joblib.load(f"{ARTIFACT_DIR}/valid_teams.joblib")

_MATCH_NUM_FEATS = [
    "home_recent_form_5", "home_avg_score_last5", "home_win_streak_entering_match", "home_days_rest",
    "home_points_before_match", "home_ladder_position_before_match",
    "home_h2h_win_rate_vs_opponent", "home_venue_win_rate",
    "away_recent_form_5", "away_avg_score_last5", "away_win_streak_entering_match", "away_days_rest",
    "away_points_before_match", "away_ladder_position_before_match",
    "away_h2h_win_rate_vs_opponent", "away_venue_win_rate",
]
_PLAYER_FEATS = ["avg_disposals_last5", "avg_goals_last5", "avg_fantasy_last5"]


def _validate_team(team_name):
    if team_name not in _valid_teams:
        raise ValueError(
            f"Unknown team '{team_name}'. Valid team names are: {', '.join(_valid_teams)}"
        )


def predict_match_winner(home_team: str, away_team: str) -> dict:
    """
    Predicts the winner of a match between two teams.

    Uses each team's most recent known rolling features (form, ladder position, etc.)
    as a stand-in for their current form, since there's no live fixture feed wired in yet.

    Args:
        home_team: exact team name, e.g. "Richmond Tigers"
        away_team: exact team name, e.g. "Carlton Blues"

    Returns:
        dict with home_team, away_team, winner, home_win_probability

    Raises:
        ValueError: if either team name isn't recognized, or home_team == away_team
    """
    _validate_team(home_team)
    _validate_team(away_team)
    if home_team == away_team:
        raise ValueError("home_team and away_team can't be the same team.")

    home_row = _latest_team_features[_latest_team_features["team_name"] == home_team].iloc[0]
    away_row = _latest_team_features[_latest_team_features["team_name"] == away_team].iloc[0]

    feat_cols = ["recent_form_5", "avg_score_last5", "win_streak_entering_match", "days_rest",
                 "points_before_match", "ladder_position_before_match",
                 "h2h_win_rate_vs_opponent", "venue_win_rate"]

    row = {}
    for c in feat_cols:
        row[f"home_{c}"] = home_row[c]
        row[f"away_{c}"] = away_row[c]

    X = pd.DataFrame([row])[_MATCH_NUM_FEATS]
    prob_home_win = float(_match_model.predict_proba(X)[0, 1])
    winner = home_team if prob_home_win >= 0.5 else away_team

    return {
        "home_team": home_team,
        "away_team": away_team,
        "winner": winner,
        "home_win_probability": round(prob_home_win, 3),
    }


def predict_top_player(team: str, stat_type: str = "disposals", top_n: int = 5) -> list:
    """
    Predicts the top players for a team, ranked by a predicted stat.

    Uses each player's most recent known rolling averages as their current form baseline.

    Args:
        team: exact team name, e.g. "Richmond Tigers"
        stat_type: one of "disposals", "goals", "fantasy_points"
        top_n: how many players to return, must be a positive integer

    Returns:
        list of dicts, sorted highest predicted stat first, each with
        player_name and predicted_<stat_type>

    Raises:
        ValueError: if team is unrecognized, stat_type isn't supported, top_n isn't
                    a positive integer, or the team has no players in the data
    """
    _validate_team(team)

    if stat_type not in _player_models:
        raise ValueError(
            f"Unknown stat_type '{stat_type}'. Must be one of: {', '.join(_player_models.keys())}"
        )

    if not isinstance(top_n, int) or top_n <= 0:
        raise ValueError("top_n must be a positive integer.")

    team_players = _latest_player_features[_latest_player_features["team"] == team].copy()
    if team_players.empty:
        raise ValueError(f"No player data found for team '{team}'.")

    model = _player_models[stat_type]
    X = team_players[_PLAYER_FEATS].fillna(team_players[_PLAYER_FEATS].median())
    team_players["predicted_" + stat_type] = model.predict(X)

    ranked = team_players.sort_values("predicted_" + stat_type, ascending=False).head(top_n)

    return ranked[["player_name", "predicted_" + stat_type]].round(
        {"predicted_" + stat_type: 1}
    ).to_dict(orient="records")
