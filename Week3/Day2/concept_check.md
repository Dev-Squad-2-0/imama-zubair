# Concept Check: SQL Joins & Relational Database Analysis

## 1. Why do relational databases split data into multiple tables?

Relational databases split data into multiple tables to avoid storing the same information repeatedly. This reduces duplicate data, saves storage, and makes updates easier because each piece of information only needs to be changed in one place.



## 2. What is the difference between an INNER JOIN and a LEFT JOIN?

An **INNER JOIN** only returns rows that have matching values in both tables.

A **LEFT JOIN** returns all rows from the left table, even if there is no matching row in the right table. If no match exists, the columns from the right table are returned as `NULL`.


## 3. When would you use a FULL OUTER JOIN?

A **FULL OUTER JOIN** is used when you want to see every row from both tables, whether they have a match or not. Matching rows are combined, while non-matching rows show `NULL` for the missing values.


## 4. Why are Primary Keys and Foreign Keys important?

A **Primary Key** uniquely identifies each row in a table.

A **Foreign Key** connects one table to another by referencing a primary key. 

Together, they maintain relationships between tables and help keep the data accurate and consistent.


## 5. Explain normalization in simple words.

Normalization is the process of organizing a database into separate tables so that the same information isn't stored multiple times. This reduces duplicate data and makes the database easier to manage and update.


## 6. What is an ER Diagram?

An **Entity Relationship (ER) Diagram** is a visual representation of a database. It shows the tables, their primary keys, foreign keys, and how the tables are connected to each other.


## 7. What happens if a JOIN condition is incorrect?

If a JOIN condition is incorrect, the query may return incorrect results, duplicate rows, missing data, or far more rows than expected because unrelated records are matched together.
