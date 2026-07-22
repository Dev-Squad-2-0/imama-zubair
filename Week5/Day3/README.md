# Week 5 Day 3: LangGraph — Stateful, Multi-Step & Cyclical Agent Workflows
# LangGraph Laptop Recommendation Agent

## Overview

This project explores **LangGraph** by building a stateful AI agent that recommends laptops from a local product catalog. Unlike a standard LangChain agent, this workflow uses a graph structure with conditional routing, self-correction loops, human approval, and persistent state management.

The project demonstrates how LangGraph gives fine-grained control over multi-step agent workflows while maintaining conversation state across executions.

---

## Objectives

* Learn LangGraph's graph-based workflow model.
* Design a shared state object for agent execution.
* Build a multi-node agent workflow.
* Implement conditional routing and self-correction loops.
* Add a human-in-the-loop approval step.
* Persist agent state using checkpoints.
* Explore state history and replay for debugging.

---

## Input

### Product Database

* `products.json`
* Contains a small catalog of laptops including:

  * Name
  * Price
  * Battery life
  * RAM

### User Input

Natural language customer requests, for example:

> "I need a budget laptop with good battery life for university."

---

## Features

* Planning customer requirements
* Product retrieval from a local JSON database
* AI-generated laptop recommendations
* Self-critique with quality scoring
* Automatic retry loop for low-quality responses
* Human approval before finalizing recommendations
* Persistent state using `MemorySaver`
* State history and replay (time travel) for debugging

---

## Technologies Used

* Python
* LangGraph
* LangChain
* LangChain OpenAI
* OpenAI-compatible API
* Jupyter Notebook
* JSON
* python-dotenv

---

## Project Structure

```
LangGraph-Agent/
│
├── products.json
├── week5_day3_langgraph.ipynb
├── .env (.gitignore)
├── README.md
└── requirements.txt
```

---

## How to Run

- Install the dependencies: `pip install -r requirements.txt`
- Add your `API_KEY` and `BASE_URL` to a `.env` file.
- Open the notebook and run all cells in order.


## Workflow
```
                 ┌──────────┐
                 │  START   │
                 └────┬─────┘
                      ▼
                 ┌──────────┐
                 │   plan   │   turn the customer query into search criteria
                 └────┬─────┘
                      ▼
                 ┌──────────┐
                 │ retrieve │   look up matching laptops in products.json
                 └────┬─────┘
                      ▼
                 ┌──────────┐
          ┌────▶ │ generate │   draft a recommendation from retrieved products
          │      └────┬─────┘
          │           ▼
          │      ┌──────────┐
          │      │ critique │   score the draft, decide pass/fail
          │      └────┬─────┘
          │           │  conditional edge
          │  score < 7 and retries < max_retries
          └───────────┘
                      │  else (score >= 7, or retries exhausted)
                      ▼
              ┌────────────────┐
              │ human_approval │◀── INTERRUPT: graph pauses here
              └────────┬───────┘
                        │ resumed with approved = True/False
             ┌──────────┴───────────┐
             ▼                      ▼
      ┌─────────────┐        ┌───────────┐
      │  finalize   │        │  rejected │
      └──────┬──────┘        └─────┬─────┘
             ▼                      ▼
          ┌──────────────────────────┐
          │           END            │
          └──────────────────────────┘
```

---

## What I Learned

* How LangGraph represents workflows as graphs instead of a simple agent loop.
* How a shared state object passes information between nodes.
* How conditional edges enable branching and self-correcting workflows.
* How retries can prevent poor-quality outputs while avoiding infinite loops.
* How human approval can safely pause and resume agent execution.
* How checkpointers preserve state and make replay/debugging much easier.

---

## Skills Demonstrated

* LangGraph
* LangChain
* AI Agents
* Stateful Workflows
* Conditional Routing
* Human-in-the-Loop Systems
* Prompt Engineering
* Python
* JSON Data Handling
* Debugging Agent Workflows

---

## Future Improvements

* Retrieve only relevant products instead of the full catalog.
* Replace the local JSON database with a real product API.
* Improve the critique step using structured output.
* Add support for multiple recommendation criteria.
* Build a simple web interface for customer interaction.

---

## Author

**Imama Zubair**
AI & Data Science Intern @ Netixsol
