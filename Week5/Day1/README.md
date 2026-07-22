# Week 5 Day 1 Agent Foundations

A lightweight, framework-free AI agent implemented in raw Python using an OpenAI-compatible API. This project demonstrates the core mechanics of agentic AI—**Reasoning, Acting, Observing, and Repeating**—without relying on high-level orchestration libraries like LangChain or LangGraph.

---

##  Overview

Understanding AI agents requires breaking down what happens under the hood: an LLM running inside a loop that maintains conversation state, selects tools, parses execution results, and iterates until a task is completed.

This project covers:

1. **Conceptual Foundations**: Agent vs. Chatbot vs. Workflow.
2. **Tool Definition & Schemas**: Defining tools with structured JSON schemas.
3. **The ReAct Loop**: Implementing a stateful loop with iteration guards.
4. **Memory & Logging**: Handling message history and displaying detailed execution logs.
5. **Failure Analysis**: Identifying edge cases, missing capabilities, and error handling.

---

##  Concepts & Architecture

### Agent vs. Chatbot vs. Workflow

* **Chatbot**: Responds strictly based on pre-trained knowledge or direct user context in a single interaction cycle.
* **Workflow**: A deterministic sequence of hardcoded steps or API calls with fixed inputs/outputs.
* **Agent**: An autonomous system capable of reasoning, selecting dynamic tools, evaluating tool outputs, and dynamically adjusting its path to achieve a goal.

### The ReAct (Reason → Act → Observe) Pattern

```
                 +-------------------+
                 |    User Request   |
                 +---------+---------+
                           |
                           v
              +------------+------------+
              |    Model Reasons       |
              +------------+------------+
                           |
            +--------------+--------------+
            |                             |
            v                             v
     [Final Answer]               [Tool Request]
            |                             |
            v                             v
           End                    +-------+-------+
                                  | Execute Tool  |
                                  +-------+-------+
                                          |
                                          v
                                 +--------+--------+
                                 | Tool Observation|
                                 +--------+--------+
                                          |
                                          +----> (Loop Back to Model)

```

### Pseudo-code

```python
conversation_history = [user_prompt]
iterations = 0

while iterations < MAX_ITERATIONS:
    response = llm.generate(conversation_history)
    
    if response.has_final_answer():
        return response.text
        
    if response.has_tool_call():
        tool_output = execute_tool(response.tool_call)
        conversation_history.append(tool_output)
        
    iterations += 1

```

---

##  Tool Schemas Used

The agent uses structured JSON schemas to communicate available tools to the LLM.

### 1. Calculator Tool

Performs basic arithmetic operations (`add`, `subtract`, `multiply`, `divide`).

```json
{
  "name": "calculator",
  "description": "Performs basic arithmetic operations.",
  "parameters": {
    "type": "object",
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["add", "subtract", "multiply", "divide"]
      },
      "a": { "type": "number" },
      "b": { "type": "number" }
    },
    "required": ["operation", "a", "b"]
  }
}

```

### 2. Weather Lookup Tool (Stub)

Returns predefined weather data for specific cities without calling an external API.

```json
{
  "name": "get_weather",
  "description": "Returns current weather information for a specified city.",
  "parameters": {
    "type": "object",
    "properties": {
      "city": { "type": "string", "description": "The name of the city." }
    },
    "required": ["city"]
  }
}

```

> **Why Tool Descriptions Matter:** Clear descriptions guide the model's decision-making process, ensuring it selects the appropriate tool and provides correctly typed arguments.

---

##  Memory & State Handling

* **Conversation Memory (Message History):** Tracks the global interaction state (`user`, `assistant`, and `tool` messages) across multiple loop turns.
* **Working Memory (Scratchpad):** The transient state within a single task run, tracking mid-task intermediate reasoning steps, raw tool outputs, and temporary variables.

---

##  Failure Modes & Edge Cases Observed

During testing, the raw agent was exposed to incomplete, missing, or erroneous scenarios:

| Scenario / Edge Case | Observed Behavior | Mitigation Strategy |
| --- | --- | --- |
| **1. Ambiguous Request** | When asked *"Is it hot today?"*, the model requested a city instead of guessing. | Prompt engineering forcing explicit parameter clarification before execution. |
| **2. Tool Execution Error** | Requesting a city missing from the dataset returned an error output rather than fabricated data. | Robust error handling inside the tool returning a clear, actionable message to the model. |
| **3. Missing Capability** | When asked to send an email, the agent drafted the email content because no email execution tool was available. | System prompts informing the model of system boundaries and missing capabilities. |
| **4. Infinite Loops** | Complex or failing tasks could repeatedly request tools without reaching a resolution. | Hard iteration cap (`MAX_ITERATIONS = 5`) to safety-break the loop. |
| **5. Hallucinated Tools** | The model attempts to call non-existent functions. | Strict validation matching requested tool names against a registered function mapping. |

---

##  Conclusion: Why Frameworks Exist

Building an agent manually demonstrates how memory management, tool parsing, and iteration mechanics operate under the hood. While a custom Python implementation offers total control, high-level frameworks like **LangChain**, **LangGraph**, and **CrewAI** simplify production deployments by providing:

* Standardized state/memory abstractions.
* Pre-built integrations and robust error recovery mechanisms.
* Graph-based workflow orchestration and multi-agent coordination.
* Built-in observability, tracing, and debugging tools.
