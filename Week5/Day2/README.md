# LangChain Agent Development: Tools, Chains & Memory

## Overview

Rebuilding a raw Python ReAct agent using LangChain to understand the abstractions, automation, and complexity introduced by the framework. The notebook transitions from raw API calls and custom loops to LangChain Expression Language (LCEL), tool decorators, `AgentExecutor`, conversation memory integration, and structured output parsing.

---

## Objectives

* Map custom Python agent components to their LangChain framework equivalents.
* Construct functional prompt-to-response chains using LCEL pipe syntax.
* Implement custom tools with `@tool` decorators and manage prompt descriptions via function docstrings.
* Build a ReAct agent using `create_tool_calling_agent` and execute multi-step tool calls with `AgentExecutor`.
* Analyze and annotate agent execution traces to understand internal reason-act-observe loops.
* Integrate persistent session memory using `RunnableWithMessageHistory`.
* Enforce structured responses using Pydantic schemas via `.with_structured_output()`.
* Implement graceful error handling for faulty and throwing tools using `handle_tool_error`.

---

## Input

* **Custom Tools Data:** Local `products.json` file acting as a product database with laptop specifications (price, RAM, battery life).
* **API Endpoints:** External LLM endpoint accessed via `ChatOpenAI` wrapper.
* **In-Memory Store:** Synthetic city weather dictionary and a runtime chat history dictionary for session persistence.

---

## Tasks / Features

* **Task 1: LangChain Setup & Core Concepts:** Set up `langchain`, `langchain-openai`, and `langchain-community`. Built an LCEL chain using the pipe operator (`prompt | llm | output_parser`) to test chain execution.
* **Task 2: Define & Register Tools:** Wrapped arithmetic operations, city weather lookups, and a `products.json` file reader using the `@tool` decorator.
* **Task 3: Agent Assembly & Trace Analysis:** Built an agent with `create_tool_calling_agent` and `AgentExecutor(verbose=True)`. Ran a multi-step query combining weather lookup and calculations, annotating the reasoning trace.
* **Task 4: Conversation Memory:** Attached `RunnableWithMessageHistory` and added a `MessagesPlaceholder(variable_name="chat_history")` to process context across a 3-turn user interaction.
* **Task 5: Structured Output & Error Recovery:** Defined a Pydantic `ProductRecommendation` model to enforce JSON output. Created a `flaky_stock_checker` tool raising exceptions and configured `AgentExecutor(handle_tool_error=True)` for graceful recovery.

---

## Technologies Used

* Python
* LangChain (`langchain`, `langchain-openai`, `langchain-community`, `langchain-core`)
* Pydantic
* Jupyter Notebook
* JSON

---

## Project Structure

```text
Week5_Day2/
│
├── products.json
├── week5_day2_langchain.ipynb
├── Week 5 Day 2 Write up.pdf
└── README.md

```

---

## What I Learned

* **LCEL Pipe Operator Syntax:** The pipe (`|`) operator overloads Python's bitwise OR operator to connect `Runnable` components, automatically invoking and passing data from one component to the next as a `RunnableSequence`.
* **Docstrings as Prompts:** Tool function docstrings are directly extracted by LangChain to construct JSON schemas passed to the LLM; accurate docstrings are critical for correct tool selection.
* **Framework Abstractions vs. Control:** `AgentExecutor` automates while loops, message history updates, and execution scratchpads that previously required manual handling in raw Python.
* **Error Handling Dynamics:** Setting `handle_tool_error=True` catches tool runtime exceptions and feeds the error back to the model as an observation, allowing the agent to attempt recovery or inform the user instead of crashing.
* **Framework Leakiness:** Abstraction layer issues can obscure underlying messages and raw tool call IDs, making stack traces deeper when troubleshooting prompt or execution errors.

---

## Skills Demonstrated

* Framework-based LLM Development
* LangChain Expression Language (LCEL)
* Tool Registration & Schema Generation
* ReAct Agent Architecture
* Memory & Chat History Management
* Structured Data Parsing (Pydantic)
* Exception Handling in Agentic Loops


---

## Author

Imama Zubair

AI & Data Science Intern @ Netixsol
