"""
RAG pipeline.

Production startup behavior:
- ChromaDB, SentenceTransformers, and OpenAI are imported lazily.
- The embedding model, Chroma client, and collection are cached for the
  lifetime of the Python process.
- warmup() can pre-load the model/collection and execute one tiny retrieval
  without blocking the caller-facing greeting.
- build_vector_store() remains an explicit maintenance operation and is never
  called automatically by the live conversation path.
"""

import csv
import glob
import os
import threading
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_DIR = os.path.join(BASE, "documents")
DATA_DIR = os.path.join(BASE, "data")
CHROMA_DIR = os.path.join(BASE, "db", "chroma")

EMBEDDING_MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
DEFAULT_COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", "knowledge_base")
DEFAULT_WARMUP_QUERY = os.getenv("RAG_WARMUP_QUERY", "real estate property information")

base_url = os.environ.get("BASE_URL")
api_key = os.environ.get("API_KEY")

_embedding_model = None
_chroma_client = None
_collection = None
_collection_name = None
_llm_client = None

# RLock lets warmup() call the normal getters without deadlocking.
_init_lock = threading.RLock()
_warmup_lock = threading.Lock()
_warmup_done = threading.Event()
_warmup_error: Optional[str] = None
_warmup_ms: Optional[int] = None


def _get_embedding_model():
    """Load SentenceTransformer only when RAG actually needs embeddings."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    with _init_lock:
        if _embedding_model is None:
            # Heavy import intentionally lives here, not at module import time.
            from sentence_transformers import SentenceTransformer  # type: ignore

            started = time.perf_counter()
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            elapsed = int((time.perf_counter() - started) * 1000)
            print(
                f"[RAG] embedding model loaded: {EMBEDDING_MODEL_NAME} "
                f"({elapsed}ms)"
            )
    return _embedding_model


def _get_chroma_client():
    """Create and cache the persistent Chroma client lazily."""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    with _init_lock:
        if _chroma_client is None:
            # Heavy import intentionally deferred.
            import chromadb

            _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client


def _get_llm_client():
    """Create the optional RAG answer client only when answer generation uses it."""
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    with _init_lock:
        if _llm_client is None:
            if not base_url or not api_key:
                raise RuntimeError("BASE_URL / API_KEY are not set in the environment")

            # Avoid importing OpenAI just to start a live phone call.
            from openai import OpenAI

            _llm_client = OpenAI(base_url=base_url, api_key=api_key)
    return _llm_client


# ---------- 1. Document Loader ----------

def load_documents():
    """Load brochures, descriptions, and FAQs as (id, text, metadata)."""
    docs = []

    for path in glob.glob(os.path.join(DOC_DIR, "brochures", "*.txt")):
        pid = os.path.basename(path).replace("property_", "").replace(".txt", "")
        with open(path, encoding="utf-8") as f:
            docs.append(
                (
                    f"brochure_{pid}",
                    f.read(),
                    {"source": "brochure", "property_id": pid},
                )
            )

    for path in glob.glob(os.path.join(DOC_DIR, "descriptions", "*.txt")):
        pid = os.path.basename(path).replace("property_", "").replace(".txt", "")
        with open(path, encoding="utf-8") as f:
            docs.append(
                (
                    f"description_{pid}",
                    f.read(),
                    {"source": "description", "property_id": pid},
                )
            )

    faq_path = os.path.join(DATA_DIR, "faqs.csv")
    with open(faq_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            text = f"Q: {row['question']}\nA: {row['answer']}"
            docs.append(
                (f"faq_{i}", text, {"source": "faq", "property_id": ""})
            )

    return docs


# ---------- 2. Chunking ----------

def chunk_text(text, chunk_size=200, overlap=40):
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


def build_chunks(docs, chunk_size=200, overlap=40):
    all_chunks = []
    for doc_id, text, meta in docs:
        pieces = chunk_text(text, chunk_size, overlap)
        for i, piece in enumerate(pieces):
            all_chunks.append(
                {
                    "id": f"{doc_id}_chunk{i}",
                    "text": piece,
                    "metadata": meta,
                }
            )
    return all_chunks


# ---------- 3. Embedding ----------

class SentenceTransformerEmbeddingFunction:
    """Chroma-compatible wrapper around the cached SentenceTransformer."""

    def __call__(self, input):
        embeddings = _get_embedding_model().encode(
            input,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_documents(self, input):
        return self.__call__(input)

    def embed_query(self, input):
        return self.__call__(input)

    def name(self):
        return EMBEDDING_MODEL_NAME


# ---------- 4. Vector Store ----------

def build_vector_store(
    chunk_size=200,
    overlap=40,
    collection_name=DEFAULT_COLLECTION_NAME,
):
    """Explicit maintenance command: rebuild persisted vectors.

    Never call this automatically from a live conversation.
    """
    docs = load_documents()
    chunks = build_chunks(docs, chunk_size, overlap)

    embed_fn = SentenceTransformerEmbeddingFunction()
    client = _get_chroma_client()

    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        embedding_function=embed_fn,
    )
    collection.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )

    # Cache the collection that was just built.
    global _collection, _collection_name
    _collection = collection
    _collection_name = collection_name

    return collection, embed_fn, len(chunks)


def get_collection(collection_name=DEFAULT_COLLECTION_NAME):
    """Return the cached persisted collection without rebuilding it."""
    global _collection, _collection_name

    if _collection is not None and _collection_name == collection_name:
        return _collection

    with _init_lock:
        if _collection is not None and _collection_name == collection_name:
            return _collection

        embed_fn = SentenceTransformerEmbeddingFunction()
        client = _get_chroma_client()

        try:
            _collection = client.get_collection(
                name=collection_name,
                embedding_function=embed_fn,
            )
            _collection_name = collection_name
        except Exception as exc:
            raise RuntimeError(
                f"Chroma collection '{collection_name}' not found at {CHROMA_DIR}. "
                "Run `python src/rag_pipeline.py` once to build it."
            ) from exc

    return _collection


# ---------- 5. Retriever ----------

def retrieve(collection, query, top_k=4):
    results = collection.query(query_texts=[query], n_results=top_k)
    hits = []

    if not results.get("ids") or not results["ids"][0]:
        return hits

    for i in range(len(results["ids"][0])):
        hits.append(
            {
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )
    return hits


# ---------- 6. Warmup ----------

def warmup(
    collection_name: str = DEFAULT_COLLECTION_NAME,
    warmup_query: str = DEFAULT_WARMUP_QUERY,
) -> Dict[str, Any]:
    """Pre-load all expensive RAG pieces once per process.

    Safe to call repeatedly. Concurrent calls collapse into one warmup.

    The one-result query warms:
      1. SentenceTransformer import/model load
      2. embedding execution
      3. Chroma PersistentClient
      4. persisted collection access
      5. SQLite/vector query path
    """
    global _warmup_error, _warmup_ms

    if _warmup_done.is_set():
        return {
            "success": _warmup_error is None,
            "elapsed_ms": _warmup_ms,
            "error": _warmup_error,
            "already_warm": True,
        }

    with _warmup_lock:
        if _warmup_done.is_set():
            return {
                "success": _warmup_error is None,
                "elapsed_ms": _warmup_ms,
                "error": _warmup_error,
                "already_warm": True,
            }

        started = time.perf_counter()
        try:
            model = _get_embedding_model()

            # Explicit encode makes sure the transformer is fully initialized
            # before the caller's first factual question.
            model.encode(
                [warmup_query],
                convert_to_numpy=True,
                normalize_embeddings=True,
            )

            collection = get_collection(collection_name)

            # Warm the persisted vector query path too.
            collection.query(query_texts=[warmup_query], n_results=1)

            _warmup_error = None
            _warmup_ms = int((time.perf_counter() - started) * 1000)
            print(f"[RAG] ready ({_warmup_ms}ms)")
        except Exception as exc:
            _warmup_error = str(exc)
            _warmup_ms = int((time.perf_counter() - started) * 1000)
            print(f"[RAG] warmup failed after {_warmup_ms}ms: {exc}")
        finally:
            _warmup_done.set()

    return {
        "success": _warmup_error is None,
        "elapsed_ms": _warmup_ms,
        "error": _warmup_error,
        "already_warm": False,
    }


def warmup_status() -> Dict[str, Any]:
    """Cheap status helper for diagnostics/health endpoints."""
    return {
        "done": _warmup_done.is_set(),
        "success": _warmup_done.is_set() and _warmup_error is None,
        "elapsed_ms": _warmup_ms,
        "error": _warmup_error,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "collection": _collection_name,
    }


# ---------- 7. Answer Generation ----------

def generate_answer(query, hits):
    context = "\n\n".join(h["text"] for h in hits)

    try:
        if not base_url or not api_key:
            raise RuntimeError("no LLM credentials in environment")

        resp = _get_llm_client().chat.completions.create(
            model="smart",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only using the provided context. If the context does "
                        "not contain the answer, say you don't have that information. "
                        "Do not make up any details."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {query}",
                },
            ],
            max_tokens=300,
        )
        return resp.choices[0].message.content, "llm_generated"

    except Exception:
        if not hits:
            return "No relevant information found in the knowledge base.", "no_context"
        return hits[0]["text"][:400], "extractive_fallback_llm_unavailable"


if __name__ == "__main__":
    collection, embed_fn, n_chunks = build_vector_store()
    print(f"Vector store built with {n_chunks} chunks\n")

    test_query = "What amenities does the property in DHA Phase 6 Lahore have?"
    hits = retrieve(collection, test_query, top_k=3)

    for hit in hits:
        print("=" * 80)
        print(hit["text"])
        print("=" * 80)

    answer, mode = generate_answer(test_query, hits)
    print(f"\nAnswer ({mode}):\n{answer}")
