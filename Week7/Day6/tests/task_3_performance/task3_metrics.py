from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


MEMORY_LABEL_HINTS = (
    "memory",
    "sticky",
    "carried",
    "carry",
    "remember",
    "retained",
    "persists",
    "preserved",
)

BOOKING_LABEL_HINTS = (
    "booking succeeds",
    "booking success",
    "status booked",
    "appointment booked",
)


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)

    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    weight = pos - lo
    return round(ordered[lo] * (1 - weight) + ordered[hi] * weight, 2)


def rate(successes: int, total: int) -> float:
    return round((100.0 * successes / total), 2) if total else 0.0


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latency_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    turn_latencies = [
        float(turn["latency_ms"])
        for result in results
        for turn in result.get("turns", [])
        if turn.get("latency_ms") is not None
    ]

    conversation_latencies = []
    for result in results:
        values = [
            float(turn["latency_ms"])
            for turn in result.get("turns", [])
            if turn.get("latency_ms") is not None
        ]
        if values:
            conversation_latencies.append(sum(values))

    return {
        "turn_count": len(turn_latencies),
        "turn_latency_ms": {
            "mean": round(statistics.mean(turn_latencies), 2)
            if turn_latencies else 0.0,
            "median_p50": percentile(turn_latencies, 0.50),
            "p95": percentile(turn_latencies, 0.95),
            "max": round(max(turn_latencies), 2) if turn_latencies else 0.0,
            "min": round(min(turn_latencies), 2) if turn_latencies else 0.0,
        },
        "conversation_latency_ms": {
            "mean": round(statistics.mean(conversation_latencies), 2)
            if conversation_latencies else 0.0,
            "median_p50": percentile(conversation_latencies, 0.50),
            "p95": percentile(conversation_latencies, 0.95),
            "max": round(max(conversation_latencies), 2)
            if conversation_latencies else 0.0,
        },
    }



def scenario_passed(result: Dict[str, Any]) -> bool:
    """Resolve scenario success across Task 1 result schema versions.

    Supported formats:

    Newer runner:
        {"passed": true, "checks": [...]}

    production_eval / older runner:
        {
          "checks": [{"status": "PASS"}, ...],
          "error": null
        }

    A scenario passes when:
    - explicit `passed` exists and is truthy; OR
    - `passed` is absent, there is no unhandled error, there is at least one
      check, and every check has status PASS.
    """
    if "passed" in result and result.get("passed") is not None:
        return bool(result.get("passed"))

    if result.get("error"):
        return False

    checks = result.get("checks") or []
    if not checks:
        # Do not silently call an unscored scenario successful.
        return False

    return all(
        str(check.get("status", "")).strip().upper() == "PASS"
        for check in checks
    )


def conversation_success_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    passed = [r for r in results if scenario_passed(r)]
    failed = [r for r in results if not scenario_passed(r)]
    return {
        "total": len(results),
        "successful": len(passed),
        "failed": len(failed),
        "success_rate_percent": rate(len(passed), len(results)),
        "passed_scenarios": [r.get("id") for r in passed],
        "failed_scenarios": [r.get("id") for r in failed],
    }


def _matching_checks(
    result: Dict[str, Any],
    hints: Tuple[str, ...],
) -> List[Dict[str, Any]]:
    matching = []
    for check in result.get("checks", []):
        label = str(check.get("label", "")).lower()
        if any(hint in label for hint in hints):
            matching.append(check)
    return matching


def booking_success_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    evaluated = []
    successful = []
    failed = []

    for result in results:
        checks = _matching_checks(result, BOOKING_LABEL_HINTS)

        # Fallback for suites that expose final appointment state but use
        # differently-worded booking check labels.
        is_appointment_case = result.get("category") == "appointment"
        final_state = result.get("final_state") or {}
        appointment_status = final_state.get("appointment_status") or {}

        if not checks and is_appointment_case and appointment_status:
            status = str(appointment_status.get("status", "")).lower()
            checks = [{
                "label": "final appointment status booked",
                "status": "PASS" if status == "booked" else "FAIL",
            }]

        if not checks:
            continue

        evaluated.append(result.get("id"))
        passed = all(str(c.get("status", "")).upper() == "PASS" for c in checks)

        if passed:
            successful.append(result.get("id"))
        else:
            failed.append({
                "id": result.get("id"),
                "failed_checks": [
                    c.get("label")
                    for c in checks
                    if str(c.get("status", "")).upper() != "PASS"
                ],
            })

    return {
        "booking_tests": len(evaluated),
        "successful_bookings": len(successful),
        "failed_bookings": len(failed),
        "booking_success_rate_percent": rate(len(successful), len(evaluated)),
        "passed_scenarios": successful,
        "failed_scenarios": failed,
    }


def memory_accuracy_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    checks_found = []

    for result in results:
        for check in _matching_checks(result, MEMORY_LABEL_HINTS):
            checks_found.append({
                "scenario_id": result.get("id"),
                "label": check.get("label"),
                "status": str(check.get("status", "")).upper(),
                "detail": check.get("detail"),
            })

    passed = [c for c in checks_found if c["status"] == "PASS"]
    failed = [c for c in checks_found if c["status"] != "PASS"]

    return {
        "memory_checks": len(checks_found),
        "passed": len(passed),
        "failed": len(failed),
        "memory_accuracy_percent": rate(len(passed), len(checks_found)),
        "passed_checks": passed,
        "failed_checks": failed,
    }


def _find_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    lookup = {str(c).lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def tool_failure_metrics(
    results: List[Dict[str, Any]],
    evaluation_db: Optional[Path] = None,
) -> Dict[str, Any]:
    failures = []

    # 1) Explicit scenario-level exceptions that clearly mention an integration.
    for result in results:
        error = str(result.get("error") or "")
        if error and re.search(
            r"\b(tool|calendar|email|gmail|google|crm|rag|chroma|api)\b",
            error,
            re.IGNORECASE,
        ):
            failures.append({
                "source": "scenario_error",
                "scenario_id": result.get("id"),
                "detail": error,
            })

        # 2) If a newer runner records tool calls/results, use them.
        for call in result.get("tool_calls", []) or []:
            call_result = call.get("result")
            if isinstance(call_result, dict) and call_result.get("success") is False:
                failures.append({
                    "source": "tool_call",
                    "scenario_id": result.get("id"),
                    "tool": call.get("tool"),
                    "detail": call_result.get("error"),
                })

    db_rows_checked = 0
    db_failure_rows = []

    # 3) CRM event statuses from the isolated evaluation DB, when available.
    if evaluation_db and evaluation_db.exists():
        try:
            conn = sqlite3.connect(str(evaluation_db))
            conn.row_factory = sqlite3.Row

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            if "crm_events" in tables:
                cols = [
                    row[1]
                    for row in conn.execute("PRAGMA table_info(crm_events)").fetchall()
                ]
                status_col = _find_column(cols, ("status", "result_status"))
                event_col = _find_column(cols, ("event_type", "type", "event"))
                error_col = _find_column(cols, ("error", "error_message", "message"))

                rows = conn.execute("SELECT * FROM crm_events").fetchall()
                db_rows_checked = len(rows)

                if status_col:
                    for row in rows:
                        status = str(row[status_col] or "").lower()
                        if status in {"fail", "failed", "failure", "error"}:
                            item = {
                                "source": "crm_events",
                                "status": row[status_col],
                            }
                            if event_col:
                                item["event_type"] = row[event_col]
                            if error_col:
                                item["detail"] = row[error_col]
                            db_failure_rows.append(item)
                            failures.append(item)

            conn.close()
        except Exception as exc:
            failures.append({
                "source": "tool_failure_audit",
                "detail": f"Could not inspect evaluation DB: {exc}",
                "audit_error": True,
            })

    audit_errors = [f for f in failures if f.get("audit_error")]
    actual_failures = [f for f in failures if not f.get("audit_error")]

    return {
        "tool_failures": len(actual_failures),
        "crm_event_rows_checked": db_rows_checked,
        "failure_rate_percent": (
            rate(len(db_failure_rows), db_rows_checked)
            if db_rows_checked else None
        ),
        "failures": actual_failures,
        "audit_warnings": audit_errors,
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def load_properties_from_db(db_path: Path) -> List[Dict[str, Any]]:
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    if not _table_exists(conn, "properties"):
        conn.close()
        return []

    rows = [dict(row) for row in conn.execute("SELECT * FROM properties").fetchall()]
    conn.close()
    return rows


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _price_mentions(sentence: str) -> List[int]:
    """Extract approximate PKR claims from crore/lakh language."""
    claims = []

    crore_re = re.compile(r"(\d+(?:\.\d+)?)\s*crore", re.IGNORECASE)
    lakh_re = re.compile(r"(\d+(?:\.\d+)?)\s*lakh", re.IGNORECASE)

    for m in crore_re.finditer(sentence):
        claims.append(round(float(m.group(1)) * 10_000_000))

    for m in lakh_re.finditer(sentence):
        claims.append(round(float(m.group(1)) * 100_000))

    return claims


def hallucination_metrics(
    results: List[Dict[str, Any]],
    properties: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Audit structured property claims against SQLite ground truth.

    This intentionally scores facts we can verify deterministically:
      - property title exists in the database;
      - price claimed near that title matches database price within 2%;
      - bedroom count claimed near that title matches database bedrooms.

    It does not use an LLM judge and therefore does not consume model quota.
    """
    if not properties:
        return {
            "claims_checked": 0,
            "supported_claims": 0,
            "hallucinated_claims": 0,
            "hallucination_rate_percent": None,
            "details": [],
            "warning": "No properties table was available for deterministic audit.",
        }

    title_key = next(
        (k for k in ("title", "property_title", "name") if k in properties[0]),
        None,
    )
    price_key = next(
        (k for k in ("price_pkr", "price", "asking_price") if k in properties[0]),
        None,
    )
    bedrooms_key = next(
        (k for k in ("bedrooms", "beds") if k in properties[0]),
        None,
    )

    if not title_key:
        return {
            "claims_checked": 0,
            "supported_claims": 0,
            "hallucinated_claims": 0,
            "hallucination_rate_percent": None,
            "details": [],
            "warning": "Properties table has no recognizable title column.",
        }

    claims = []

    for result in results:
        for turn in result.get("turns", []):
            reply = str(turn.get("agent_reply") or "")
            reply_norm = _normalize(reply)

            for prop in properties:
                title = str(prop.get(title_key) or "").strip()
                if not title or _normalize(title) not in reply_norm:
                    continue

                # Property existence/title claim is supported because the title
                # was matched directly to a DB row.
                claims.append({
                    "scenario_id": result.get("id"),
                    "type": "property_title",
                    "property": title,
                    "status": "supported",
                })

                # Inspect a local text window following the title.
                start = reply_norm.find(_normalize(title))
                window = reply_norm[start:start + max(220, len(title) + 160)]

                if price_key and prop.get(price_key) is not None:
                    stated_prices = _price_mentions(window)
                    if stated_prices:
                        truth = float(prop[price_key])
                        best = min(stated_prices, key=lambda p: abs(p - truth))
                        tolerance = max(100_000.0, truth * 0.02)
                        supported = abs(best - truth) <= tolerance
                        claims.append({
                            "scenario_id": result.get("id"),
                            "type": "price",
                            "property": title,
                            "claimed_pkr": best,
                            "ground_truth_pkr": prop[price_key],
                            "status": "supported" if supported else "hallucinated",
                        })

                if bedrooms_key and prop.get(bedrooms_key) is not None:
                    bed_match = re.search(
                        r"\b(\d+)\s*(?:bedroom|bedrooms|bed)\b",
                        window,
                        re.IGNORECASE,
                    )
                    if bed_match:
                        claimed = int(bed_match.group(1))
                        truth = int(prop[bedrooms_key])
                        claims.append({
                            "scenario_id": result.get("id"),
                            "type": "bedrooms",
                            "property": title,
                            "claimed": claimed,
                            "ground_truth": truth,
                            "status": "supported"
                            if claimed == truth else "hallucinated",
                        })

    hallucinated = [c for c in claims if c["status"] == "hallucinated"]
    supported = [c for c in claims if c["status"] == "supported"]

    return {
        "claims_checked": len(claims),
        "supported_claims": len(supported),
        "hallucinated_claims": len(hallucinated),
        "hallucination_rate_percent": rate(len(hallucinated), len(claims)),
        "details": claims,
        "scope_note": (
            "Deterministic audit of structured property title/price/bedroom "
            "claims against SQLite ground truth."
        ),
    }
