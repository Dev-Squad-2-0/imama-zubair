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


-- 2.Display every payment with Customer Name, Film Title, and Amount Paid.
-- 3.Display every payment with Customer Name, Film Title, and Amount Paid.
-- 4.Find the Top 10 customers based on total amount spent.
-- 5.Display each film with its Category and Rental Rate.
-- 6.Find all actors who appeared in each film.
-- 7.Count how many films belong to each category.
-- 8.Which categories generated the highest revenue? (Hint: This requires joining multiple tables.)
-- 9.Find customers who have rented more than 20 films.
-- 10.Which cities generated the highest rental revenue?