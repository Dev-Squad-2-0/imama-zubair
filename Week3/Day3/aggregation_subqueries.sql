-- Part 1 — Aggregation Basics
-- 1. Find the total revenue generated per store.
SELECT s.store_id, SUM(p.amount) AS "Total Revenue"
FROM payment AS p
JOIN staff AS s 
ON p.staff_id = s.staff_id
GROUP BY s.store_id
ORDER BY "Total Revenue" DESC

-- 2. Find the average rental duration per film category.
SELECT c.name AS "Film Category", AVG(f.rental_duration) AS "Average Rental Duration"
FROM film AS f
JOIN film_category AS fc
ON f.film_id = fc.film_id
JOIN category AS c
ON c.category_id = fc.category_id
GROUP BY c.name
ORDER BY "Average Rental Duration" DESC


-- 3. Find the number of rentals made each month.
SELECT TO_CHAR(rental_date,'YYYY-MM') AS "Month", COUNT(*) AS "No. of Rentals"
FROM rental
GROUP BY "Month"
ORDER BY "Month" desc

-- 4. Find categories with more than 50 films (use HAVING).
SELECT c.name AS "Category", COUNT(fc.film_id) AS "No. of Films"
FROM category c
JOIN film_category fc ON c.category_id = fc.category_id
GROUP BY c.name
HAVING COUNT(fc.film_id) > 50
ORDER BY "No. of Films" DESC

-- Part 2 — Subquery Challenges
-- 5. Find customers who spent more than the average customer spend.
SELECT customer_id, total_spent
FROM (
  	SELECT customer_id, SUM(amount) AS total_spent
    FROM payment
    GROUP BY customer_id ) 	
AS customer_totals
WHERE total_spent > (
    SELECT AVG(total_spent)
    FROM (
        SELECT SUM(amount) AS total_spent
        FROM payment
        GROUP BY customer_id
    ) AS avg_calc
)
ORDER BY total_spent DESC;

-- 6. Find the film(s) with the highest rental rate in each category (use a correlated subquery).
SELECT c.name AS category, f.title, f.rental_rate
FROM film f
JOIN film_category fc 
ON f.film_id = fc.film_id
JOIN category c 
ON fc.category_id = c.category_id
WHERE f.rental_rate = (
    SELECT MAX(f2.rental_rate)
    FROM film f2
    JOIN film_category fc2 ON f2.film_id = fc2.film_id
    WHERE fc2.category_id = fc.category_id  
)
ORDER BY c.name, f.title;

-- 7. Find customers who have never rented a film (use NOT IN / NOT EXISTS).
SELECT cu.customer_id, cu.first_name, cu.last_name
FROM customer AS cu
WHERE NOT EXISTS (
    SELECT 1
    FROM rental r
    WHERE r.customer_id = cu.customer_id
);

-- 8. Find the store with the highest total revenue using a subquery in the WHERE clause.
SELECT * FROM
(
    SELECT s.store_id, SUM(p.amount) AS revenue
    FROM payment p
    JOIN staff st
    ON p.staff_id = st.staff_id
    JOIN store s
    ON st.staff_id = s.manager_staff_id
    GROUP BY s.store_id
)
WHERE revenue =
(
    SELECT MAX(revenue)
    FROM
    (
        SELECT SUM(p.amount) AS revenue
        FROM payment p
        JOIN staff st
        ON p.staff_id = st.staff_id
        JOIN store s
        ON st.staff_id = s.manager_staff_id
        GROUP BY s.store_id
    )
);

-- Part 3 — CTE & Window Function Challenges
-- 9. Using a CTE, rank customers by total spend within each city.
-- 10. Using ROW_NUMBER(), find the most recently rented film for each customer.
-- 11. Using a CTE, calculate month-over-month rental revenue growth.
-- 12. Find the top 3 highest-grossing films per category using RANK() inside a CTE.
-- Bonus Challenge
-- Without looking at any online solution, write a single query (using CTEs) that finds: Which staff member processed the highest revenue in each store, and what percentage of that store's total revenue did they contribute? This requires combining aggregation, a CTE, and a percentage calculation in the same query.