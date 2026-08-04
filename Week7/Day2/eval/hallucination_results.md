# Hallucination Evaluation

20 test questions across structured, semantic, and out-of-knowledge-base categories.

## Metrics Summary

- Grounding Rate (structured + semantic): **0.93**
- Retrieval Accuracy (semantic only): **1.0**
- Hallucination Rate : **0.0** Percentage of out-of-knowledge-base questions where the assistant produced fabricated information. Lower is better.

## Full Results

| # | Category | Question | Grounded | Retrieval Correct | Hallucinated | Note |
|---|---|---|---|---|---|---|
| 1 | structured | What is the price of property 1? | True | None | False |  |
| 2 | structured | Is property 1 available? | True | None | False |  |
| 3 | structured | What is the plot size of property 1? | True | None | False |  |
| 4 | structured | Who is the agent for property 1? | True | None | False |  |
| 5 | structured | What is the price of property 30? | True | None | False |  |
| 6 | structured | How many bedrooms does property 30 have? | True | None | False |  |
| 7 | structured | What type of property is 30? | True | None | False |  |
| 8 | semantic | What amenities are commonly offered in DHA Phase 6 propertie | False | True | True |  |
| 9 | semantic | Do you offer flexible payment plans? | True | True | False |  |
| 10 | semantic | What documents are needed to buy a property? | True | True | False |  |
| 11 | semantic | Can overseas Pakistanis buy property remotely? | True | True | False |  |
| 12 | semantic | Is the price negotiable? | True | True | False |  |
| 13 | semantic | What is the difference between a token and down payment? | True | True | False |  |
| 14 | semantic | Do you provide legal assistance during purchase? | True | True | False |  |
| 15 | out_of_kb | What is the current State Bank of Pakistan policy interest r | None | None | False |  |
| 16 | out_of_kb | Can you guarantee my property value will double in 2 years? | None | None | False |  |
| 17 | out_of_kb | What is the weather forecast for Lahore this weekend? | None | None | False |  |
| 18 | out_of_kb | Do you have any properties on the moon? | None | None | False |  |
| 19 | out_of_kb | What is your company's total annual revenue? | None | None | False |  |
| 20 | out_of_kb | Can I pay in Bitcoin for a property? | None | None | False |  |

## Structured Question Detail

Structured questions are answered by direct SQL lookup against the properties table, so they are grounded by construction (there is no room for the LLM to paraphrase a price or status field, it is returned as-is from the database).

