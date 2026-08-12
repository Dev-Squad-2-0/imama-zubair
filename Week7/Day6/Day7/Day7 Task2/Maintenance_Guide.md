# Maintenance Guide

Regular maintenance ensures the AI Voice Agent remains accurate, responsive, and secure.

## 1. Vector Database Refresh Schedule
The RAG (Retrieval-Augmented Generation) system relies on ChromaDB.
- **Frequency**: Trigger an update script whenever new property listings are added to the main CRM.
- **Process**: Drop outdated embeddings and re-index the latest property descriptions.
- **Validation**: After indexing, run the RAG accuracy evaluation to ensure no hallucinations occur on the new dataset.

## 2. Model and Prompt Updates
- **LLM Selection**: Periodically evaluate newer, faster, or cheaper LLM endpoints. When updating the underlying LLM, run the full 44-scenario production evaluation suite to prevent regressions.
- **Prompt Refinement**: Any changes to the base system prompt or persona should be tested against the security prompt-injection suite to ensure jailbreak resistance.

## 3. Weekly Retraining & Performance Review
- **Review Monitoring Logs**: Run the monitoring report (`run_monitoring_report.py`) weekly.
- **Analyze Failures**: Look for spikes in `calendar_failed`, `rag_misses`, or high latency.
- **Transcripts**: Review interactions that resulted in an "Angry Customer" state to identify areas for prompt improvement or new tool integration.

## 4. Database Maintenance
- **SQLite Backups**: The SQLite databases (`knowledge_base.db` and CRM/metrics) should be backed up nightly.
- **Log Pruning**: If metrics are stored indefinitely, schedule a job to archive or prune `service_metrics` data older than 90 days to maintain fast query performance.

## 5. Security Review Cadence
- **Monthly**: Review security logs for new types of prompt injections.
- **Quarterly**: Audit Google API credentials and rotate keys if necessary. Ensure the principle of least privilege is maintained for the Gmail and Calendar APIs.
