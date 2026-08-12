# Monitoring & Maintenance Plan

This document outlines the Service Level Agreements (SLAs), operational targets, and ongoing maintenance schedules for the RealEstate Hub AI Voice Agent to ensure consistent performance, reliability, and security in production.

## 1. Performance Targets

### 1.1 Latency Thresholds
To provide a natural, human-like voice experience, system latency must be strictly monitored. The following thresholds apply:
- **STT (Speech-to-Text)**: < 300ms (Deepgram)
- **Agent Orchestration (LangGraph)**: < 1500ms for standard turns, < 2500ms for turns involving RAG or Calendar API calls.
- **TTS (Text-to-Speech) First-Byte**: < 400ms to begin audio playback.
- **Total Turnaround Time (P95)**: < 2200ms from user finishing speech to agent starting speech.

*Alerting*: If P95 latency exceeds 2500ms for more than 5 minutes, an alert is dispatched to the engineering team.

### 1.2 Uptime Targets
- **Core API & Agent Orchestration**: 99.9% uptime (maximum of ~43 minutes of downtime per month).
- **RAG & Vector DB**: 99.9% uptime.
- **Third-Party Integrations**: Dependent on vendor SLAs (Google Calendar, Gmail, Deepgram, LLM Provider). "Fail closed" grace mechanisms are in place so the agent degrades gracefully (e.g., asking to try booking again later if Calendar is down) rather than crashing entirely.

## 2. Maintenance Schedules

### 2.1 Vector Database Refresh Schedule
- **Frequency**: Nightly (or event-driven when listings change).
- **Procedure**: 
  - Extract the delta of new, updated, or removed properties from the master CRM database.
  - Drop obsolete embeddings from ChromaDB.
  - Re-index updated descriptions using the `all-MiniLM-L6-v2` embedding model.
- **Validation**: After indexing, a small suite of automated RAG evaluations is run against known ground-truth questions before the new vector store goes live.

### 2.2 Weekly Retraining & Performance Review
- **Retraining**: No direct fine-tuning of the base LLM occurs weekly. Instead, "retraining" involves updating the few-shot examples or dynamic context window based on missed intents or user friction.
- **Log Review**: Every Friday, product managers review the `run_monitoring_report.py` output. Calls that resulted in an "Angry Customer" state or frequent fallbacks to Small Talk are reviewed via transcript.
- **Action**: Misunderstood intents are added to the routing prompt's few-shot examples.

### 2.3 Prompt Updates
- **Frequency**: Bi-weekly or as needed based on feature additions.
- **Procedure**:
  - Updates to the System Prompt (persona, instruction limits) must be tested against the internal 44-scenario test suite.
  - Changes must also pass the 6-scenario Security Prompt Injection suite to ensure new instructions do not open jailbreak vectors.
  - Deployed during low-traffic windows (e.g., 2:00 AM AST).

## 3. Data Integrity & Security

### 3.1 Backup Strategy
- **SQLite Databases (`knowledge_base.db`, CRM, Metrics)**:
  - Backups run every 6 hours using a cron job.
  - Backups are zipped and stored in a secure cloud bucket (e.g., AWS S3 or Google Cloud Storage) with a 30-day retention policy.
- **Metrics Pruning**: The `service_metrics` table is pruned of records older than 90 days to prevent disk bloat and ensure fast query times.

### 3.2 Security Review Cadence
- **Weekly**: Automated review of logs for prompt-injection attempts or unauthorized data access stopped by the deterministic security guard.
- **Monthly**: Review API key usage and billing for Deepgram, Google Cloud (Calendar/Gmail), and the LLM provider to detect anomalies.
- **Quarterly**: Audit and rotate service account credentials (`google_credentials.json`) and API keys. Verify the principle of least privilege is maintained.
