# Week 7 — Day 6 — Task 4 Monitoring Report

**Window:** Last 1440 minutes  
**Generated:** `2026-08-09T16:40:14.385203`

## Monitoring Summary

| Required Metric | Current Value |
|---|---:|
| Average latency | 4932.59 ms |
| Voice quality — average STT confidence | None |
| Voice quality — TTS success rate | 100.0% |
| Voice quality — average TTS first-byte latency | 895.74 ms |
| API failures | 0 |
| Calendar failures | 0 |
| Email failures | 0 |
| Booking success | 5/5 (100.0%) |
| RAG misses | 0/4 (0.0%) |

## Details

- Turns monitored: **303**
- Average API latency: **676.82 ms**
- TTS requests: **80/80 successful**
- Booking failures: **0**
- RAG queries: **4**
- RAG misses: **0**

## Recent Failure / Miss Events

_No recent failure or miss events were recorded._

## What Is Being Monitored

- **Average latency:** every LangGraph turn through `record_graph_turn()`.
- **Voice quality:** Deepgram STT confidence, Fish TTS first-byte latency, and TTS success/failure.
- **API failures:** provider/API errors through `record_api_request()` or `record_api_failure()`.
- **Calendar failures:** explicit monitoring events and existing `calendar_failed` CRM events.
- **Email failures:** explicit monitoring events and existing `email_failed` CRM events.
- **Booking success:** successful bookings from monitoring events or `appointment_history` compared with failed booking/calendar attempts.
- **RAG misses:** retrieval turns where the RAG layer returns zero hits.