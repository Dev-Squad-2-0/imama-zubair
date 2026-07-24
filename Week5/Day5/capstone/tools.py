"""
Tools used by the proposal crew. `calculator` is reusedfrom Day 1/2.
`company_lookup` and `service_lookup` follow the same pattern as Day 4's
`product_lookup` (read-only JSON-backed catalog tools).
"""
import json
import os
from crewai.tools import tool

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

with open(os.path.join(DATA_DIR, "companies.json")) as f:
    COMPANIES = json.load(f)

with open(os.path.join(DATA_DIR, "services.json")) as f:
    SERVICES = json.load(f)


@tool("Calculator")
def calculator(operation: str, a: float, b: float) -> str:
    """Perform arithmetic on two numbers. operation must be one of: add, subtract, multiply, divide."""
    if operation == "add":
        return str(a + b)
    elif operation == "subtract":
        return str(a - b)
    elif operation == "multiply":
        return str(a * b)
    elif operation == "divide":
        if b == 0:
            return "Error: Cannot divide by zero."
        return str(a / b)
    else:
        return "Invalid operation."


@tool("Company Lookup")
def company_lookup(company_name: str) -> str:
    """Look up known background info for a company by name (industry, size, notes).
    Returns 'Error: not found' with a note to rely on the request description instead,
    if the company isn't in our CRM records (this is expected for brand-new leads)."""
    key = company_name.strip().lower()
    record = COMPANIES.get(key)
    if not record:
        return (
            f"Error: '{company_name}' not found in CRM records. This is a new lead — "
            "base your research on the project description provided in the request instead."
        )
    return json.dumps(record, indent=2)


@tool("Service Catalog Lookup")
def service_lookup(query: str = "all") -> str:
    """Look up Web3Geeks service offerings. Pass 'all' to list every service with price,
    duration, and what it's best suited for, so you can match services to client needs."""
    if query == "all":
        return json.dumps(SERVICES, indent=2)
    key = query.strip().lower().replace(" ", "_")
    item = SERVICES.get(key)
    if not item:
        return f"Error: no service with id '{query}'. Valid ids: {list(SERVICES.keys())}"
    return json.dumps(item, indent=2)
