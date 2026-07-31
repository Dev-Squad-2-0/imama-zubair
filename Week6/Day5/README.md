# Week 6 Day 5 – Capstone: AFL LangGraph Assistant

## Overview

This capstone project is a production-ready AFL assistant built using LangGraph. It combines conversational AI, statistical retrieval, and machine learning predictions into a single domain-locked assistant that only answers AFL-related questions.

The assistant can answer general AFL questions, retrieve player and team statistics, compare head-to-head records, predict match winners and top-performing players, and reject off-topic or prompt-injection attempts. The system is exposed through both a FastAPI API and an optional Streamlit chat interface.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # add your API_KEY / BASE_URL (or GROQ_API_KEY if using Groq)
```

---

## Run the Streamlit UI

```bash
streamlit run streamlit_app.py
```

---

## Run the API

```bash
uvicorn api:app --reload --port 8000
```

Available endpoints:

* `POST /chat` — send a chat message and receive the assistant response
* `GET /health` — health check

---

## Run the Evaluation Suite

```bash
python eval_suite.py
```

This generates:

* `eval_results.csv`
* `eval_summary.md`

The evaluation covers:

* Factual Q&A
* Retrieval
* Prediction sanity
* Multi-turn conversations
* Scope guardrails

---

# Files

| File                                      | Purpose                                         |
| ----------------------------------------- | ----------------------------------------------- |
| `afl_langgraph_agent.py`                  | Main LangGraph workflow and orchestration       |
| `afl_chat_agent.py`                       | Day 3 conversational AFL chat agent             |
| `predict.py`                              | Machine learning prediction tools               |
| `api.py`                                  | FastAPI wrapper                                 |
| `streamlit_app.py`                        | Streamlit chat interface                        |
| `eval_suite.py`                           | Automated evaluation framework                  |
| `team_match_features_v1_2026-07-27.csv`   | Team feature dataset                            |
| `player_match_features_v1_2026-07-27.csv` | Player feature dataset                          |
| `models/`                                 | Trained ML models and feature encoders          |
| `assets/`                                 | For icons                                       |
| `monitoring_checklist.md`                 | Production monitoring checklist                 |
| `slide_outline.md`                        | Stakeholder presentation script                 |
| `executive report.pdf`                    | Final executive report                          |
| `week6_day5_capstone.ipynb`               | Executed notebook demonstrating all Day 5 tasks |

---

## Notes on what was verified

The following components were tested during development:

* The complete LangGraph workflow successfully routes between factual chat, retrieval, prediction, clarification, and off-topic handling.
* Prompt injection attempts are detected and blocked while keeping the assistant restricted to AFL topics.
* Multi-turn conversations preserve context correctly after fixing checkpoint state handling.
* FastAPI endpoint responds correctly with prediction metadata.
* Streamlit interface communicates with the LangGraph application successfully.
* The evaluation suite executes successfully across 30 test cases.
* Match winner predictions were compared against a ladder-position baseline using a time-based holdout.

---

# TASKS

# Task 1 – System Hardening

Improved the robustness of the complete assistant by implementing:

* Consistent error handling across every LangGraph node
* Timeout handling for slow tool and LLM calls
* Prediction disclaimer stating that results are model estimates, not certainties
* Prompt injection detection and logging
* Repeated off-topic abuse detection
* Structured logging for monitoring

Three prompt injection attempts were tested successfully, and the assistant remained restricted to AFL-related queries.

---

# Task 2 – Comprehensive Evaluation

Developed a complete evaluation framework covering:

* Factual AFL questions
* Retrieval accuracy
* Match prediction sanity
* Multi-turn conversations
* Scope guardrails

Implemented:

* 30 evaluation cases
* Category-wise pass rates
* Weakest-category analysis
* Comparison between the trained match winner model and a ladder-position baseline

---

# Task 3 – API & UI

Wrapped the assistant behind a FastAPI application.

Implemented:

* `POST /chat`
* `GET /health`

Also created a Streamlit interface that provides:

* Interactive chat
* Prediction responses
* Debug information
* Conversation memory

Added structured logging including:

* User query
* Intent
* Tools called
* Latency
* Errors
* Token usage (when available)

---

# Task 4 – Monitoring & Maintenance

Prepared a production monitoring plan covering:

* Response latency
* Tool failures
* Off-topic leak rate
* Prediction accuracy drift
* Weekly model retraining workflow
* Feature table refresh process

---

# Task 5 – Final Deliverables

Prepared the complete capstone deliverables:

* LangGraph application
* FastAPI API
* Streamlit UI
* Evaluation framework
* Evaluation results
* Monitoring checklist
* Executive report
* Demo script
* Executed notebook

---

# Skills Demonstrated

* LangGraph workflows
* Conversational AI
* Retrieval-Augmented Generation (RAG)
* Machine Learning deployment
* FastAPI development
* Streamlit applications
* Prompt engineering
* Tool integration
* State management
* Multi-turn conversations
* Evaluation frameworks
* Structured logging
* Production monitoring
* AI system hardening

---

# Tech Stack

* Python
* LangGraph
* LangChain
* FastAPI
* Streamlit
* Pandas
* Scikit-learn
* LightGBM
* Joblib
* Python Dotenv

---

### Author

*Imama Zubair*

AI Intern @ NetixSol
