# SQL Joins & Relational Database Analysis

## Overview

Brief explanation of the DVD Rental database and the goal of learning SQL JOINs.

## Dataset

DVD Rental Sample Database
**Source**: https://neon.com/postgresql/getting-started/sample-database

# Part 1: Relationship Discovery

## Primary Keys and Foreign Keys

| Table             | Primary Key(s)                                       | Foreign Key(s)                                                                                                       |
| ----------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **actor**         | `actor_id`                                           | —                                                                                                                    |
| **address**       | `address_id`                                         | `city_id` → `city.city_id`                                                                                           |
| **category**      | `category_id`                                        | —                                                                                                                    |
| **city**          | `city_id`                                            | `country_id` → `country.country_id`                                                                                  |
| **country**       | `country_id`                                         | —                                                                                                                    |
| **customer**      | `customer_id`                                        | `address_id` → `address.address_id`                                                                                  |
| **film**          | `film_id`                                            | `language_id` → `language.language_id`                                                                               |
| **film_actor**    | (`actor_id`, `film_id`) *(Composite Primary Key)*    | `actor_id` → `actor.actor_id`<br>`film_id` → `film.film_id`                                                          |
| **film_category** | (`film_id`, `category_id`) *(Composite Primary Key)* | `film_id` → `film.film_id`<br>`category_id` → `category.category_id`                                                 |
| **inventory**     | `inventory_id`                                       | `film_id` → `film.film_id`                                                                                           |
| **language**      | `language_id`                                        | —                                                                                                                    |
| **payment**       | `payment_id`                                         | `customer_id` → `customer.customer_id`<br>`rental_id` → `rental.rental_id`<br>`staff_id` → `staff.staff_id`          |
| **rental**        | `rental_id`                                          | `customer_id` → `customer.customer_id`<br>`inventory_id` → `inventory.inventory_id`<br>`staff_id` → `staff.staff_id` |
| **staff**         | `staff_id`                                           | `address_id` → `address.address_id`                                                                                  |
| **store**         | `store_id`                                           | `address_id` → `address.address_id`<br>`manager_staff_id` → `staff.staff_id`                                         |


## Relationship Diagram

The Entity Relationship Diagram (ERD) was generated using pgAdmin's Generate ERD feature. The diagram illustrates the relationships between the normalized tables through their primary and foreign keys.

> Right click on the db --> select ERD for databse --> generate ERD and download it

#### ER Diagram:

![ERD](erd.png)

---

# Part 2: SQL JOIN Challenges

## JOIN TYPES

**JOIN/INNER JOIN**:Used when matching rows exist in both tables.

**LEFT JOIN**: Returns all rows from the left table and matching rows from the right table.

**RIGHT JOIN**: Returns all rows from the right table and matching rows from the left table.

**FULL OUTER JOIN**: Returns all rows from both tables, matching where possible.

## SQL Queries

1. Display Customer Name, Email, City, and Country.
2. Display every payment with Customer Name, Film Title, and Amount Paid.
3. Display every payment with Customer Name, Film Title, and Amount Paid.
4. Find the Top 10 customers based on total amount spent.
5. Display each film with its Category and Rental Rate.
6. Find all actors who appeared in each film.
7. Count how many films belong to each category.
8. Which categories generated the highest revenue? (Hint: This requires joining multiple tables.)
9. Find customers who have rented more than 20 films.
10. Which cities generated the highest rental revenue?