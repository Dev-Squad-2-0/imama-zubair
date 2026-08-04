"""
Day 3 - Task 4: Objection Handling

Detects the objection category in what the customer just said, then returns
a response STRATEGY (not a hardcoded line) built from the rules already
defined in system_prompt.md's PERSUASION RULES and GUARDRAILS, plus the
example patterns in urdulish_persona.md's Objection Handling section.

Important: this does not invent new sales tactics. It operationalizes the
existing rules:
    - acknowledge the objection before offering an alternative (persuasion rule)
    - persuasion must be based on real value, never false urgency (persuasion rule)
    - always give an easy exit (persuasion rule)
    - never guarantee investment returns, refer to human advisor (guardrail)
    - stop pushing after two clear declines (guardrail)
    - escalate legal/contractual/payment questions beyond standard booking (escalation rule)

The actual sentence generation (final UrduLish wording) happens in the LLM
call inside conversation_agent.py, using the strategy this module returns as
part of the prompt. This module's job is classification + strategy, not
final phrasing, so swapping the LLM or persona later doesn't require
touching this file.
"""

import re
from dataclasses import dataclass
from typing import Optional, List


OBJECTION_CATEGORIES = [
    "price",
    "trust",
    "location",
    "investment",
    "builder",
    "maintenance",
]

_KEYWORDS = {
    "price": ["mehnga", "mehngi", "expensive", "budget se zyada", "price zyada", "rate zyada"],
    "trust": ["fraud", "dhoka", "trust nahi", "bharosa", "scam", "asli hai", "genuine hai"],
    "location": ["door hai", "far", "location theek nahi", "access", "traffic", "connectivity"],
    "investment": ["return", "profit", "resale", "value barhega", "investment achi hai",
                    "guarantee", "kitna faida"],
    "builder": ["builder", "developer", "construction quality", "delay", "possession late"],
    "maintenance": ["maintenance", "upkeep", "society charges", "monthly fee", "repair"],
}


@dataclass
class ObjectionStrategy:
    category: Optional[str]
    should_acknowledge_first: bool
    talking_points: List[str]
    guardrail_notes: List[str]
    escalate: bool


def detect_objection(customer_text: str) -> Optional[str]:
    lowered = customer_text.lower()
    for category, keywords in _KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return None


def build_strategy(category: Optional[str], decline_count: int = 0) -> ObjectionStrategy:
    """
    Returns the strategy the agent should follow. The LLM call in
    conversation_agent.py turns this into natural UrduLish, it doesn't
    decide the substance of the response.
    """
    if category is None:
        return ObjectionStrategy(None, False, [], [], False)

    if category == "price":
        return ObjectionStrategy(
            category="price",
            should_acknowledge_first=True,
            talking_points=[
                "acknowledge the price concern directly, don't dismiss it",
                "point to a real, checkable value signal: price trend in that area, "
                "or amenities that justify it (never invent numbers not in retrieved data)",
                "offer a more affordable alternative in the same area if one exists in the "
                "recommendation results",
            ],
            guardrail_notes=["never invent a discount or a price that isn't in structured data"],
            escalate=False,
        )

    if category == "trust":
        return ObjectionStrategy(
            category="trust",
            should_acknowledge_first=True,
            talking_points=[
                "acknowledge that trust is a fair concern in property dealing",
                "mention verifiable facts only: agency's registered listings, agent name "
                "and phone number, the option of an in-person site visit before any commitment",
                "never claim certifications, awards, or guarantees not present in retrieved data",
            ],
            guardrail_notes=["do not fabricate credentials or legal guarantees"],
            escalate=False,
        )

    if category == "location":
        return ObjectionStrategy(
            category="location",
            should_acknowledge_first=True,
            talking_points=[
                "acknowledge the concern about distance/access",
                "give real nearby context if available from retrieval (schools, hospitals, "
                "main roads) rather than a generic reassurance",
                "offer to check other areas that better match their commute or lifestyle need",
            ],
            guardrail_notes=[],
            escalate=False,
        )

    if category == "investment":
        return ObjectionStrategy(
            category="investment",
            should_acknowledge_first=True,
            talking_points=[
                "acknowledge interest in return potential",
                "share only factual price trend data if present in retrieval (e.g. "
                "'rising' price_trend field), described as a trend, not a promise",
                "explicitly state that guaranteed returns can't be promised and offer to "
                "connect them with a human investment advisor for anything beyond general trend info",
            ],
            guardrail_notes=["NEVER guarantee investment returns — this is a hard guardrail "
                               "in system_prompt.md, refer to human advisor"],
            escalate=True,
        )

    if category == "builder":
        return ObjectionStrategy(
            category="builder",
            should_acknowledge_first=True,
            talking_points=[
                "acknowledge that construction quality and delivery timeline matter",
                "share only what's in retrieved developer/brochure data (track record, "
                "past projects) rather than general reassurance",
                "if the question goes into contractual/legal territory (possession guarantees, "
                "penalty clauses), flag for escalation to a human agent",
            ],
            guardrail_notes=["legal/contractual specifics are outside agent scope, escalate"],
            escalate=False,  # only escalate if it drifts into contract terms, handled in agent layer
        )

    if category == "maintenance":
        return ObjectionStrategy(
            category="maintenance",
            should_acknowledge_first=True,
            talking_points=[
                "acknowledge the ongoing-cost concern",
                "share monthly society/maintenance charges only if present in retrieved data, "
                "otherwise say this will be confirmed and followed up rather than guessing",
            ],
            guardrail_notes=["do not guess maintenance fees not present in structured data"],
            escalate=False,
        )

    return ObjectionStrategy(category, True, [], [], False)


def should_stop_pushing(decline_count: int) -> bool:
    """system_prompt.md GUARDRAILS: 'Do not continue pushing a sale if the
    customer has clearly declined twice.'"""
    return decline_count >= 2


if __name__ == "__main__":
    samples = [
        "Yeh property thori mehngi hai.",
        "Mujhe is builder par bharosa nahi.",
        "Yeh area thora door hai office se.",
        "Investment ke hisaab se kitna profit hoga guaranteed?",
        "Monthly maintenance kitni hai is society ki?",
    ]
    for s in samples:
        cat = detect_objection(s)
        strat = build_strategy(cat)
        print(f"Customer: {s}")
        print(f"  -> category: {cat}, escalate: {strat.escalate}")
        for tp in strat.talking_points:
            print(f"     - {tp}")
        print()
