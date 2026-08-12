# System Architecture

## Overview
The RealEstate Hub AI Voice Agent is an intelligent conversational assistant designed for real estate inquiries, appointment booking, and customer management. It leverages a state-of-the-art conversational graph powered by LangGraph, deployed as a RESTful API using FastAPI, and containerized via Docker for reliable production environments.

## Core Components

1. **API Layer (FastAPI)**
   - Acts as the main entrypoint for client applications (Voice/Web).
   - Handles liveness/readiness probes (`/health/live`, `/health/ready`).
   - Serves monitoring metrics (`/metrics/summary`).
   - Processes conversation turns (`/v1/conversation/turn`).

2. **Orchestration Layer (LangGraph)**
   - Manages stateful conversation flows.
   - Routes intents (e.g., Small Talk, Recommendation, Booking, Rescheduling).
   - Preserves session context across turns (caller ID, extracted property preferences, appointment drafts).

3. **Security Guard**
   - A deterministic, pre-LLM security layer intercepting prompt injections, jailbreaks, and unauthorized data access requests before they reach the language model.

4. **Retrieval-Augmented Generation (RAG) Engine**
   - **Vector Database**: ChromaDB (stores property embeddings).
   - **Embedding Model**: Local sentence-transformers (e.g., `all-MiniLM-L6-v2`), lazily initialized with background warmup.
   - Provides factual real estate data to ground LLM responses and prevent hallucinations.

5. **Tool Integration**
   - **CRM (SQLite)**: Stores customer profiles, interaction history, and operational metrics.
   - **Google Calendar API**: Checks real-time availability and creates events. Built to "fail closed" to prevent double-booking.
   - **Gmail API**: Dispatches employee notifications upon successful bookings or cancellations.
   - **Voice Services**: Integrates with STT/TTS (e.g., Deepgram) for low-latency voice interactions.

## Deployment Architecture
- **Containerization**: The entire application runs within a Docker container.
- **Volumes**: Persistent storage is mounted for SQLite databases (`/app/db`), Chroma vectors, and sensitive secrets (e.g., `google_credentials.json`).
- **Monitoring**: Built-in metrics tracking for API latency, RAG accuracy, tool failure rates, and voice quality.

## System Flow
1. Audio input is transcribed to text (STT).
2. FastAPI receives the text payload.
3. LangGraph processes the text through the security guard.
4. If safe, intent routing determines if RAG, CRM, or Calendar tools are needed.
5. The LLM generates the response and determines necessary tool calls.
6. Tools execute and state is updated.
7. Text response is returned via API and converted to audio (TTS).
