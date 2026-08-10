# Week 7 — Day 6 — Task 3 Performance Evaluation

**Run ID:** `20260809-163314`  
**Task 1 source:** `C:\Users\PC\Downloads\Compressed\day6messaround\tests\production_eval\output\evaluation_results.json`

## Executive Summary

| Metric | Result |
|---|---:|
| Mean turn latency | 5751.78 ms |
| P95 turn latency | 11610.42 ms |
| Conversation success rate | 95.45% |
| Booking success rate | 100.0% |
| Tool failures | 0 |
| RAG accuracy@3 | 100.0% |
| Memory accuracy | 100.0% |
| Hallucination rate | 0.0% |

## 1. Latency

Latency is calculated from the real per-turn timings already recorded by the Task 1 runner.

| Statistic | Turn latency | Conversation latency |
|---|---:|---:|
| Mean | 5751.78 ms | 8758.4 ms |
| P50 | 193.19 ms | 9112.68 ms |
| P95 | 11610.42 ms | 22316.79 ms |
| Maximum | 58370.16 ms | 69378.73 ms |

## 2. Conversation Success Rate

- Total conversations: **44**
- Successful: **42**
- Failed: **2**
- Success rate: **95.45%**

Failed scenarios:

- `investor_01`
- `inject_05`

## 3. Booking Success

- Booking tests identified: **4**
- Successful bookings: **4**
- Failed bookings: **0**
- Booking success rate: **100.0%**

## 4. Tool Failures

- Tool/integration failures detected: **0**
- CRM event rows checked: **0**

## 5. RAG Accuracy

RAG retrieval accuracy@3: **100.0%** (10/10 correct).

Ground-truth document retrieval hit-rate@K; no LLM judge.

| Case | Expected | Rank | Result |
|---|---|---:|---|
| `brochure_1` | brochure/1 | 1 | PASS |
| `brochure_10` | brochure/10 | 2 | PASS |
| `brochure_11` | brochure/11 | 1 | PASS |
| `brochure_12` | brochure/12 | 1 | PASS |
| `brochure_13` | brochure/13 | 1 | PASS |
| `brochure_14` | brochure/14 | 1 | PASS |
| `brochure_15` | brochure/15 | 1 | PASS |
| `brochure_16` | brochure/16 | 1 | PASS |
| `brochure_17` | brochure/17 | 1 | PASS |
| `brochure_18` | brochure/18 | 1 | PASS |

## 6. Memory Accuracy

- Memory assertions found: **2**
- Passed: **2**
- Failed: **0**
- Memory accuracy: **100.0%**

## 7. Hallucination Rate

Hallucination is measured without another LLM judge. Property titles, prices and bedroom claims in evaluation replies are checked against the SQLite property database.

- Claims checked: **10**
- Supported claims: **10**
- Hallucinated/mismatched claims: **0**
- Hallucination rate: **0.0%**

## Methodology Notes

- **Latency:** measured from recorded Task 1 turn timings.
- **Conversation success:** Task 1 scenario PASS / total scenarios.
- **Booking success:** booking-success assertions/final booked state from Task 1.
- **Tool failures:** explicit integration errors plus failed CRM-event statuses where available.
- **RAG accuracy:** retriever hit-rate@K against known indexed source documents; no LLM judge.
- **Memory accuracy:** PASS/FAIL of Task 1 checks explicitly testing sticky/carried/remembered context.
- **Hallucination rate:** deterministic structured property claims checked against SQLite ground truth.

This keeps Task 3 reproducible and avoids spending additional LLM quota merely to score the evaluation.