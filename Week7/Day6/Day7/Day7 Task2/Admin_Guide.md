# Admin Guide

This guide provides instructions for administering the RealEstate Hub AI Voice Agent system.

## 1. Running the System

The recommended way to run the production system is via Docker Compose:

```bash
docker compose up --build -d
```

To stop the system gracefully:
```bash
docker compose down
```

## 2. Configuration Management

System behavior is controlled via environment variables in the `.env` file. Key configurations include:

- **Deployment**: `APP_ENV` (development/production), `WEB_CONCURRENCY`
- **Dependencies**: `REQUIRE_CALENDAR_FOR_READINESS`, `REQUIRE_EMAIL_FOR_READINESS`, `REQUIRE_VOICE_FOR_READINESS`, `REQUIRE_RAG_FOR_READINESS`
- **Paths**: `DATABASE_PATH`, `CHROMA_DIR`, `MONITORING_DB_PATH`, `GOOGLE_CREDENTIALS_PATH`
- **RAG Settings**: `RAG_WARMUP_ON_LIVE_START`, `RAG_EMBEDDING_MODEL`

## 3. Monitoring & Reporting

The system tracks detailed operational metrics in the `service_metrics` table within the SQLite database.

**Generating a Monitoring Report**:
Run the included python script to generate a summary report.

```bash
python scripts/run_monitoring_report.py --window-minutes 1440
```
*(1440 minutes = 24 hours)*

**Metrics Available**:
- Latency (Graph/API/TTS First-Byte)
- Success rates (Booking, TTS)
- Failure rates (API, Calendar, Email)
- RAG evaluation accuracy

## 4. Security Auditing

The agent logs any rejected prompt injections or unauthorized access attempts. If a user tries to extract the system prompt, request internal secrets, or act as an administrator, the deterministic security guard will block the action and log the event. Monitor these logs for malicious caller patterns.
