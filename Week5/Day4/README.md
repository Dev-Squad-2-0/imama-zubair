# Week 5 Dy 4 CrewAI — Multi-Agent Collaboration, Roles & Task Delegation
# CrewAI Multi-Agent Workflow

This project demonstrates how to build and compare different CrewAI workflows using multiple AI agents to recommend the best laptop for a customer.

## Objective

The goal was to compare:

- Sequential Crew
- Hierarchical Crew
- Single-Agent approach (Day 3)

The customer request used throughout the project was:

> "I need a laptop mainly for work meetings and travel, battery life matters most, budget around $900."

---

## Project Structure

### Agents

**Researcher**
- Retrieves laptop information from the product catalog.
- Uses the Product Lookup tool.
- Returns only factual product specifications.

**Analyst**
- Compares the products numerically.
- Calculates value-for-money scores.
- Produces structured comparisons.

**Communicator**
- Converts the analysis into a customer-friendly recommendation email.
- Makes the final response easy to understand.

**Manager (Hierarchical only)**
- Delegates work to the specialist agents.
- Reviews outputs before producing the final result.

---

## Tools

### Product Lookup Tool

Returns laptop information from the local product catalog.

Supported fields:

- Name
- Price
- Battery life
- RAM

### Calculator Tool

Performs simple arithmetic:

- Add
- Subtract
- Multiply
- Divide

---

## Workflow Comparison

### Sequential Crew

```
Researcher
      ↓
Analyst
      ↓
Communicator
```

Each agent receives the previous agent's output before continuing.

---

### Hierarchical Crew

```
             Manager
          /     |     \
 Researcher Analyst Communicator
```

The manager decides which agent performs each task and combines their outputs.

---

## Results

| Approach | Total Tokens | Approx. Cost | Notes |
|----------|-------------:|-------------:|------|
| Single-Agent | ~9,500 | ~$0.019 | Lowest cost and fastest execution. |
| Sequential | 22,299 | ~$0.0446 | Good balance between quality and cost. |
| Hierarchical | 65,056 | ~$0.1301 | Highest cost because of delegation and additional reasoning. |

---

### Success Criteria and Manual Evaluation
**Success Criteria**
1. **Factual grounding** : does the recommendation email correctly reflect the actual catalog data (right price, right battery life, no invented specs)?
2. **Completeness** :does it address the customer's stated priorities (battery life, budget) and mention at least one runner-up tradeoff?
3. **Tone** : does it read as a natural, friendly customer email rather than a spec dump?

| Run                  | Factual Grounding | Completeness | Customer-Friendly Tone | Overall   |
| -------------------- | ----------------- | ------------ | ---------------------- | --------- |
| Single-Agent (Day 3) | **5/5**           | **4/5**      | **4/5**                | **13/15** |
| Sequential Crew      | **5/5**           | **5/5**      | **5/5**                | **15/15** |
| Hierarchical Crew    | **2/5**           | **3/5**      | **5/5**                | **10/15** |


---

## Observations

- The Sequential Crew produced the best overall balance between quality and cost.
- The Hierarchical Crew consumed significantly more tokens because of manager reasoning and delegation.
- During testing, the manager occasionally hallucinated product names instead of delegating correctly, reducing output quality.
- The Single-Agent solution remained the most efficient option for this relatively simple task.

---

## Technologies Used

- Python
- CrewAI
- Google Gemini
- Custom Tools
- JSON Product Catalog

---

## Skills Demonstrated

- CrewAI multi-agent workflows
- Sequential & hierarchical execution
- Custom tool development
- Prompt engineering
- LLM integration & API configuration
- Token usage and cost analysis
- Agent performance evaluation
- Debugging and troubleshooting

---
## Files

```
products.json
week5_day4_crewai.ipynb
README.md
requirements.txt
```

---

## Conclusion

For this laptop recommendation task, a Sequential Crew provided the best trade-off between modularity, quality, and token usage. Although Hierarchical crews are more flexible for complex workflows, the additional coordination introduced higher costs without improving the final recommendation for this relatively straightforward problem.