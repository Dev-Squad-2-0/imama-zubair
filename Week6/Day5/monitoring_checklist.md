# AFL Assistant: Monitoring & Maintenance Checklist

This meant for whoever will check if the agent works well :D

## What to track

| Metric | Where it comes from | Why it matters |
|---|---|---|
| Response latency (p50 / p95) | `latency_ms` in `afl_agent_logs.jsonl`, per turn | Slow tool calls or a slow LLM ruins the chat feel. p95 catches the bad tail |
| Tool / node error rate | `status: "error"` or `"timeout"` log lines from `safe_node` | Tells us if predict.py, the data files, or the LLM connection are breaking, before users complain. |
| Off-topic leak rate | Manual spot check: sample turns where `intent != "off_topic"` but the query looks off-topic | Catches cases where the keyword router mis-routes something off-topic as factual and the LLM answers it anyway. |
| Injection attempts | `event: "injection_attempt"` / `"injection_blocked"` log lines | Volume trend tells us if someone is actively probing the assistant. |
| Clarification rate | `needs_clarification: true` share of turns | If this creeps up, entity resolution (team/player name matching) is probably falling behind real user phrasing. |
| Prediction accuracy drift | Weekly: compare `match_winner_model` predictions made before each round against that round's real results | The whole point of tracking this: catch the model quietly getting worse as the season's matchups change. |

## Alert thresholds (starting point, tune after a few weeks of traffic)

- p95 latency > 8 seconds sustained for 15+ minutes -> page on-call
- Error rate > 5% of turns in a rolling 30-minute window -> page on-call
- Off-topic leak rate > 2% in a weekly manual sample -> ticket to improve router keywords, not urgent
- Injection attempts > 20/hour from one `conversation_id` -> consider basic per-thread rate limiting (not yet built, flagged as a known gap below)
- Rolling 4-week prediction accuracy drops more than 5 points below the holdout baseline (66.3%) -> retrain, don't wait for the next scheduled cycle

## Cadence

- **Daily**: skim the error/timeout log lines. Two minutes, just checking nothing is silently broken.
- **Weekly**: pull the week's `eval_suite.py`-style spot check (10-15 fresh real queries from logs, hand-scored) plus the accuracy-drift check below.
- **Each new round (weekly during season)**: refresh the feature tables and re-run the holdout comparison in `eval_suite.py` / the baseline notebook.
- **Monthly**: full re-run of the 30-case `eval_suite.py` regression suite to catch anything a code change broke.

## Weekly retrain / refresh loop

1. After each round's matches are final, append the new match rows to `team_match_features_v1_*.csv` and `player_match_features_v1_*.csv` (same schema, rolling averages recomputed for the new rows).
2. Regenerate `latest_team_features.joblib` and `latest_player_features.joblib` from the updated tables (these hold each team/player's most recent rolling stats, used as the "current form" input at prediction time).
3. Re-run the Day 2 training pipeline on the updated data, save new `match_winner_model.joblib` / `top_player_model_*.joblib`.
4. Re-run the holdout comparison (model vs ladder-position baseline) on the latest rounds. If model accuracy drops below the baseline for two rounds in a row, that's the retrain trigger even outside the alert threshold above.
5. Swap the new joblib files into `models/`, redeploy. No code changes needed since `predict.py` and the agent just load whatever is in `models/`.

## Known gaps 

- No proper rate limiting yet, and only per-thread counters kept in memory (`_thread_offtopic_streak`, `_thread_injection_count` in `afl_langgraph_agent.py`). Its fine for a demo but not enough to deploy publically
- Hardcoded Logic: Since its a rule-based classifier, if asked something out of even its hardcoded afl score, it doesnt answer as intented, need to work on that
- Data recency: features are only as fresh as the last CSV refresh, there's no live fixture feed, so "current form" is really "form as of the last data pull."
