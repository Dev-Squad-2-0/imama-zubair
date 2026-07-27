# AFL Prediction System — Data Dictionary & Target Definitions
### Week 6 Day 1

## Source tables

| Table | Grain | Key columns | Join keys |
|---|---|---|---|
| `afl_players_round_by_round_stats_raw.csv` | one row per player per match | player_id, team, opponent, year, round, match_date | team + opponent + match_date |
| `team_matches_home_away_raw.csv` | one row per team per match (both sides of every match appear) | team_name, opponent, match_date, home_away, result | match_date + team_name + opponent |
| `merged_players.csv` | one row per player per season per team (split by is_finals) | player_id, year, team, is_finals | player_id + year + team |

Date range: 1983-2025 (43 seasons). 20 teams, 3,109 unique players. 2020 season is shortened (COVID). Fitzroy Lions and Brisbane Bears both stop appearing after 1996, merging into Brisbane Lions from 1997. Gold Coast Suns (2011) and GWS Giants (2012) join partway through.

## Prediction targets

| Target | Definition | Formula | Level |
|---|---|---|---|
| `match_winner` | 3-class label from home team's perspective | home team `result`: W→home_win, L→away_win, D→draw | match |
| `match_margin` | point margin (secondary target) | team_score - opponent_score (home perspective) | match |
| `top_disposal_getter` | player with most disposals | max(disposals) per match, or avg_disposals per season | match / season |
| `top_goal_kicker` | player with most goals | max(goals) per match, or avg_goals per season | match / season |
| `top_player_composite` | best overall game (fantasy-points based) | `fantasy_points` column (match) / `avg_fantasy_points` (season, from merged_players) | match / season |

**Why classification for match winner, not regression on margin:** the real question the assistant/model needs to answer is "who wins", not the exact point gap. Classification directly targets that, margin regression is kept as a secondary target since the column already exists.

**Why fantasy_points for the composite instead of a new formula:** it's already a standard, pre-computed AFL Fantasy score in the data (built from disposals, marks, tackles, goals, etc). Re-deriving a new composite risks double-counting stats already baked into it.

## Known data quality issues (and how they're handled)

| Issue | Scope | Handling |
|---|---|---|
| Inconsistent team names in `team_matches` (whitespace/tabs, "W. Bulldogs" abbreviation) | 1,574 rows | Cleaned with a `clean_team_name()` function — strips whitespace and maps to the full name used everywhere else |
| Negative disposals (impossible, disposals = kicks + handballs) | 723 rows (~0.3%) | Flagged, left as-is (too small a sample and no reliable way to guess the correct value) |
| Missing stat columns (hit_outs, contested_marks, bounces, etc.) | up to ~40% of rows depending on column | Not a data error — these stats weren't officially tracked in earlier eras. Left as null; to be handled per-column on Day 2 depending on model needs |
| No `position` field for players | all rows | Real gap in the data, not something inferred or guessed at. Forward/midfield/defender comparisons aren't possible with the current columns |

## Train/holdout split

Time-based split (not random): train on all seasons before the cutoff, hold out the most recent season(s) as test. A random split would let a model trained on rolling/form features "see" a team's future history when evaluating an earlier match, since those features are built from each team's full timeline. Sport outcomes are noisy (injuries, weather, bad luck) — a realistic accuracy ceiling for match winner is roughly 65-72%. Anything close to 90%+ would signal leakage, not a genuinely better model.
