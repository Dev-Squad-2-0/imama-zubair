# Week 7 - Day 2: Knowledge Base, RAG & Property Intelligence

Part of the Week 7 capstone: A real-estate AI voice agent. Real estate is the demonstration domain, but the pipeline in this folder is not real-estate-specific. Swapping `config/domain_config.yaml`, `data/`, and `documents/` for a different business (clinic, restaurant, etc) is enough to reuse the same RAG, structured retrieval, and recommendation code with no code changes
This was done so that part of the workflow can be used in the future.

Synthetic data was generated for this.

## Folder Structure

```
week-7-day-2/
├── README.md
├── config/
│   └── domain_config.yaml          # defines structured vs semantic entities, weights, RAG settings
├── data/                           # structured knowledge base (Task 1)
│   ├── properties.csv
│   ├── locations.csv
│   ├── amenities.csv
│   ├── schools.csv
│   ├── hospitals.csv
│   ├── payment_plans.csv
│   ├── developers.csv
│   └── faqs.csv
├── documents/                      # semantic knowledge base (Task 1)
│   ├── brochures/                  # 60  brochures
│   └── descriptions/               # 60  property descriptions
├── db/
│   └── knowledge_base.db           # SQLite, built from data/ by src/build_database.py
├── src/
│   ├── generate_data.py            # Task 1: I just generated data from claude since our teamlead said the dataset didnt matter
│   ├── build_database.py           # loads CSVs into SQLite
│   ├── structured_retrieval.py     # Task 3: SQL-based exact fact lookups
│   ├── rag_pipeline.py             # Task 2: loader, chunking, embedding, vector store, retriever, answer gen
│   ├── evaluate_chunk_sizes.py     # Task 2: chunk size comparison
│   └── recommendation_engine.py    # Task 4: property recommendation engine
├── eval/
│   ├── hallucination_questions.py       # Task 5: 20-question evaluation harness
│   ├── hallucination_results.md         # Task 5: metrics + full results
│   ├── hallucination_raw_results.json
│   └── structured_vs_semantic_justification.md   # Task 3: written justification
└── outputs/
    └── chunk_size_comparison.md    # Task 2: chunk size evaluation results
```

## How to Run

```bash
pip install faker chromadb scikit-learn pandas --break-system-packages

python3 src/generate_data.py              # Task 1: generate synthetic knowledge base
python3 src/build_database.py             # load CSVs into SQLite
python3 src/structured_retrieval.py       # Task 3: demo SQL lookups
python3 src/rag_pipeline.py               # Task 2: build vector store, run a sample query
python3 src/evaluate_chunk_sizes.py       # Task 2: chunk size comparison
python3 src/recommendation_engine.py      # Task 4: demo recommendation
python3 eval/hallucination_questions.py   # Task 5: run the 20-question evaluation
```

## Task Summary

### Task 1: Knowledge Base
60 synthetic properties across 3 cities (Lahore, Karachi, Islamabad) and 15 areas, with linked locations, amenities, schools, hospitals, payment plans, developers, and 20 FAQs. Every property also gets a generated brochure (marketing tone) and description (neutral factual tone) as text documents, since the RAG pipeline needs unstructured content to chunk and retrieve, not just CSV rows.

### Task 2: RAG Pipeline
Full pipeline: document loader -> word-based chunker with overlap -> embedding -> ChromaDB vector store -> top-k retriever -> answer generation.

Embedding note: this sandbox has no network access to hosted embedding APIs (OpenAI/HuggingFace), so a local TF-IDF vectorizer is used as the embedding function, wrapped to match ChromaDB's embedding function interface. In production this is a one-line swap to an OpenAI or ChromaDB-hosted embedding function, nothing else in the pipeline changes.

#### Chunking Evaluation Results

| Chunk Size | Number of Chunks | Average Words | Retrieval Hit Rate |
|------------:|-----------------:|--------------:|-------------------:|
| 100 | 152 | 73.8 | 0.07 (1/15) |
| 200 | 140 | 76.7 | 0.40 (6/15) |
| 400 | 140 | 76.7 | 0.40 (6/15) |

#### Observations

- A chunk size of **100 words** produced the highest number of chunks but significantly lower retrieval accuracy. Splitting documents into smaller fragments reduced the amount of context available during retrieval, making it more difficult to return the correct document.

- Chunk sizes of **200** and **400 words** produced identical results because most documents in the knowledge base were already shorter than 200 words. Consequently, each document remained a single chunk regardless of the configured chunk size.

- Based on these results, a **200-word chunk size** was selected as the default configuration. It achieved the highest retrieval accuracy while avoiding the creation of unnecessary chunks, providing the best balance between retrieval performance and indexing efficiency.


### Task 3: Structured Retrieval
Prices, availability, plot sizes, and agent names are answered by direct SQL against `db/knowledge_base.db`, never by the LLM. Brochures, descriptions, and FAQs go through vector retrieval. Full reasoning in `eval/structured_vs_semantic_justification.md`: exact facts have zero tolerance for paraphrase drift, descriptive content needs semantic matching because customer phrasing rarely matches document wording exactly.

### Task 4: Recommendation Engine
`src/recommendation_engine.py` filters candidates with structured SQL (budget, city, area, bedrooms, purpose) then ranks them with a weighted score (budget fit, location match, bedroom match, amenity match, purpose match). Weights live in `config/domain_config.yaml`, not hardcoded in the scoring function, so they can be tuned per domain.

### Task 5: Hallucination Evaluation
20 questions across structured, semantic, and out-of-knowledge-base categories, scored for Grounding Rate, Retrieval Accuracy, and Hallucination Rate. Full results in `eval/hallucination_results.md`.



## Domain-Agnostic Design Notes

- `src/generate_data.py` is the only file in this folder that knows anything about real estate. Everything downstream (`build_database.py`, `structured_retrieval.py`, `rag_pipeline.py`, `recommendation_engine.py`) reads table/field names either directly or through `config/domain_config.yaml`.
- To adapt this for another business: replace the data generator's output with that business's data (keeping the same CSV shapes), replace `documents/` with that business's descriptive text, and update `domain_config.yaml`'s field list and recommendation weights. No pipeline code changes needed.
- The structured vs semantic split is itself domain-agnostic: any business will have exact facts (price, appointment slot, inventory) that belong in SQL, and descriptive content (service details, policies, FAQs) that belongs in the vector store.

## Next Steps

Day 3 will build on this knowledge base and RAG pipeline inside the LangGraph orchestration layer, wiring structured retrieval, semantic retrieval, and the recommendation engine into the agent's tool-calling flow.
