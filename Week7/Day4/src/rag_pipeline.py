"""
Day 2 - Task 2: RAG Pipeline

Document Loader -> Chunking -> Embedding -> Vector Store -> Retriever -> Answer Generation

Embeddings are generated locally using the Sentence Transformers
'all-MiniLM-L6-v2' model. Tried to use gemini embedding but the quota reached too quickly

The embeddings are stored in ChromaDB for semantic retrieval.

The final answer is generated separately using the configured LLM endpoint,
allowing the embedding model and generation model to be swapped independently.
"""

import os
import glob
import csv
import chromadb
# from sklearn.feature_extraction.text import TfidfVectorizer
# import numpy as np

from openai import OpenAI
# from google import genai

from sentence_transformers import SentenceTransformer #type: ignore

from dotenv import load_dotenv

embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

load_dotenv()

base_url = os.environ.get("BASE_URL")
api_key = os.environ.get("API_KEY")

# gemini_client = genai.Client(
#     api_key=os.environ["GEMINI_API_KEY"]
# )

llm_client = OpenAI(
    base_url=os.environ["BASE_URL"],
    api_key=os.environ["API_KEY"]
)



BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_DIR = os.path.join(BASE, "documents")
DATA_DIR = os.path.join(BASE, "data")
CHROMA_DIR = os.path.join(BASE, "db", "chroma")


# ---------- 1. Document Loader ----------

def load_documents():
    """Loads brochures, descriptions, and FAQs as (doc_id, text, metadata) tuples."""
    docs = []

    for path in glob.glob(os.path.join(DOC_DIR, "brochures", "*.txt")):
        pid = os.path.basename(path).replace("property_", "").replace(".txt", "")
        with open(path) as f:
            docs.append((f"brochure_{pid}", f.read(), {"source": "brochure", "property_id": pid}))

    for path in glob.glob(os.path.join(DOC_DIR, "descriptions", "*.txt")):
        pid = os.path.basename(path).replace("property_", "").replace(".txt", "")
        with open(path) as f:
            docs.append((f"description_{pid}", f.read(), {"source": "description", "property_id": pid}))

    faq_path = os.path.join(DATA_DIR, "faqs.csv")
    with open(faq_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            text = f"Q: {row['question']}\nA: {row['answer']}"
            docs.append((f"faq_{i}", text, {"source": "faq", "property_id": ""}))

    return docs


# ---------- 2. Chunking ----------
# Fixed-Size Chunking

def chunk_text(text, chunk_size=200, overlap=40):
    """Word-based chunking with overlap. chunk_size and overlap are in words."""
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
            all_chunks.append({
                "id": f"{doc_id}_chunk{i}",
                "text": piece,
                "metadata": meta,
            })
    return all_chunks


# ---------- 3. Embedding ----------

class SentenceTransformerEmbeddingFunction:
    """
    Embedding function backed by Sentence Transformers.
    Compatible with ChromaDB's embedding interface.
    """

    def __call__(self, input):
        embeddings = embedding_model.encode(
            input,
            convert_to_numpy=True,
            normalize_embeddings=True
        )
        return embeddings.tolist()

    def embed_documents(self, input):
        return self.__call__(input)

    def embed_query(self, input):
        return self.__call__(input)

    def name(self):
        return "all-MiniLM-L6-v2"

# ---------- 4. Vector Store ----------

def build_vector_store(chunk_size=200, overlap=40, collection_name="knowledge_base"):
    docs = load_documents()
    chunks = build_chunks(docs, chunk_size, overlap)

    embed_fn = SentenceTransformerEmbeddingFunction()


    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(name=collection_name, embedding_function=embed_fn)

    collection.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    return collection, embed_fn, len(chunks)


_collection = None


def get_collection(collection_name="knowledge_base"):
    """Connects to the already-built persisted collection instead of
    rebuilding it — build_vector_store() deletes and re-embeds everything,
    too slow/destructive to call on a live conversation path."""
    global _collection
    if _collection is None:
        embed_fn = SentenceTransformerEmbeddingFunction()
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        try:
            _collection = client.get_collection(name=collection_name, embedding_function=embed_fn)
        except Exception as e:
            raise RuntimeError(
                f"Chroma collection '{collection_name}' not found at {CHROMA_DIR}. "
                f"Run `python rag_pipeline.py` once to build it."
            ) from e
    return _collection


# ---------- 5. Retriever ----------

def retrieve(collection, query, top_k=4):
    results = collection.query(query_texts=[query], n_results=top_k)
    hits = []
    for i in range(len(results["ids"][0])):
        hits.append({
            "id": results["ids"][0][i],
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return hits


# ---------- 6. Answer Generation ----------

def generate_answer(query, hits):
    """Tries the internship platform's LLM endpoint. Falls back to an
    extractive answer (top retrieved chunk) if no LLM is reachable, and
    labels the fallback honestly rather than pretending it's a generated answer."""
    context = "\n\n".join(h["text"] for h in hits)

    try:
        # # from openai import OpenAI
        # base_url = os.environ.get("BASE_URL")
        # api_key = os.environ.get("API_KEY")
        if not base_url or not api_key:
            raise RuntimeError("no LLM credentials in environment")

        # llm_client = OpenAI(
        #     base_url=os.environ["BASE_URL"],
        #     api_key=os.environ["API_KEY"]
# )
        resp = llm_client.chat.completions.create(
            model="smart",
            messages=[
                {"role": "system", "content": (
                    "Answer only using the provided context. If the context does not "
                    "contain the answer, say you don't have that information. Do not "
                    "make up any details."
                )},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
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
    for h in hits:
        # print(f"[{h['metadata']['source']}] dist={h['distance']:.3f} :: {h['text'][:100]}...")

        print("=" * 80)
        print(h["text"])
        print("=" * 80)

    answer, mode = generate_answer(test_query, hits)
    print(f"\nAnswer ({mode}):\n{answer}")
