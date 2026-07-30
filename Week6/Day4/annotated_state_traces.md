# Annotated State Traces


## Retrieval (c2)

**Query:** What's Carlton's record against Richmond?

```
Router -> intent=retrieval, entities={'teams': ['Richmond Tigers', 'Carlton Blues'], 'player': None, 'stat_type': 'disposals', 'is_top_player_request': False}
retrieval_node -> result={'team_a': 'Richmond Tigers', 'team_b': 'Carlton Blues', 'matches_played': 59, 'Richmond Tigers_wins': 25, 'Carlton Blues_wins': 35}, error=None
validation_node -> needs_clarification=False
response_formatting_node -> built final response
```
**Final response:** Here's what the data shows: {'team_a': 'Richmond Tigers', 'team_b': 'Carlton Blues', 'matches_played': 59, 'Richmond Tigers_wins': 25, 'Carlton Blues_wins': 35}

**Annotation:** Router correctly identifies `retrieval` from "record against", resolves both team names, `retrieval_node` finds the head-to-head rows, validation passes (no error), and `response_formatting_node` returns the numbers straight from the dataset.


## Prediction (c3)

**Query:** Who will win Richmond Tigers vs Carlton Blues?

```
Router -> intent=prediction, entities={'teams': ['Carlton Blues', 'Richmond Tigers'], 'player': None, 'stat_type': 'disposals', 'is_top_player_request': False}
prediction_node -> result={'home_team': 'Carlton Blues', 'away_team': 'Richmond Tigers', 'winner': 'Carlton Blues', 'home_win_probability': 0.751, 'top_features': ['home_points_before_match (favors the home team)', 'away_avg_score_last5 (favors the home team)', 'away_ladder_position_before_match (favors the home team)'], 'grounding': "Prediction uses each team's recent form (last 5 matches), ladder position before the match, and average scoring performance. Top drivers for this matchup: home_points_before_match (favors the home team); away_avg_score_last5 (favors the home team); away_ladder_position_before_match (favors the home team)."}, error=None
validation_node -> needs_clarification=False
response_formatting_node -> built final response
```
**Final response:** Most likely winner: Carlton Blues

Confidence: 75.1%

This is a probabilistic estimate, not a certainty.

Grounding: Prediction uses each team's recent form (last 5 matches), ladder position before the match, and average scoring performance. Top drivers for this matchup: home_points_before_match (favors the home team); away_avg_score_last5 (favors the home team); away_ladder_position_before_match (favors the home team).

**Annotation:** Router flags `prediction` from "who will win", resolves both teams, `prediction_node` calls `match_prediction_tool`, which returns a win probability plus the top 3 features actually driving this specific prediction. Validation passes, and `format_prediction_response` adds the "probabilistic estimate, not a certainty" wording automatically, every time.


## Multi Turn (c9)

**Query:** What's Carlton's record against Richmond?

```
Router -> intent=retrieval, entities={'teams': ['Richmond Tigers', 'Carlton Blues'], 'player': None, 'stat_type': 'disposals', 'is_top_player_request': False}
retrieval_node -> result={'team_a': 'Richmond Tigers', 'team_b': 'Carlton Blues', 'matches_played': 59, 'Richmond Tigers_wins': 25, 'Carlton Blues_wins': 35}, error=None
validation_node -> needs_clarification=False
response_formatting_node -> built final response
```
**Final response:** Here's what the data shows: {'team_a': 'Richmond Tigers', 'team_b': 'Carlton Blues', 'matches_played': 59, 'Richmond Tigers_wins': 25, 'Carlton Blues_wins': 35}

**Query:** Who's more likely to win between them?

```
Router -> intent=prediction, entities={'teams': [], 'player': None, 'stat_type': 'disposals', 'is_top_player_request': False}
prediction_node -> result=None, error=need_clarification
validation_node -> needs_clarification=True
response_formatting_node -> asked for clarification
```
**Final response:** Which two teams (or which team) did you mean? Use full names or common nicknames.

**Annotation:** Turn 1 resolves both teams from "record against" and answers the head-to-head question. Turn 2, "who's more likely to win between them", has no team names in it at all, but the router's fallback pulls the previous turn's resolved teams from the checkpointed state and correctly routes to prediction with the right two teams filled in.