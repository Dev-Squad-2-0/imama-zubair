"""Deterministic security gate for caller-supplied prompt injection.

This module intentionally does NOT call an LLM. Requests that clearly ask the agent
to override instructions, reveal prompts/secrets/private data, or bypass booking
validation are intercepted before any LLM-facing node receives the caller text.
"""

import re
from typing import Optional


_PROMPT_EXTRACTION = re.compile(
    r"\b("
    r"system\s+prompt|hidden\s+prompt|developer\s+prompt|internal\s+prompt|"
    r"hidden\s+instructions?|system\s+instructions?|developer\s+instructions?|"
    r"reveal\s+(?:your\s+)?prompt|show\s+(?:me\s+)?(?:your\s+)?prompt|"
    r"paste\s+(?:the\s+)?(?:exact\s+)?(?:hidden\s+)?prompt|"
    r"print\s+(?:all\s+)?(?:hidden\s+)?instructions?"
    r")\b"
    r"|(خفیہ\s+ہدایات|سسٹم\s+پرومپٹ|اندرونی\s+ہدایات)",
    re.IGNORECASE,
)

_INSTRUCTION_OVERRIDE = re.compile(
    r"\b("
    r"ignore\s+(?:all\s+|the\s+|your\s+)?(?:previous\s+)?instructions?|"
    r"ignore\s+(?:all\s+|your\s+)?rules?|"
    r"forget\s+(?:all\s+|your\s+)?(?:previous\s+)?instructions?|"
    r"security\s+(?:checks?|rules?|instructions?)\s+(?:are\s+)?disabled|"
    r"bypass\s+(?:the\s+)?(?:security|validation|guardrails?)|"
    r"skip\s+(?:all\s+)?(?:validation|checks?)"
    r")\b"
    r"|(?:instructions?|rules?|security)\s+ignore\s+karo"
    r"|(?:instructions?|rules?)\s+follow\s+mat\s+karo"
    r"|(ہدایات\s+نظر\s+انداز|قواعد\s+نظر\s+انداز)",
    re.IGNORECASE,
)

_SECRET_OR_INTERNAL_DATA = re.compile(
    r"\b("
    r"api\s*keys?|credentials?|access\s*tokens?|refresh\s*tokens?|"
    r"environment\s+variables?|env\s+vars?|client\s+secret|"
    r"internal\s+company\s+data|private\s+configuration|database\s+paths?|"
    r"internal\s+configuration|company\s+secrets?"
    r")\b"
    r"|(اندرونی\s+کمپنی\s+ڈیٹا|خفیہ\s+ڈیٹا|کریڈینشل)",
    re.IGNORECASE,
)

_PRIVATE_CUSTOMER_DATA = re.compile(
    r"\b("
    r"all\s+(?:other\s+)?customers?|other\s+customers?|"
    r"customer\s+records?|crm\s+records?|"
    r"phone\s+numbers?.*appointment\s+history|"
    r"appointment\s+history.*phone\s+numbers?"
    r")\b"
    r"|(دوسرے\s+کسٹمر|تمام\s+کسٹمر|کسٹمر\s+ڈیٹا)",
    re.IGNORECASE,
)

_FAKE_OR_BYPASS_ACTION = re.compile(
    r"\b("
    r"fake\s+appointments?|book\s+\d+\s+fake\s+appointments?|"
    r"book.*without\s+(?:validation|checking|availability)|"
    r"do\s+not\s+(?:ask|check).*(?:calendar|availability|name|property)|"
    r"skip\s+ownership\s+checks?|"
    r"cancel.*event\s+id|reschedule.*event\s+id"
    r")\b",
    re.IGNORECASE,
)

_FAKE_AUTHORITY = re.compile(
    r"\b(i\s+am|i'm|im|main)\s+(?:the\s+)?(?:admin|administrator|developer)\b"
    r"|\bdeveloper\s+message\s*:",
    re.IGNORECASE,
)


def security_reason(text: str) -> Optional[str]:
    value = (text or "").strip()
    if not value:
        return None

    if _PROMPT_EXTRACTION.search(value):
        return "prompt_extraction"
    if _SECRET_OR_INTERNAL_DATA.search(value):
        return "internal_or_secret_data"
    if _PRIVATE_CUSTOMER_DATA.search(value):
        return "private_customer_data"
    if _INSTRUCTION_OVERRIDE.search(value):
        return "instruction_override"
    if _FAKE_OR_BYPASS_ACTION.search(value):
        return "unsafe_action_bypass"

    # Claiming admin/developer authority is only security-sensitive when paired
    # with a sensitive target/action. This reduces false positives.
    if _FAKE_AUTHORITY.search(value) and re.search(
        r"\b(prompt|instructions?|customer|crm|data|secret|credential|"
        r"booking|appointment|calendar|security)\b",
        value,
        re.IGNORECASE,
    ):
        return "fake_authority"

    return None


def is_security_sensitive_request(text: str) -> bool:
    return security_reason(text) is not None


def safe_security_reply(text: str) -> str:
    reason = security_reason(text)

    if reason in {"prompt_extraction", "instruction_override", "fake_authority"}:
        return (
            "Main internal prompts ya security instructions share ya override nahi "
            "kar sakta. Property, booking, rescheduling ya cancellation mein normal "
            "process ke through help kar sakta hoon."
        )

    if reason == "internal_or_secret_data":
        return (
            "Main API keys, credentials ya internal company configuration share nahi "
            "kar sakta. Agar property ya appointment se related help chahiye ho toh "
            "main us mein assist kar deta hoon."
        )

    if reason == "private_customer_data":
        return (
            "Main doosre customers ki private CRM ya appointment information share "
            "nahi kar sakta. Main sirf aap ki apni property ya appointment request "
            "mein help kar sakta hoon."
        )

    if reason == "unsafe_action_bypass":
        return (
            "Main booking ya calendar validation bypass karke fake ya unauthorized "
            "action perform nahi kar sakta. Genuine appointment ho toh main normal "
            "verification ke saath book kar deta hoon."
        )

    return (
        "Main is request ko security reasons ki wajah se process nahi kar sakta. "
        "Property ya appointment ke silsile mein main help kar sakta hoon."
    )
