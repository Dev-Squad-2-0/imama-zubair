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

import difflib
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
    # Each category also carries a native Urdu-script variant, not a
    # transliteration of the Roman list - same reasoning as
    # conversation_memory.py's _NAME_PATTERNS_URDU_SCRIPT: STT can hand back
    # either script depending on how the customer actually speaks, and this
    # is the one place that split can't be missed - it's what decides
    # whether the investment guardrail (never promise guaranteed returns)
    # even fires.
    "price": ["mehnga", "mehngi", "expensive", "budget se zyada", "price zyada", "rate zyada",
              "مہنگا", "مہنگی", "بجٹ سے زیادہ"],
    "trust": ["fraud", "dhoka", "trust nahi", "bharosa", "scam", "asli hai", "genuine hai",
              "دھوکہ", "بھروسہ", "فراڈ"],
    "location": ["door hai", "far", "location theek nahi", "access", "traffic", "connectivity",
                 "دور ہے", "ٹریفک"],
    "investment": ["return", "profit", "resale", "value barhega", "investment achi hai",
                    "guarantee", "kitna faida", "منافع", "فائدہ", "گارنٹی", "انویسٹمنٹ"],
    "builder": ["builder", "developer", "construction quality", "delay", "possession late",
                "بلڈر", "تاخیر"],
    "maintenance": ["maintenance", "upkeep", "society charges", "monthly fee", "repair",
                     "دیکھ بھال", "مینٹیننس"],
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

    # exact substring match first (fast path, no false-positive risk)
    for category, keywords in _KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category

    # fuzzy fallback for STT spelling drift - confirmed live: Deepgram
    # transcribed "مہنگا" (mehnga/expensive) as "ماہنگا" (one extra
    # letter), which a plain substring check can never match no matter how
    # many correct spellings are in _KEYWORDS. Same reasoning as
    # nodes.py's _validate_categorical fuzzy fallback for city/area, just
    # applied per-word since objection keywords are short phrases embedded
    # in a longer sentence, not a single value to validate whole.
    # cutoff=0.8 on short Urdu/Roman words: loose enough to catch a
    # one-character STT slip, tight enough that unrelated short words
    # don't accidentally collide (e.g. "hai" vs "kya").
    words = lowered.split()
    for category, keywords in _KEYWORDS.items():
        for kw in keywords:
            kw_word_count = len(kw.split())
            if kw_word_count == 1:
                if difflib.get_close_matches(kw, words, n=1, cutoff=0.8):
                    return category
            else:
                # multi-word keyword ("budget se zyada") - check it as a
                # fuzzy substring by comparing against each same-length
                # window of words, not the whole sentence at once
                kw_words = kw.split()
                for i in range(len(words) - kw_word_count + 1):
                    window = " ".join(words[i:i + kw_word_count])
                    if difflib.SequenceMatcher(None, kw, window).ratio() >= 0.8:
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