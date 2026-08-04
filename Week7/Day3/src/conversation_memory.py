"""
Day 3 - Task 3: Context Memory

Keeps a running "slot" state per call so the agent understands references
like "us se sasti koi option?" (cheaper than that one) without the customer
repeating themselves. This is deliberately simple: a slot dictionary plus a
short turn history, not a separate vector memory store. For a single phone
call (a few minutes), that's all that's needed, and it's easy for an intern
to explain in a review.

Example flow this supports:
    Turn 1  "Budget 3 crore hai"              -> slots.budget = 30,000,000
    Turn 2  "DHA mein kya options hain?"       -> slots.area = "DHA Phase 6"
                                                   (uses budget from turn 1)
    Turn 3  "Us se sasti koi option?"          -> reads slots.last_shown_price
                                                   and lowers the budget ceiling
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# crude PKR parser: "3 crore", "80 lakh", "3.5 crore", "15000000"
_CRORE = 10_000_000
_LAKH = 100_000


def parse_pkr_amount(text: str) -> Optional[int]:
    text = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*crore", text)
    if m:
        return int(float(m.group(1)) * _CRORE)
    m = re.search(r"(\d+(?:\.\d+)?)\s*lakh", text)
    if m:
        return int(float(m.group(1)) * _LAKH)
    m = re.search(r"\b(\d{6,})\b", text)  # raw number like 15000000
    if m:
        return int(m.group(1))
    return None


@dataclass
class ConversationSlots:
    """Everything the agent currently 'knows' about this caller's intent."""
    budget: Optional[int] = None
    city: Optional[str] = None
    area: Optional[str] = None
    purpose: Optional[str] = None          # buy, rent, commercial, investment
    bedrooms: Optional[int] = None
    property_type: Optional[str] = None
    last_shown_property_ids: List[int] = field(default_factory=list)
    last_shown_min_price: Optional[int] = None
    last_shown_max_price: Optional[int] = None
    pending_appointment: Optional[Dict[str, Any]] = None
    decline_count: int = 0                 # tracks "no thanks" for the no-pushing-past-2x rule


@dataclass
class ConversationMemory:
    """Full memory for one call: slots + turn history."""
    slots: ConversationSlots = field(default_factory=ConversationSlots)
    history: List[Dict[str, str]] = field(default_factory=list)

    def add_turn(self, speaker: str, text: str):
        self.history.append({"speaker": speaker, "text": text})

    def recent_context(self, n=6) -> str:
        """Last n turns as plain text, used as LLM context alongside slots."""
        return "\n".join(f"{t['speaker']}: {t['text']}" for t in self.history[-n:])

    # ---- slot updates, called by conversation_agent.py after each customer turn ----

    def update_from_customer_text(self, text: str):
        lowered = text.lower()

        amount = parse_pkr_amount(text)
        if amount:
            self.slots.budget = amount

        # maps loose customer phrasing to the canonical area name stored in the DB
        area_aliases = {
            "dha phase 6": "DHA Phase 6",
            "dha": "DHA Phase 6",   # only DHA phase in this demo dataset
            "bahria town": "Bahria Town",
            "gulberg": "Gulberg",
            "gulshan-e-iqbal": "Gulshan-e-Iqbal",
            "f-10": "F-10", "f-11": "F-11", "e-11": "E-11",
        }
        for alias in sorted(area_aliases, key=len, reverse=True):
            if alias in lowered:
                self.slots.area = area_aliases[alias]
                break

        for city in ["lahore", "karachi", "islamabad"]:
            if city in lowered:
                self.slots.city = city.title()
                break

        for purpose_kw, purpose_val in [("rent", "rent"), ("kiraya", "rent"),
                                          ("invest", "investment"), ("buy", "buy"),
                                          ("khareed", "buy"), ("commercial", "commercial")]:
            if purpose_kw in lowered:
                self.slots.purpose = purpose_val
                break

        m = re.search(r"(\d+)\s*(?:bed|bedroom|kamre)", lowered)
        if m:
            self.slots.bedrooms = int(m.group(1))

        if any(p in lowered for p in ["sasti", "kam budget", "cheaper", "affordable"]):
            # "us se sasti koi option" -> lower the ceiling below the last shown price
            if self.slots.last_shown_min_price:
                self.slots.budget = self.slots.last_shown_min_price - 1

        if any(p in lowered for p in ["nahi chahiye", "nahi", "not interested", "no thanks"]):
            self.slots.decline_count += 1

    def record_shown_properties(self, properties: List[Dict[str, Any]]):
        self.slots.last_shown_property_ids = [p["id"] for p in properties]
        if properties:
            prices = [p["price_pkr"] for p in properties]
            self.slots.last_shown_min_price = min(prices)
            self.slots.last_shown_max_price = max(prices)

    def as_recommendation_kwargs(self) -> Dict[str, Any]:
        """Slots translated straight into recommendation_engine.recommend_properties()
        kwargs, so conversation_agent.py doesn't have to re-map fields."""
        return {
            "budget": self.slots.budget,
            "city": self.slots.city,
            "area": self.slots.area,
            "bedrooms": self.slots.bedrooms,
            "purpose": self.slots.purpose,
        }


if __name__ == "__main__":
    mem = ConversationMemory()

    mem.add_turn("customer", "Budget 3 crore hai.")
    mem.update_from_customer_text("Budget 3 crore hai.")
    print("After turn 1 slots:", mem.slots)

    mem.add_turn("customer", "DHA mein kya options hain?")
    mem.update_from_customer_text("DHA mein kya options hain?")
    print("After turn 2 slots:", mem.slots)

    # simulate the agent having shown properties priced 3.2cr-5.5cr from DHA
    mem.record_shown_properties([
        {"id": 101, "price_pkr": 32_000_000},
        {"id": 105, "price_pkr": 55_000_000},
    ])

    mem.add_turn("customer", "Us se sasti koi option?")
    mem.update_from_customer_text("Us se sasti koi option?")
    print("After turn 3 slots:", mem.slots)
    print("\nRecommendation kwargs derived from memory:", mem.as_recommendation_kwargs())
