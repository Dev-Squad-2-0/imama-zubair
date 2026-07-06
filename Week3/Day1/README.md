# Setup Guide and SQL Queries: Superstore Sales Dataset

## Overview

The objective is to understand how relational databases work and how SQL enables efficient analysis of datasets that are too large to comfortably handle in spreadsheets.

---

# Technologies Used

- PostgreSQL
- pgAdmin 4
- SQL (the language)
- Kaggle Superstore Sales Dataset

---

# Dataset

**Name:** Superstore Sales Dataset

**Source:** https://www.kaggle.com/datasets/vivek468/superstore-dataset-final

---

# Project Structure

```text
Week 3/
└── Day 1/
    ├── README.md
    ├── concept_check.md
    ├── queries.sql
    ├── superstore_sales.csv
    └── screenshots/
        ├── database_created.png
        ├── table_imported.png
        ├── table_structure.png
        ├── select_count.png
        ├── select_limit10.png
        └── information_schema_columns.png
        └── installation.png
```

---

# Setup Instructions

### 1. Install PostgreSQL

Download and install PostgreSQL from:

https://www.postgresql.org/download/

During installation:

- Install pgAdmin
- Remember the password you create for the `postgres` user
- Keep the default port (5432)

---

### 2. Open pgAdmin

Launch pgAdmin and connect to your PostgreSQL server using the password you created during installation.

---

### 3. Create a Database

Right-click **Databases** → **Create** → **Database**

Database name:

```
superstore
```

---

### 4. Import the Dataset

1. Download the Superstore Sales dataset from Kaggle.
2. Create a table named superstore_sales

```sql
CREATE TABLE superstore_sales;
```

> Replace the column names and data types below if your downloaded dataset differs.

```sql
CREATE TABLE superstore_sales (
    "Row ID" INT,
    "Order ID" VARCHAR(30),
    "Order Date" DATE,
    "Ship Date" DATE,
    "Ship Mode" VARCHAR(50),
    "Customer ID" VARCHAR(30),
    "Customer Name" VARCHAR(100),
    "Segment" VARCHAR(50),
    "Country" VARCHAR(50),
    "City" VARCHAR(100),
    "State" VARCHAR(100),
    "Postal Code" VARCHAR(20),
    "Region" VARCHAR(50),
    "Product ID" VARCHAR(30),
    "Category" VARCHAR(50),
    "Sub-Category" VARCHAR(50),
    "Product Name" TEXT,
    "Sales" NUMERIC(10,2),
    "Quantity" INT,
    "Discount" NUMERIC(5,2),
    "Profit" NUMERIC(10,2)
);
```

3. Import the CSV into the table using pgAdmin's Import/Export tool OR
    Use the following query:
    ```sql
    copy superstore_sales ("Row ID","Order ID","Order Date","Ship Date","Ship Mode","Customer ID","Customer Name","Segment","Country","City","State","Postal Code","Region","Product ID","Category","Sub-Category","Product Name","Sales","Quantity","Discount","Profit") 
    FROM 'D:\repos\NETIXSOL\imama-zubair\Week3\Day1\superstore_sales.csv'
    WITH (FORMAT csv, HEADER, DELIMITER ',', ENCODING 'WIN1252')
```

```
### 5.: Verify the Import

Count the rows:

```sql
SELECT COUNT(*)
FROM superstore_sales;
```

Preview the data:

```sql
SELECT *
FROM superstore_sales
LIMIT 10;
```

---

### 6: View the Table Structure

View all columns and their data types:

```sql
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'superstore_sales';
```

---

# Deliverables

- ✅ README.md
- ✅ concept_check.md
- ✅ queries.sql
- ✅ Superstore Sales dataset (or dataset source)
- ✅ Screenshots of:
  - Database created
  - Table imported
  - Table structure
  - `SELECT COUNT(*)`
  - `SELECT * LIMIT 10`
  - `information_schema.columns`

---

## Author:
Imama Zubair