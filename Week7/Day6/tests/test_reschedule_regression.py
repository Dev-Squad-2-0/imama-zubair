"""
Regression test covering the two bugs fixed this session:

1. Phone-normalisation + CRM restore so a second call can reschedule without
   repeating all details.
2. "book" keyword in a past-tense context phrase ("mene appointment book ki
   thi") must NOT flip a live reschedule intent back to booking mode.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from appointment_intent import detect_appointment_intent, resolve_stateful_appointment_intent
from crm_logger import _normalize_phone, get_appointment_history

def test_phone_normalisation():
    cases = [
        ("+923022356799", "03022356799"),
        ("923022356799",  "03022356799"),
        ("03022356799",   "03022356799"),
        ("0302-2356799",  "03022356799"),
        ("+923001234567", "03001234567"),
    ]
    for raw, expected in cases:
        got = _normalize_phone(raw)
        assert got == expected, f"normalize_phone({raw!r}) = {got!r}, want {expected!r}"
    print("  OK  phone normalisation")

def test_crm_cross_format_lookup():
    local = "03022356799"
    e164  = "+923022356799"
    rows_local = get_appointment_history(local)
    rows_e164  = get_appointment_history(e164)
    assert len(rows_local) == len(rows_e164), (
        f"lookup({local!r}) -> {len(rows_local)} rows, "
        f"lookup({e164!r}) -> {len(rows_e164)} rows"
    )
    print(f"  OK  CRM cross-format lookup ({len(rows_local)} rows)")

def test_past_tense_book_in_reschedule_context():
    phrases = [
        "mene kal sham ki appointment book ki thi",
        "mene bahria town k liye appointment book ki thi",
        "meri appointment book ho gayi thi kal ke liye",
        "maine kal sham 5 baje ki booking ki thi",
        "mene appointment book karwa li thi DHA mein",
    ]
    for phrase in phrases:
        detected = detect_appointment_intent(phrase, has_existing_appointment=True)
        resolved = resolve_stateful_appointment_intent(
            detected_intent=detected,
            previous_intent="reschedule",
            last_write_action={},
        )
        assert resolved == "reschedule", (
            f"FAIL  {phrase!r}\n"
            f"       detected={detected!r}  resolved={resolved!r}  (want 'reschedule')"
        )
    print("  OK  past-tense 'book' phrases don't override live reschedule intent")

def test_genuine_book_intent_detected():
    phrases = [
        "appointment book karni hai",
        "visit book karna chahta hoon",
        "site visit book kar dein",
    ]
    for phrase in phrases:
        detected = detect_appointment_intent(phrase, has_existing_appointment=False)
        assert detected == "book", f"FAIL {phrase!r}: {detected!r}"
    print("  OK  genuine book intent detected")

def test_reschedule_intent_detected():
    phrases = [
        "appointment reschedule karni hai",
        "jo appointment hai usse change karna hai",
        "reschedule karna chahta hoon",
    ]
    for phrase in phrases:
        detected = detect_appointment_intent(phrase, has_existing_appointment=False)
        assert detected == "reschedule", f"FAIL {phrase!r}: {detected!r}"
    print("  OK  reschedule intent detected")

def test_resolve_stateful_carries_reschedule():
    resolved = resolve_stateful_appointment_intent(
        detected_intent=None,
        previous_intent="reschedule",
        last_write_action={},
    )
    assert resolved == "reschedule", f"Expected 'reschedule', got {resolved!r}"
    print("  OK  stateful reschedule carried on keyword-free turn")

if __name__ == "__main__":
    print("\n=== Reschedule regression tests ===\n")
    test_phone_normalisation()
    test_crm_cross_format_lookup()
    test_past_tense_book_in_reschedule_context()
    test_genuine_book_intent_detected()
    test_reschedule_intent_detected()
    test_resolve_stateful_carries_reschedule()
    print("\n--- All tests finished ---")
