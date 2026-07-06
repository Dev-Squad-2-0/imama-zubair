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

## Setup Instructions

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
    row_id INT,
    order_id VARCHAR(30),
    order_date DATE,
    ship_date DATE,
    ship_mode VARCHAR(50),
    customer_id VARCHAR(30),
    customer_name VARCHAR(100),
    segment VARCHAR(50),
    country VARCHAR(50),
    city VARCHAR(100),
    state VARCHAR(100),
    postal_code VARCHAR(20),
    region VARCHAR(50),
    product_id VARCHAR(30),
    category VARCHAR(50),
    sub_category VARCHAR(50),
    product_name TEXT,
    sales NUMERIC(10,2),
    quantity INT,
    discount NUMERIC(5,2),
    profit NUMERIC(10,2)
);
```

3. Import the CSV into the table using pgAdmin's Import/Export tool.

---

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

# Basic SQL Queries

## Retrieve all rows

```sql
SELECT *
FROM superstore_sales;
```

---

## Retrieve specific columns

```sql
SELECT customer_name, sales
FROM superstore_sales;
```

---

## Remove duplicate values

```sql
SELECT DISTINCT category
FROM superstore_sales;
```

---

## Filter rows

```sql
SELECT *
FROM superstore_sales
WHERE sales > 1000;
```

---

## Sort data

```sql
SELECT customer_name, sales
FROM superstore_sales
ORDER BY sales DESC;
```

---

## Limit returned rows

```sql
SELECT *
FROM superstore_sales
LIMIT 10;
```

---

## Rename a column

```sql
SELECT
    customer_name AS customer,
    sales AS total_sales
FROM superstore_sales;
```

---

# Aggregate Functions

## Count rows

```sql
SELECT COUNT(*)
FROM superstore_sales;
```

---

## Total sales

```sql
SELECT SUM(sales)
FROM superstore_sales;
```

---

## Average sales

```sql
SELECT AVG(sales)
FROM superstore_sales;
```

---

## Minimum sale

```sql
SELECT MIN(sales)
FROM superstore_sales;
```

---

## Maximum sale

```sql
SELECT MAX(sales)
FROM superstore_sales;
```

---

# Grouping Data

Total sales by category:

```sql
SELECT
    category,
    SUM(sales) AS total_sales
FROM superstore_sales
GROUP BY category;
```

Average profit by region:

```sql
SELECT
    region,
    AVG(profit) AS average_profit
FROM superstore_sales
GROUP BY region;
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