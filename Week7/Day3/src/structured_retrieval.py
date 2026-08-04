"""
Day 2 - Task 3: Structured Retrieval

This module handles everything that has one correct, factual answer:
price, availability, plot size, agent name, payment plans.
These live in SQL because they are exact values that must never be
paraphrased or approximated by an LLM. Vector search is for the other
half of the system (brochures, descriptions, FAQs) where meaning
matters more than an exact field lookup.
"""

import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "db", "knowledge_base.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_property_by_id(property_id: int):
    conn = _connect()
    row = conn.execute("SELECT * FROM properties WHERE id = ?", (property_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_price(property_id: int):
    p = get_property_by_id(property_id)
    return p["price_pkr"] if p else None


def check_availability(property_id: int):
    p = get_property_by_id(property_id)
    return p["status"] if p else None


def get_plot_size(property_id: int):
    p = get_property_by_id(property_id)
    return p["size_marla"] if p else None


def get_agent_name(property_id: int):
    p = get_property_by_id(property_id)
    return {"agent_name": p["agent_name"], "agent_phone": p["agent_phone"]} if p else None


def search_properties(city=None, area=None, purpose=None, property_type=None,
                       min_bedrooms=None, max_price=None, status="available"):
    """Filtered structured search, used by the recommendation engine."""
    conn = _connect()
    query = "SELECT * FROM properties WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if city:
        query += " AND city = ?"
        params.append(city)
    if area:
        query += " AND area = ?"
        params.append(area)
    if purpose:
        query += " AND purpose = ?"
        params.append(purpose)
    if property_type:
        query += " AND property_type = ?"
        params.append(property_type)
    if min_bedrooms is not None:
        query += " AND bedrooms >= ?"
        params.append(min_bedrooms)
    if max_price is not None:
        query += " AND price_pkr <= ?"
        params.append(max_price)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_payment_plans():
    conn = _connect()
    rows = conn.execute("SELECT * FROM payment_plans").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_nearby_schools(location_id: int):
    conn = _connect()
    rows = conn.execute("SELECT * FROM schools WHERE location_id = ?", (location_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_nearby_hospitals(location_id: int):
    conn = _connect()
    rows = conn.execute("SELECT * FROM hospitals WHERE location_id = ?", (location_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    print("Sample structured queries:\n")
    sample = search_properties(city="Lahore", purpose="buy")[:3]
    for p in sample:
        print(f"- {p['title']} | Price: {p['price_pkr']} PKR | Status: {p['status']} | Agent: {p['agent_name']}")

    if sample:
        pid = sample[0]["id"]
        print(f"\nget_price({pid}) ->", get_price(pid))
        print(f"check_availability({pid}) ->", check_availability(pid))
        print(f"get_plot_size({pid}) ->", get_plot_size(pid))
        print(f"get_agent_name({pid}) ->", get_agent_name(pid))
