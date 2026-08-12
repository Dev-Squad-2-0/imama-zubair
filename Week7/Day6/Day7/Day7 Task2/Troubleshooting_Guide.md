# Troubleshooting Guide

This guide covers common issues and resolutions for the RealEstate Hub AI Voice Agent.

## 1. API Returns 503 Service Unavailable on `/health/ready`
**Symptom**: The container is running, but the readiness probe fails.
**Cause**: One of the critical dependencies is unreachable.
**Resolution**:
- Check logs: `docker compose logs voice-agent-api`
- Verify Google credentials path (`GOOGLE_CREDENTIALS_PATH`). Ensure the file exists and is mounted correctly in `docker-compose.yml`.
- Verify database file permissions.

## 2. Calendar Booking Failures ("Time is already booked" but calendar is empty)
**Symptom**: Agent claims a slot is busy, but you know it's free.
**Cause**: The Google Calendar API request failed (e.g., network error, bad config). The agent "fails closed" and marks it unavailable.
**Resolution**:
- Use the diagnostic tool:
  ```bash
  python debug_calendar_availability.py "YYYY-MM-DDTHH:MM:SS"
  ```
- Inspect the `"error"` field in the JSON output to identify the exact Google API error.

## 3. High Latency During Initial Greeting
**Symptom**: The agent takes 5-10 seconds to respond to the first message.
**Cause**: The local embedding model (`all-MiniLM-L6-v2`) is initializing on the main thread.
**Resolution**:
- Ensure lazy initialization and background warmup are enabled in `.env`:
  ```env
  RAG_WARMUP_ON_LIVE_START=1
  ```

## 4. Agent Forgets Property Context (e.g., "Us se sasti")
**Symptom**: When a user asks for a cheaper option, the agent switches to small talk instead of searching.
**Cause**: The state variables `last_shown_property_ids`, `last_shown_min_price`, etc., are not being populated correctly in the graph state.
**Resolution**:
- Check the intent router logic in LangGraph. Ensure comparison phrases in English and Urdu are mapped to the Recommendation intent, not Small Talk.

## 5. Docker Path vs Windows Path Mismatch
**Symptom**: FileNotFoundError when running via Docker.
**Cause**: `.env` is configured with Windows paths (e.g., `C:\Users\...`).
**Resolution**:
- Ensure your `.env` contains Linux paths meant for the container (e.g., `/app/db/knowledge_base.db`).
- Only use Windows paths when running `python main.py` directly on the host machine.
