# SQL Joins & Relational Database Analysis

## Overview

Brief explanation of the DVD Rental database and the goal of learning SQL JOINs.

## Dataset

DVD Rental Sample Database
**Source**: https://neon.com/postgresql/getting-started/sample-database

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

> Right click on the db --> select ERD for databse --> generate ERD and download it

