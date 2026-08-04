"""
Day 2 - Task 3 support: loads the structured CSVs into SQLite.
This is the structured half of the retrieval system (exact facts).
"""

import os
import sqlite3
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(BASE, "db", "knowledge_base.db")


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    tables = ["properties", "locations", "amenities", "schools",
              "hospitals", "payment_plans", "developers", "faqs"]

    for table in tables:
        csv_path = os.path.join(DATA_DIR, f"{table}.csv")
        df = pd.read_csv(csv_path)
        df.to_sql(table, conn, if_exists="replace", index=False)
        print(f"Loaded table '{table}' with {len(df)} rows")

    conn.commit()
    conn.close()
    print(f"\nDatabase written to {DB_PATH}")


if __name__ == "__main__":
    main()
