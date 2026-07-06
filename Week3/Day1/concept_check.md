# Concept Check: SQL

## 1. What problem does SQL solve that CSV files cannot?

SQL lets you work with very large datasets without opening the whole file. You can quickly search, filter, sort, and analyze data, and many people can use the same database at the same time.

---

## 2. What is the difference between a database table and a spreadsheet?

A database table stores data in a structured way inside a database and is made for handling large amounts of data. A spreadsheet is mainly used to view, edit, and calculate smaller datasets.

---

## 3. What is a Primary Key?

A Primary Key is a column that gives every row its own unique id. It cannot have duplicate values or be empty.

Example:

| student_id | name |
|------------|------|
| 1 | Ali |
| 2 | Sara |
| 3 | Ahmed |

Here, student_id is the Primary Key.

---

## 4. What is a Foreign Key?

A Foreign Key is a column that connects one table to another. It points to the Primary Key in another table so the two tables can be linked together.

Example:

**Customers**

| customer_id | customer_name |
|--------------|---------------|
| 1 | Ali |
| 2 | Sara |

**Orders**

| order_id | customer_id |
|----------|-------------|
| 101 | 1 |
| 102 | 2 |

Here, `customer_id` in the Orders table is a Foreign Key because it links each order to a customer.

---

## 5. What is the difference between WHERE and HAVING?

`WHERE` filters rows before they are grouped. `HAVING` filters the grouped results after using `GROUP BY`.

Example:

```sql
SELECT *
FROM superstore_sales
WHERE sales > 1000;
```

This only shows rows where the sales are greater than 1000.

```sql
SELECT category, SUM(sales)
FROM superstore_sales
GROUP BY category
HAVING SUM(sales) > 50000;
```

This only shows categories where the total sales are more than 50,000.

---

## 6. What is the difference between `ORDER BY` and `GROUP BY`?

`ORDER BY` sorts the data. `GROUP BY` puts rows with the same value into groups so you can calculate things like totals or averages.

Example:

```sql
SELECT *
FROM superstore_sales
ORDER BY sales DESC;
```

This sorts the rows from the highest sales to the lowest.

```sql
SELECT category, COUNT(*)
FROM superstore_sales
GROUP BY category;
```

This groups the rows by category and counts how many rows each category has.

---

## 7. What does `DISTINCT` do?

`DISTINCT` removes duplicate values and only shows unique ones.

Example:

```sql
SELECT DISTINCT category
FROM superstore_sales;
```

If there are hundreds of rows with the category "Furniture", it will only show "Furniture" once.

---

## 8. When should you use `LIMIT`?

You should use `LIMIT` when you only want to see a small number of rows. It is useful for checking your data without showing the whole table.

Example:

```sql
SELECT *
FROM superstore_sales
LIMIT 10;
```

This returns only the first 10 rows.

---

## 9. What are aggregate functions?

Aggregate functions are functions that perform calculations on a group of rows and return one result. Some common ones are `COUNT()`, `SUM()`, `AVG()`, `MIN()`, and `MAX()`.

Example:

```sql
SELECT AVG(sales)
FROM superstore_sales;
```

This returns the average value of the sales column.

---

## 10. Why do Data Scientists prefer databases over Excel for large datasets?

Databases can store millions of rows, run queries much faster, and let multiple people work with the same data at the same time. Excel works well for smaller datasets, but it becomes slow and difficult to manage when the data gets very large.