# API Documentation

## Base URL
When running locally via Docker Compose, the API is available at:
`http://localhost:8000`

## Endpoints

### 1. Conversation Turn
Process a single conversational turn from the user and receive the agent's response.

- **Method**: `POST`
- **Path**: `/v1/conversation/turn`
- **Content-Type**: `application/json`

**Request Body**:
```json
{
  "session_id": "string",
  "customer_text": "string",
  "caller_id": "string"
}
```
*Note: `session_id` and `caller_id` are used to maintain conversation history and CRM context.*

**Response**:
```json
{
  "response": "string",
  "state_updates": {
    "intent": "string",
    "appointment_status": "string"
  }
}
```

### 2. Readiness Check
Verifies if the application and all required downstream dependencies (DB, LLM, Google APIs) are ready to serve traffic.

- **Method**: `GET`
- **Path**: `/health/ready`

**Response (Success)**: `200 OK`
**Response (Failure)**: `503 Service Unavailable`

### 3. Liveness Check
Verifies if the API process is running.

- **Method**: `GET`
- **Path**: `/health/live`

### 4. General Health
General health overview.

- **Method**: `GET`
- **Path**: `/health`

### 5. Metrics Summary
Retrieve operational metrics for the agent.

- **Method**: `GET`
- **Path**: `/metrics/summary`
- **Query Parameters**:
  - `window_minutes` (optional, default=60): Time window for metrics aggregation.

**Response**:
```json
{
  "latency_ms": 1200,
  "success_rate": 0.98,
  "tool_failure_rate": 0.01
}
```
