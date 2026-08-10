# Production Readiness – RealEstate Voice Agent

## Task 1 — Evaluation Suite

The production suite contains **44 conversations across 11 required categories**:
buyer, seller, investor, rental, appointment, cancellation, rescheduling,
off-topic, prompt injection, angry customer, and silent caller.

Run:

```powershell
python tests\production_eval\run_evaluation_suite.py
```

By default Calendar and email writes are mocked and CRM/trace writes are isolated to
`tests/production_eval/output/eval_<run>.db`. To deliberately exercise real Calendar/email integrations:

```powershell
$env:EVAL_REAL_WRITES="1"
python tests\production_eval\run_evaluation_suite.py
```

Outputs:
- `tests/production_eval/output/evaluation_results.json`
- `tests/production_eval/output/evaluation_results.md`

## Task 2 — Prompt Injection

16 dedicated variants cover the four requested attack families:
ignore instructions, reveal prompt, fake bookings, and internal company data.

```powershell
python tests\production_eval\run_prompt_injection_suite.py
```

Outputs:
- `prompt_injection_results.json`
- `prompt_injection_results.md`

## Task 3 — Performance Evaluation

Run Task 1 first, then:

```powershell
python tests\production_eval\run_performance_evaluation.py
```

Measures:
- turn latency: mean / p50 / p95 / max
- conversation success rate
- booking success rate
- tool failures from isolated CRM events
- RAG retrieval accuracy on 10 factual FAQ cases
- multi-turn memory accuracy
- hallucination/grounding proxy

The hallucination percentage is intentionally labeled a **proxy**: it flags unsupported
numeric claims or generated answers that miss the expected grounded fact. Human review is
still required for a final semantic hallucination score.

## Task 4 — Monitoring

`src/monitoring.py` stores metrics in `service_metrics` inside the project SQLite DB.
The FastAPI service exposes:

```text
GET /metrics/summary?window_minutes=60
```

Tracked values:
- average LangGraph turn latency
- average FastAPI latency
- Deepgram STT confidence (voice quality signal)
- Fish Audio first-byte latency and failures
- API failures
- Calendar failures
- email failures
- booking success
- RAG misses

## Task 5 — Deployment Readiness

### Local API

```powershell
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Health endpoints:

```text
GET /health/live    # process liveness
GET /health/ready   # DB + configured dependencies; HTTP 503 when not ready
GET /health         # detailed dependency breakdown
```

### Docker

```powershell
docker build -t realestate-voice-agent .
docker run --env-file .env -p 8000:8000 realestate-voice-agent
```

Or:

```powershell
docker compose up --build
```

Never bake `.env` or Google credentials into the image. Mount credentials as a read-only
file and point `GOOGLE_CREDENTIALS_PATH` to the mounted path.

### CI/CD

`.github/workflows/ci.yml` performs:
1. Python syntax compilation
2. deterministic NLU/name-memory regression tests
3. production Docker image build

The 44-conversation live LLM suite is intentionally not forced on every PR because it
requires network credentials and has provider latency/cost. Run it manually or add a
secret-backed deployment-stage job when the hosting target is finalized.
