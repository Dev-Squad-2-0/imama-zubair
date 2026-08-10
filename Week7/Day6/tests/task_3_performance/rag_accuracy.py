from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _tokens(text: str) -> set:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z0-9\u0600-\u06ff]+", text or "")
        if len(t) >= 3
    }


def _jaccard(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _query_from_document(text: str) -> str:
    """Create a retrieval query directly from corpus ground truth.

    We use the first meaningful sentence/phrase, capped so this remains a
    retrieval task rather than passing an entire source document as the query.
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""

    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    candidate = next((p for p in pieces if len(p.split()) >= 6), cleaned)

    words = candidate.split()
    return " ".join(words[:18])


def evaluate_rag_accuracy(
    max_cases: int = 10,
    top_k: int = 3,
) -> Dict[str, Any]:
    """Measure retrieval hit-rate@K against the project's indexed documents.

    No LLM is called. This evaluates the RAG retriever itself.
    """
    try:
        import rag_pipeline
    except Exception as exc:
        return {
            "cases": 0,
            "correct": 0,
            "rag_accuracy_percent": None,
            "top_k": top_k,
            "details": [],
            "error": f"Could not import rag_pipeline: {exc}",
        }

    try:
        docs = rag_pipeline.load_documents()
        collection = rag_pipeline.get_collection()
    except Exception as exc:
        return {
            "cases": 0,
            "correct": 0,
            "rag_accuracy_percent": None,
            "top_k": top_k,
            "details": [],
            "error": f"Could not initialize RAG: {exc}",
        }

    selected = []
    seen_keys = set()

    # Prefer property-specific brochure/description documents because they
    # provide a strong expected source/property_id identity.
    ordered = sorted(
        docs,
        key=lambda d: 0 if (d[2] or {}).get("property_id") else 1,
    )

    for doc_id, text, metadata in ordered:
        query = _query_from_document(text)
        if not query:
            continue

        key = (
            (metadata or {}).get("source"),
            str((metadata or {}).get("property_id") or ""),
        )
        if key in seen_keys and key[1]:
            continue

        selected.append((doc_id, text, metadata or {}, query))
        seen_keys.add(key)

        if len(selected) >= max_cases:
            break

    details = []
    correct = 0

    for doc_id, source_text, expected_meta, query in selected:
        try:
            hits = rag_pipeline.retrieve(collection, query, top_k=top_k)
        except Exception as exc:
            details.append({
                "document_id": doc_id,
                "query": query,
                "passed": False,
                "error": str(exc),
            })
            continue

        expected_source = expected_meta.get("source")
        expected_property_id = str(expected_meta.get("property_id") or "")

        matched_rank = None
        best_overlap = 0.0

        for rank, hit in enumerate(hits, start=1):
            hit_meta = hit.get("metadata") or {}
            hit_source = hit_meta.get("source")
            hit_property_id = str(hit_meta.get("property_id") or "")
            overlap = _jaccard(source_text, hit.get("text", ""))
            best_overlap = max(best_overlap, overlap)

            if expected_property_id:
                identity_match = (
                    hit_source == expected_source
                    and hit_property_id == expected_property_id
                )
            else:
                # FAQ documents don't carry unique property IDs, so require
                # the expected source plus meaningful source-text overlap.
                identity_match = (
                    hit_source == expected_source
                    and overlap >= 0.15
                )

            if identity_match:
                matched_rank = rank
                break

        passed = matched_rank is not None
        correct += int(passed)

        details.append({
            "document_id": doc_id,
            "query": query,
            "expected_source": expected_source,
            "expected_property_id": expected_property_id or None,
            "passed": passed,
            "matched_rank": matched_rank,
            "best_text_overlap": round(best_overlap, 3),
        })

    total = len(selected)
    return {
        "cases": total,
        "correct": correct,
        "incorrect": total - correct,
        "rag_accuracy_percent": round(100 * correct / total, 2) if total else None,
        "top_k": top_k,
        "details": details,
        "method": "Ground-truth document retrieval hit-rate@K; no LLM judge.",
    }
