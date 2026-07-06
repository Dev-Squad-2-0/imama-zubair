# SQL Foundations for Data Science - Superstore Sales Dataset

## Overview

This task introduces the fundamentals of SQL using PostgreSQL. The Superstore Sales dataset is imported into a relational database, where SQL queries are used to retrieve, filter, sort, and summarize data.

The objective is to understand how relational databases work and how SQL enables efficient analysis of datasets that are too large to comfortably handle in spreadsheets.

---

# Learning Objectives

By completing this task, I learned how to:

- Understand relational database concepts
- Create and manage PostgreSQL databases
- Import CSV files into PostgreSQL
- Retrieve and filter data using SQL
- Sort and summarize data
- Use aggregate functions
- Group data using `GROUP BY`
- Inspect database tables and columns

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

# Superstore Dataset Setup Guide

## Step 1: Create a Database

```sql
CREATE DATABASE superstore;
```

Connect to the database:

```sql
\c superstore
```

---

## Step 2: Create the Table

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

---

## Step 3: Import the CSV

Move the CSV file somewhere PostgreSQL can access.

Then run:

```sql
COPY superstore_sales
FROM '/path/to/superstore_sales.csv'
DELIMITER ','
CSV HEADER;
```

### Windows Example

```sql
COPY superstore_sales
FROM 'C:/Users/YourName/Downloads/superstore_sales.csv'
DELIMITER ','
CSV HEADER;
```

> If you're using pgAdmin, you can also import the CSV through **Import/Export Data**, but the `COPY` command is the SQL-based approach.

---

## Step 4: Verify the Import

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

## Step 5: View the Table Structure

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

Number of orders per segment:

```sql
SELECT
    segment,
    COUNT(*) AS total_orders
FROM superstore_sales
GROUP BY segment;
```

---

# Useful Metadata Query

Display every column in the table:

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

# Learning Outcomes

After completing this project, I can:

- Explain the difference between databases, CSV files, and spreadsheets.
- Create and manage PostgreSQL databases.
- Import CSV data using SQL.
- Retrieve, filter, and sort data with SQL.
- Use aggregate functions to summarize data.
- Group records using `GROUP BY`.
- Inspect database metadata using `information_schema`.
- Write reusable SQL scripts for data analysis.