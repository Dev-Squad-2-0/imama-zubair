# Week 6 Day 3: AFL Chat Agent (Retrieval, Guardrails & Memory)

## Overview

This was the third day of Week 6, and the focus shifted from building prediction models to building the conversational side of the AFL assistant. The goal was to create a chat agent that only discusses AFL, retrieves real information from the dataset instead of making up statistics, remembers previous messages in a conversation, and safely refuses off-topic requests. This lays the foundation for adding the prediction tools on Day 4.

---

## Objectives

* Define the assistant's scope with clear guardrails
* Design polite refusal responses for off-topic requests
* Build structured retrieval tools using the AFL datasets
* Connect the retrieval tools to a LangChain/LangGraph agent
* Add conversation memory for multi-turn chats
* Evaluate the guardrails using a mix of AFL and off-topic prompts
* Save the chat agent as a reusable Python module for future tasks

---

## Dataset

The feature tables created on Day 2 were reused as the knowledge source for retrieval.

* **player_match_features_v1_2026-07-27.csv** — player-level rolling statistics, including disposals, goals, fantasy points, and recent form features.
* **team_match_features_v1_2026-07-27.csv** — team-level match history and rolling features such as recent form, ladder position, and head-to-head records.

No external APIs or online data sources were used.

---

## Tasks Completed

### **Task 1: Scope Definition & Guardrails**

Designed a system prompt that clearly defines the assistant's role as an AFL-only chatbot. The prompt limits the assistant to AFL teams, players, matches, statistics, history, and rules, while refusing unrelated requests such as other sports, coding, recipes, weather, or general trivia. Three example refusal responses were also written to politely redirect conversations back to AFL.

An adversarial test set containing jailbreak attempts, topic drift, and off-topic prompts was prepared to evaluate the guardrails.

### **Task 2: Structured Retrieval**

Implemented structured retrieval tools using pandas instead of relying on the language model's memory. These tools query the AFL datasets directly to return factual information such as:

* Player recent statistics
* Team head-to-head records

Structured retrieval was chosen because sports statistics must come directly from the dataset rather than from semantic search or model memory, reducing the risk of hallucinated numbers.

### **Task 3: LangChain Agent Integration**

Registered the retrieval functions as LangChain tools and connected them to a LangGraph ReAct agent. The agent calls the correct tool whenever a factual AFL question requires real data instead of answering from memory.

A grounding check was also performed by comparing the tool output with the final response to confirm that numerical values shown to the user matched the retrieved data.

### **Task 4: Conversation Memory**

Added conversation memory using LangGraph's `MemorySaver`, allowing the assistant to remember previous messages during a conversation. Multi-turn conversations were tested to confirm that users could ask follow-up questions without repeating the full context.

### **Task 5: Guardrail Evaluation**

Built a test set of 15 prompts covering:

* Legitimate AFL questions
* Off-topic requests
* Prompt injection attempts
* Mixed AFL and non-AFL questions
* Ambiguous edge cases

The agent stayed within its intended scope for every test and consistently refused unrelated requests while grounding factual responses in the retrieval tools.

---

## Technologies Used

* Python
* Pandas
* LangChain
* LangGraph
* Jupyter Notebook

---

## Project Structure

```text
Week6_Day3/
│
├── afl_chat_agent.py
├── week6_day3_afl_chat_agent.ipynb
├── player_match_features_v1_2026-07-27.csv
├── team_match_features_v1_2026-07-27.csv
├── Guardrail Evaluation Report.pdf
├── guardrail_evluation_results.csv
├── adversarial_prompt_results.csv
└── README.md
```

---

## Key Insights

* Structured retrieval is much more reliable than relying on an LLM's memory for numerical sports statistics.
* Clear system prompts and guardrails are effective at preventing off-topic conversations and prompt injection attempts.
* Conversation memory makes the chatbot feel more natural by supporting follow-up questions without repeating context.
* Separating retrieval from prediction keeps the chat agent modular and makes it easier to add prediction tools later.

---

## Skills Demonstrated

* Prompt Engineering
* LangChain Tool Calling
* LangGraph Agent Development
* Structured Data Retrieval
* Conversation Memory
* AI Guardrails
* Grounding and Hallucination Prevention
* Python Programming
* Documentation

---

## Future Improvements

* Add retrieval tools for recent team results, ladder standings, and season summaries.
* Expand the range of structured queries the assistant can answer.
* Add semantic retrieval over AFL articles or match reports if unstructured text becomes available.
* Integrate the Day 2 prediction models so the assistant can answer predictive questions about match winners and top players.
* Deploy the chat agent through a web interface or API for interactive use.

---

## Author

*Imama Zubair*

AI & Data Science Intern @ Netixsol
