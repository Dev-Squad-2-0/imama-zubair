"""
Day 2 - Task 4: Recommendation Engine

Filters candidates using structured SQL (budget, city, area, bedrooms, purpose)
then ranks them with a weighted score (budget fit, location match, bedroom
match, amenity match, purpose match). Weights come from domain_config.yaml
so tuning them does not require touching this code.
"""

import os
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from structured_retrieval import search_properties, get_nearby_schools, get_nearby_hospitals

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE, "config", "domain_config.yaml")

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

WEIGHTS = CONFIG["recommendation_weights"]


def _budget_fit_score(price, budget):
    if budget is None:
        return 0.5
    if price <= budget:
        # closer to budget without going over = better use of funds
        return 0.5 + 0.5 * (price / budget)
    else:
        over_pct = (price - budget) / budget
        return max(0.0, 0.5 - over_pct)


def _amenity_match_score(property_amenities, wanted_amenities):
    if not wanted_amenities:
        return 0.5
    have = set(a.strip().lower() for a in property_amenities.split(","))
    want = set(a.strip().lower() for a in wanted_amenities)
    if not want:
        return 0.5
    overlap = len(have & want)
    return overlap / len(want)


def recommend_properties(budget=None, city=None, area=None, bedrooms=None,
                          purpose=None, property_type=None, amenities=None,
                          investment_goal=None, top_n=5):
    """
    investment_goal: optional string like "high_growth" or "stable", used to
    bias toward locations tagged with a rising price_trend when purpose is investment.
    """
    candidates = search_properties(
        city=city,
        area=area,
        purpose=purpose,
        property_type=property_type,
        min_bedrooms=bedrooms,
        max_price=int(budget * 1.15) if budget else None,  # allow slight stretch, penalized in scoring
    )

    if not candidates:
        return []

    scored = []
    for p in candidates:
        budget_score = _budget_fit_score(p["price_pkr"], budget)
        location_score = 1.0 if (city and p["city"] == city) else (0.6 if city else 0.5)
        if area and p.get("area") == area:
            location_score = 1.0
        bedroom_score = 1.0 if (bedrooms and p["bedrooms"] == bedrooms) else (0.5 if bedrooms else 0.5)
        amenity_score = _amenity_match_score(p["amenities"], amenities)
        purpose_score = 1.0 if (purpose and p["purpose"] == purpose) else (0.5 if purpose else 0.5)

        total = (
            WEIGHTS["budget_fit"] * budget_score +
            WEIGHTS["location_match"] * location_score +
            WEIGHTS["bedroom_match"] * bedroom_score +
            WEIGHTS["amenity_match"] * amenity_score +
            WEIGHTS["purpose_match"] * purpose_score
        )

        if purpose == "investment" and investment_goal == "high_growth":
            # small nudge handled at scoring time, kept simple and transparent
            total += 0.05 if "rising" in str(p.get("price_trend", "")) else 0

        scored.append({**p, "match_score": round(total, 3)})

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:top_n]


if __name__ == "__main__":
    results = recommend_properties(
        budget=15_000_000,
        city="Lahore",
        bedrooms=3,
        purpose="buy",
        amenities=["Swimming Pool", "24/7 Security"],
    )
    print(f"Top recommendations ({len(results)}):\n")
    for r in results:
        print(f"[{r['match_score']}] {r['title']} - {r['price_pkr']} PKR - {r['amenities']}")