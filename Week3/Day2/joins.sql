-- query to check PK and FK

SELECT
    tc.table_name,
    kcu.column_name,
    tc.constraint_type
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
AND tc.table_schema = 'public'
AND tc.table_name NOT LIKE 'pg_%'
ORDER BY tc.table_name;

-- 1.Display Customer Name, Email, City, and Country.

SELECT CONCAT(c.first_name , ' ', c.last_name) AS "Customer Name", c.email AS "Email", ci.city AS "City", co.country AS "Country"
FROM customer c
JOIN address AS a
ON c.address_id = a.address_id
JOIN city AS ci
ON a.city_id = ci.city_id
JOIN country AS co
ON ci.country_id = co.country_id


-- 2 and 3.Display every payment with Customer Name, Film Title, and Amount Paid.

SELECT CONCAT(c.first_name , ' ', c.last_name) AS "Customer Name", f.title AS "Film Title", p.amount AS "Amount Paid"
FROM payment p
JOIN customer AS c
ON p.customer_id = c.customer_id
JOIN rental AS r
ON p.rental_id = r.rental_id
JOIN inventory as i
ON r.inventory_id = i.inventory_id
JOIN film AS f
ON i.film_id = f.film_id


-- 4.Find the Top 10 customers based on total amount spent.

SELECT  CONCAT(c.first_name , ' ', c.last_name) AS "Customer Name", SUM(p.amount) AS "Total Amount Spent"
FROM customer c
INNER JOIN payment p 
ON c.customer_id = p.customer_id
GROUP BY c.customer_id, "Customer Name"
ORDER BY "Total Amount Spent" DESC
LIMIT 10;


-- 5.Display each film with its Category and Rental Rate.

SELECT f.title AS "Title", c.name AS "Category", f.rental_rate AS "Rental Rate"
FROM film f
INNER JOIN film_category fc 
ON f.film_id = fc.film_id
INNER JOIN category c
ON fc.category_id = c.category_id
ORDER BY f.title


-- 6.Find all actors who appeared in each film.

SELECT CONCAT(a.first_name , ' ', a.last_name) AS "Actor", f.title AS "Film Title"
FROM film f
INNER JOIN film_actor AS fa
    ON f.film_id = fa.film_id
INNER JOIN actor AS a
    ON fa.actor_id = a.actor_id
ORDER BY
    f.title, "Actor";

-- 7.Count how many films belong to each category.

SELECT c.name AS "Category", COUNT(fc.film_id) AS "Total Films"
FROM category c
INNER JOIN film_category AS fc
ON c.category_id = fc.category_id
GROUP BY c.category_id, c.name
ORDER BY "Total Films" DESC;


-- 8.Which categories generated the highest revenue? (Hint: This requires joining multiple tables.)

SELECT c.name AS "Category", SUM(p.amount) AS "Total Revenue"
FROM payment p
INNER JOIN rental r 
ON p.rental_id = r.rental_id
INNER JOIN inventory i 
ON r.inventory_id = i.inventory_id
INNER JOIN film_category fc 
ON i.film_id = fc.film_id
INNER JOIN category c 
ON fc.category_id = c.category_id
GROUP BY c.name
ORDER BY "Total Revenue" DESC;


-- 9.Find customers who have rented more than 20 films.

SELECT CONCAT(c.first_name , ' ', c.last_name) AS "Customer Name", COUNT(r.rental_id) AS "Films Rented"
FROM customer AS c
INNER JOIN rental r ON c.customer_id = r.customer_id
GROUP BY c.customer_id, "Customer Name"
HAVING COUNT(r.rental_id) > 20
ORDER BY "Films Rented" DESC;


-- 10.Which cities generated the highest rental revenue?

SELECT ci.city AS "City", SUM(p.amount) AS "Total Revenue"
FROM payment AS p
INNER JOIN customer c ON p.customer_id = c.customer_id
INNER JOIN address a ON c.address_id = a.address_id
INNER JOIN city ci ON a.city_id = ci.city_id
GROUP BY ci.city
ORDER BY "Total Revenue" DESC
LIMIT 10;

-- Bonus Challenge: Which actor has generated the highest total rental revenue?
SELECT CONCAT(a.first_name , ' ', a.last_name) AS "Actor",  SUM(p.amount) AS "Total Revenue"
FROM actor AS a
INNER JOIN
film_actor AS fa 
ON a.actor_id = fa.actor_id
INNER JOIN film AS f 
ON fa.film_id = f.film_id
INNER JOIN inventory AS i 
ON f.film_id = i.film_id
INNER JOIN rental AS r 
ON i.inventory_id = r.inventory_id
INNER JOIN payment AS p 
ON r.rental_id = p.rental_id
GROUP BY a.actor_id, "Actor"
ORDER BY "Total Revenue" DESC