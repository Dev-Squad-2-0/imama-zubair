# Week 7 — Day 6 — Task 3: Performance Evaluation

This package measures the seven metrics required by Task 3:

1. Latency
2. Conversation success rate
3. Booking success
4. Tool failures
5. RAG accuracy
6. Memory accuracy
7. Hallucination rate

It is designed to reuse the **real Task 1 evaluation results** instead of
rerunning all 40+ conversations and consuming more LLM quota.

## Install

Place this folder at:

```text
day6messaround/
└── tests/
    └── task3_performance/
```

## Prerequisite

Run Task 1 first so this file exists:

```text
tests\task1_evaluation\output\evaluation_results.json
```

If your Task 1 folder has a different name, pass the JSON path explicitly.

## Run

Normal:

```powershell
python tests\task3_performance\run_performance_evaluation.py
```

Explicit Task 1 result path:

```powershell
python tests\task3_performance\run_performance_evaluation.py `
  --task1-results "tests\task 1 evaluation\output\evaluation_results.json"
```

You can change the number of RAG corpus probes:

```powershell
python tests\task3_performance\run_performance_evaluation.py --rag-cases 10
```

## How each metric is measured

### Latency

Uses every `latency_ms` value already recorded in Task 1.

Reports:
- mean turn latency;
- p50;
- p95;
- maximum;
- mean/p50/p95/max whole-conversation latency.

### Conversation Success Rate

```text
successful Task 1 scenarios / total Task 1 scenarios
```

A scenario is successful only when all of its Task 1 assertions pass.

### Booking Success

Finds Task 1 assertions such as:

```text
booking succeeds
booking success
status booked
appointment booked
```

and measures passed booking assertions / booking tests.

If a suite exposes final appointment state instead, the evaluator can use
`appointment_status.status == "booked"`.

### Tool Failures

Looks for:
- explicit tool/integration exceptions in scenario results;
- failed recorded tool calls when a runner exposes them;
- failed/error statuses in the Task 1 isolated `crm_events` table.

No real Calendar/email writes are required by Task 3.

### RAG Accuracy

This does **not use an LLM judge**.

It loads the same documents used to build Chroma, creates up to 10
ground-truth retrieval queries, runs the real retriever, and measures whether
the expected source/property appears within the top 3 results.

Metric:

```text
RAG Accuracy@3 = correct retrievals / retrieval cases
```

This only consumes local embedding/retrieval resources.

### Memory Accuracy

Reuses Task 1 assertions whose labels explicitly test:
- memory;
- sticky state;
- carried context;
- remembered/retained context.

Metric:

```text
Memory Accuracy = passed memory assertions / total memory assertions
```

This includes cases such as the buyer saying:

```text
Us se sasti koi option hai?
```

where the agent must remember the prior recommendation/budget context.

### Hallucination Rate

This also avoids an LLM judge.

The evaluator reads the `properties` SQLite table and audits verifiable
structured property claims made by the agent:

- property title;
- price;
- bedroom count.

A price is considered supported when it matches the database within a small
2% formatting/rounding tolerance.

Metric:

```text
Hallucination Rate =
unsupported or mismatched structured claims / total structured claims checked
```

This is intentionally described as a **structured-property hallucination
rate**, because claims that cannot be deterministically verified should not be
silently scored by guesswork.

## Output

```text
tests\task3_performance\output\
├── performance_evaluation.json
└── performance_evaluation.md
```

The terminal also prints all seven final metrics when evaluation completes.

Example:

```text
========================================================================
TASK 3 PERFORMANCE EVALUATION COMPLETE
========================================================================
Mean turn latency       : 1840.55 ms
P95 turn latency        : 5210.34 ms
Conversation success    : 40/44 (90.91%)
Booking success         : 4/5 (80.0%)
Tool failures           : 1
RAG accuracy@3          : 9/10 (90.0%)
Memory accuracy         : 5/6 (83.33%)
Hallucination rate      : 1/31 (3.23%)
------------------------------------------------------------------------
REPORT FILES:
  JSON: ...\performance_evaluation.json
  MD  : ...\performance_evaluation.md
========================================================================
```

## Why Task 3 reuses Task 1

Your 40+ Task 1 conversations are already the production-style workload.
Running another independent 40+ LLM conversations only to calculate metrics
would:
- consume additional model quota;
- produce a different sample;
- make Task 1 and Task 3 results inconsistent.

Task 3 therefore treats Task 1 as the workload and performs deterministic
analysis plus local RAG/database audits on the same run.
