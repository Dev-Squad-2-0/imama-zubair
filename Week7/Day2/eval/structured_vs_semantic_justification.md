# Structured vs Semantic Retrieval: Why the Split

## The Split

**Structured retrieval (SQL, via `src/structured_retrieval.py`)** handles:
- Prices
- Property availability (status)
- Plot sizes
- Agent names and contact info
- Bedroom/bathroom counts
- Any filtered search (city, area, budget, purpose)

**Semantic retrieval (vector search, via `src/rag_pipeline.py`)** handles:
- Brochure text (marketing language, persuasive description)
- Neutral property descriptions (paragraph-level facts)
- FAQs (question and answer pairs)

## Why

Prices, availability, and sizes are single, exact values that exist in one place. There is nothing to "search" semantically about a number, either it's 33,141,381 PKR or it isn't. Running these through a vector store adds latency, cost, and a real risk: an LLM asked to summarize retrieved text about a price can paraphrase it wrong ("around 33 million" when the real number is 33,141,381, or worse, blend two different properties' prices together in one answer). SQL returns the exact row, every time, with zero room for drift.

Brochures, descriptions, and FAQs are different. The customer's question rarely matches the document's wording exactly ("is it safe" vs "24/7 Security" vs "gated community"). There's no single correct row to look up, the answer requires finding text that's *about* the right thing and then composing a response. That's what embeddings and vector search are for.

## What This Means for the Agent

When the voice agent gets a question, intent detection decides which path to use:
- "What's the price of the house in DHA Phase 6?" -> structured lookup, exact number back, no LLM guessing
- "Is DHA Phase 6 a good area for families?" -> semantic search over descriptions and FAQs, then LLM composes an answer grounded in what was retrieved

In practice, most real customer questions blend both: "Is the 3 bedroom in DHA Phase 6 still available, and does it have a park nearby?" splits into a structured availability check plus a semantic amenity/location lookup, and the two results get merged into one spoken answer.

## Domain-Agnostic Note

This split is not real-estate specific. Any business following this platform's config pattern will have the same shape: structured facts (price, appointment slot, inventory count, doctor's name) go in SQL, descriptive/unstructured content (service descriptions, policies, FAQs) go in the vector store. Swapping domains means swapping which fields live in each table, not changing this architecture.
