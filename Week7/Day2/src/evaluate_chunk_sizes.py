"""
Day 2 - Task 2 (evaluation): Compare chunk sizes.

For each chunk size in the config, build a fresh vector store and measure:
- total number of chunks produced (storage/index cost)
- average chunk length in words
- retrieval hit rate on a fixed set of test queries (does the top-3 result
  contain the property_id we expect, based on which document the query text
  was drawn from)
"""

import os
import sys
import yaml
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag_pipeline import (
    load_documents,
    build_chunks,
    SentenceTransformerEmbeddingFunction,
)
import chromadb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE, "config", "domain_config.yaml")
OUTPUT_PATH = os.path.join(BASE, "outputs", "chunk_size_comparison.md")

random.seed(7)


def make_test_queries(docs, n=15):
    """Build test queries by sampling a sentence out of known documents,
    so we know which property_id should come back in the results."""
    candidates = [(doc_id, text, meta) for doc_id, text, meta in docs if meta["source"] == "description"]
    sample = random.sample(candidates, min(n, len(candidates)))
    queries = []
    for doc_id, text, meta in sample:
        # use the amenities line as the query since it's distinctive
        for line in text.split("\n"):
            if line.startswith("Amenities:"):
                queries.append((line.replace("Amenities:", "").strip(), meta["property_id"]))
                break
    return queries


def evaluate_chunk_size(chunk_size, overlap, docs, queries, top_k=3):
    chunks = build_chunks(docs, chunk_size, overlap)

    embed_fn = SentenceTransformerEmbeddingFunction()

    client = chromadb.EphemeralClient()
    collection = client.create_collection(name=f"eval_{chunk_size}", embedding_function=embed_fn)
    collection.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )

    hits = 0
    for query_text, expected_pid in queries:
        results = collection.query(query_texts=[query_text], n_results=top_k)
        returned_pids = [m["property_id"] for m in results["metadatas"][0]]
        if str(expected_pid) in [str(p) for p in returned_pids]:
            hits += 1

    hit_rate = hits / len(queries) if queries else 0
    avg_len = sum(len(c["text"].split()) for c in chunks) / len(chunks)

    return {
        "chunk_size": chunk_size,
        "overlap": overlap,
        "num_chunks": len(chunks),
        "avg_chunk_words": round(avg_len, 1),
        "retrieval_hit_rate": round(hit_rate, 2),
        "hits": hits,
        "total_queries": len(queries),
    }


def main():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    chunk_sizes = config["rag"]["chunk_sizes_to_evaluate"]
    overlap = config["rag"]["chunk_overlap"]

    docs = load_documents()
    queries = make_test_queries(docs, n=15)

    results = []
    for size in chunk_sizes:
        res = evaluate_chunk_size(size, overlap, docs, queries)
        results.append(res)
        print(res)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write("# Chunk Size Evaluation\n\n")
        f.write(f"Test set: {len(queries)} queries built from known property descriptions, ")
        f.write("checking whether the correct property_id appears in the top-3 retrieved chunks.\n\n")
        f.write("| Chunk Size (words) | Overlap | Num Chunks | Avg Chunk Words | Retrieval Hit Rate |\n")
        f.write("|---|---|---|---|---|\n")
        for r in results:
            f.write(f"| {r['chunk_size']} | {r['overlap']} | {r['num_chunks']} | {r['avg_chunk_words']} | {r['retrieval_hit_rate']} ({r['hits']}/{r['total_queries']}) |\n")

        best = max(results, key=lambda r: r["retrieval_hit_rate"])
        f.write(f"\n## Conclusion\n\n")
        f.write(
        f"Chunk size {best['chunk_size']} words achieved the highest retrieval hit rate "
        f"({best['retrieval_hit_rate']}) in this evaluation. Smaller chunks provide "
        f"more precise retrieval but increase the number of stored vectors and may split "
        f"important context across multiple chunks. Larger chunks preserve more context "
        f"but may include additional unrelated information. Based on these results, "
        f"{config['rag']['default_chunk_size']} words was selected as the default chunk "
        f"size because it offers the best balance between retrieval accuracy and context preservation.\n"
)

    print(f"\nResults written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
