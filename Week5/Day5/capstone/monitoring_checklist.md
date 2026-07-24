# Monitoring checklist — Web3Geeks onboarding agent

## What to track

| Metric | Source | Why it matters |
|---|---|---|
| Error rate (`status=failed` or `crashed` / total requests) | `main.py` `request_finished` log events | Catches upstream data-source breakage, malformed input spikes, or LLM outages |
| Validation-failure rate (`validation_failed` events / total) | `graph.py` `validate_input_node` | Rising rate suggests a frontend/client bug sending bad payloads, not an agent problem |
| Crew retry rate (`crew_attempts` > 1 at completion) | `run_crew_node` logs | Rising retries = model drift, prompt regression, or an upstream service.json/companies.json change breaking expected format |
| Human rejection rate (`approved=False` at `/onboard/approve`) | `human_decision` events | Sustained rise = proposal quality degrading, needs a prompt/model review |
| Latency (p50/p95 per run, per node) | timestamps around each node already logged | Node-level timing shows whether slowness is the crew, the PDF step, or an external lookup |
| Token usage & estimated cost per run | `crew_completed` event `token_usage` | Cost drift detection — catches runaway prompts or a model swap that's quietly more expensive |
| PDF generation failures | `pdf_generation_error` events | Direct blocker to deliverable — should page immediately, not just log |
| Output quality drift (spot-checked) | periodic manual sampling of `proposal_text` against eval.py criteria | Automated metrics won't catch subtle tone/accuracy decay; needs a human in the loop periodically |

## Suggested alert thresholds (tune after 1-2 weeks of real traffic to set a real baseline)

- Error rate > 5% over a rolling 1-hour window -> page on-call
- Crew retry rate > 20% of runs -> warn, investigate within 1 business day
- Human rejection rate > 30% over a rolling 7-day window -> warn, review agent prompts
- p95 latency > 45s -> warn (likely a timeout risk for the caller)
- Estimated daily cost > 150% of the trailing 7-day average -> warn, check for a prompt/model regression or an abuse pattern
- Any `pdf_generation_error` -> page immediately (blocks the actual deliverable)

## Re-evaluation cadence

- **Weekly**: re-run `eval.py`'s 8 test cases against production config, diff scores against the last run, eyeball the 2 adversarial cases specifically.
- **On any prompt/model/service-catalog change**: re-run the full eval suite before deploying, not after.
- **Monthly**: manually sample 10-15 real production proposals against the 6 evaluation criteria (Task 3) to catch drift the automated checks can't see (tone, factual grounding against real client conversations).
- **Quarterly**: revisit alert thresholds against actual observed traffic/cost baselines — thresholds set on day 1 will likely be wrong within a quarter.
