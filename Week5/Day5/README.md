# Week 5 Day 5 – Capstone: Web3Geeks Client Onboarding Agent

## Overview

This capstone project is a production-ready AI client onboarding system for Web3Geeks. It automates the proposal creation process by combining LangGraph for workflow orchestration and CrewAI for role-based collaboration. The system validates client requests, researches company information, recommends services, generates a proposal, includes a human approval checkpoint, and creates a client-ready PDF.

---


## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in API_KEY / BASE_URL, same pattern as day 3/4
```

## Run the API

```bash
uvicorn main:app --reload
```

- `POST /onboard` — start a run. Returns either `completed`, `failed`, or
  `awaiting_approval` (with a `thread_id` and `proposal_preview`).
- `POST /onboard/approve` — resume a paused run with `{thread_id, approved, feedback}`.
- `GET /onboard/{thread_id}/download` — fetch the generated proposal PDF once completed.
- `GET /health` — health check.

## Run the evaluation suite

```bash
python eval.py           # live run against your real .env — makes real LLM calls
python eval_dry_run.py    # stubbed run, no credentials needed, proves the harness itself works
```

Both write `eval_results.md` and `eval_results_raw.json`. The `eval_dry_run.py`
output currently in this folder is illustrative (hand-written proposal text,
not model output) — re-run `eval.py` with real credentials for actual scores,
especially `factual_accuracy` and `tone_quality`, which need a manual read.


## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI wrapper |
| `graph.py` | LangGraph control flow: validate -> gather info -> run crew -> human approval -> generate PDF |
| `crew.py` | CrewAI proposal team (3 agents, sequential process) |
| `tools.py` | `calculator` (reused from day 1/2), `company_lookup`, `service_lookup` |
| `pdf_gen.py` | Renders the approved proposal text into a client-facing PDF |
| `schemas.py` | Pydantic request/response models (API-boundary validation) |
| `logging_config.py` | Structured JSON logging used throughout the graph |
| `eval.py` / `eval_dry_run.py` | Evaluation harness (8 test cases, 2 edge, 1 adversarial) |
| `data/companies.json` | Mock CRM |
| `data/services.json` | Web3Geeks service catalog |
| `monitoring_checklist.md` | Task 4 production monitoring checklist |
| `slide_outline.md` | Task 5 stakeholder presentation outline |
| `executive_report.pdf` | Task 5 executive report  |

## Notes on what was actually verified in this environment

What *was* verified by actually running the code:
- The full LangGraph graph compiles and routes correctly (validation failure
  path, business-rule validation path, and the crew-retry-then-fail path were
  all exercised live against a dummy endpoint, producing clean structured
  logs and a graceful `failed` response rather than a crash).
- The FastAPI app boots and both validation layers (Pydantic + graph-level)
  correctly return 422 / a clean `failed` status respectively.
- `eval_dry_run.py` exercises the entire evaluation pipeline — including the
  self-correction retry catching a "bad" first attempt on the adversarial
  case and the human-approval interrupt firing correctly — with stubbed crew
  output standing in for real model calls.

---

# TASKS


# Task 1 – System Design

- Designed a real-world Web3Geeks client onboarding and proposal generation system.
- Created an architecture diagram showing LangGraph nodes, CrewAI agents, tools, data sources, state flow, and the human approval checkpoint.
- Chose a hybrid architecture:
  - **LangGraph** for workflow control, validation, retries, and state management.
  - **CrewAI** for collaborative proposal generation using specialized agents.
- Documented the business objective and framework selection rationale.

---

# Task 2 – End-to-End System

Built the complete onboarding workflow featuring:

- Input validation using Pydantic
- Company lookup from a local CRM (`companies.json`)
- Service catalog lookup (`services.json`)
- CrewAI proposal generation with:
  - Client Research Agent
  - Solution Architect
  - Proposal Writer
- Budget calculations
- Self-correction and retry logic
- Human approval checkpoint before proposal completion
- Automatic proposal PDF generation
- Graceful handling of invalid input, tool failures, and model errors

---

# Task 3 – Evaluation Framework

Developed an evaluation pipeline that includes:

- 8 test cases
- Edge cases and adversarial inputs
- Automated scoring for:
  - Task success
  - Completeness
  - Safety
  - Latency and cost
- Manual evaluation for factual accuracy and proposal quality
- Evaluation results exported to Markdown and JSON

---

# Task 4 – API & Monitoring

Wrapped the workflow in a FastAPI application.

Implemented:

- `POST /onboard`
- `POST /onboard/approve`
- `GET /onboard/{thread_id}/download`
- `GET /health`

Added structured logging for:

- Requests
- Validation
- Tool usage
- Crew execution
- Token usage
- Latency
- Errors
- PDF generation

Also created a production monitoring checklist covering error rates, latency, cost, and output quality.

---

# Task 5 – Final Deliverables

Prepared the complete capstone deliverables:

- Executive report (PDF)
- Architecture diagram
- Evaluation results
- Monitoring checklist
- Stakeholder presentation outline
- Proposal PDF generation
- Complete runnable codebase

---

# Skills Demonstrated

- LangGraph workflows
- CrewAI multi-agent systems
- Hybrid AI architecture
- FastAPI development
- State management
- Prompt engineering
- Tool integration
- Human-in-the-loop workflows
- Evaluation frameworks
- Logging and monitoring
- PDF generation
- Production-ready system design

---

# Tech Stack

- Python
- LangGraph
- CrewAI
- FastAPI
- Pydantic
- ReportLab
- Python Dotenv

---

### Author
Imama Zubair 
AI Intern @ NetixSol