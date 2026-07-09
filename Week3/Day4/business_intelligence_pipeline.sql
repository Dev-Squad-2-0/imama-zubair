
-- FULL PIPELINE

WITH customer_invoices AS (
    -- Base: invoice-level numbers per customer (spend, invoice count, months active)
    SELECT
        c.customer_id,
        c.first_name,
        c.last_name,
        c.country,
        COUNT(DISTINCT i.invoice_id)                        AS total_invoices,
        SUM(i.total)                                        AS total_spent,
        COUNT(DISTINCT DATE_TRUNC('month', i.invoice_date)) AS purchase_months,
        ROUND(AVG(i.total), 2)                              AS avg_invoice_value
    FROM customer c
    JOIN invoice i ON i.customer_id = c.customer_id
    GROUP BY c.customer_id, c.first_name, c.last_name, c.country
),

customer_line_items AS (
    --track-level numbers per customer (tracks bought, genre & artist diversity)
    SELECT
        c.customer_id,
        COUNT(il.invoice_line_id)    AS total_tracks_purchased,
        COUNT(DISTINCT t.genre_id)   AS unique_genres,
        COUNT(DISTINCT al.artist_id) AS unique_artists
    FROM customer c
    JOIN invoice i        ON i.customer_id = c.customer_id
    JOIN invoice_line il  ON il.invoice_id = i.invoice_id
    JOIN track t          ON t.track_id = il.track_id
    LEFT JOIN album al    ON al.album_id = t.album_id
    GROUP BY c.customer_id
),

--- TASK 1: CUSTOMER SPENDING PROFILE
customer_profile AS (
    SELECT ci.customer_id,ci.first_name, ci.last_name,ci.country,ci.total_spent,ci.total_invoices,cl.total_tracks_purchased,
        cl.unique_genres,
        cl.unique_artists,
        ci.purchase_months,
        ci.avg_invoice_value
    FROM customer_invoices ci
    JOIN customer_line_items cl ON cl.customer_id = ci.customer_id
),

--- TASK 2: CUSTOMER SEGMENTATION
customer_scored AS (
    SELECT
        cp.*,
        (
            0.40 * (cp.total_spent    / NULLIF(MAX(cp.total_spent)    OVER (), 0)) +
            0.20 * (cp.total_invoices / NULLIF(MAX(cp.total_invoices) OVER (), 0)) +
            0.20 * (cp.unique_genres  / NULLIF(MAX(cp.unique_genres)  OVER (), 0)) +
            0.20 * (cp.unique_artists / NULLIF(MAX(cp.unique_artists) OVER (), 0))
        ) AS composite_score
    FROM customer_profile cp
),
customer_segments AS (
    SELECT
        cs.*,
        NTILE(4) OVER (ORDER BY cs.composite_score DESC) AS score_quartile,
        CASE NTILE(4) OVER (ORDER BY cs.composite_score DESC)
            WHEN 1 THEN 'Platinum'
            WHEN 2 THEN 'Gold'
            WHEN 3 THEN 'Silver'
            WHEN 4 THEN 'Bronze'
        END AS customer_segment
    FROM customer_scored cs
),

--- TASK 3: FAVORITE GENRE PER CUSTOMER
customer_genre_counts AS (
    SELECT c.customer_id,
        g.name            AS genre_name,
        SUM(il.quantity)  AS tracks_bought,
        ROW_NUMBER() OVER (
            PARTITION BY c.customer_id
            ORDER BY SUM(il.quantity) DESC, g.name
        ) AS genre_rank
    FROM customer c
    JOIN invoice i       ON i.customer_id = c.customer_id
    JOIN invoice_line il ON il.invoice_id = i.invoice_id
    JOIN track t         ON t.track_id = il.track_id
    JOIN genre g         ON g.genre_id = t.genre_id
    GROUP BY c.customer_id, g.name
),
customer_favorite_genre AS (
    SELECT customer_id, genre_name AS favorite_genre, tracks_bought
    FROM customer_genre_counts
    WHERE genre_rank = 1
),

customer_recommendations AS (
    SELECT cs.customer_id, cs.first_name, cs.last_name, cs.country,cs.customer_segment,cs.total_spent,cfg.favorite_genre,
        CASE
            WHEN cs.customer_segment = 'Platinum'
                THEN 'Early access to new releases'
            WHEN cs.customer_segment = 'Gold'
                THEN 'Album bundle discounts'
            WHEN cs.customer_segment = 'Silver'
                THEN 'Genre-specific discounts'
            ELSE 'First purchase coupon'
        END AS recommendation
    FROM customer_segments cs
    LEFT JOIN customer_favorite_genre cfg
        ON cs.customer_id = cfg.customer_id
),

-- TASK 4 A: COUNTRY PERFORMANCE METRICS
country_metrics AS (
    SELECT
        cp.country,
        COUNT(DISTINCT cp.customer_id)                                  AS total_customers,
        SUM(cp.total_spent)                                             AS total_revenue,
        ROUND(SUM(cp.total_spent) / COUNT(DISTINCT cp.customer_id), 2)  AS avg_revenue_per_customer,
        ROUND(AVG(cp.avg_invoice_value), 2)                             AS avg_invoice_value,
        SUM(cp.unique_genres)                                           AS total_genres_purchased
    FROM customer_profile cp
    GROUP BY cp.country
),

-- TASK 4 B: COUNTRY EXPANSION SCORE + RANK
country_normalized AS (
    SELECT
        cm.*,
        cm.avg_revenue_per_customer / NULLIF(MAX(cm.avg_revenue_per_customer) OVER (), 0) AS norm_rev_per_customer,
        cm.total_revenue            / NULLIF(MAX(cm.total_revenue) OVER (), 0)            AS norm_total_revenue,
        cm.avg_invoice_value        / NULLIF(MAX(cm.avg_invoice_value) OVER (), 0)        AS norm_avg_invoice,
        cm.total_genres_purchased   / NULLIF(MAX(cm.total_genres_purchased) OVER (), 0)   AS norm_genre_diversity
    FROM country_metrics cm
),
country_ranking AS (
    SELECT
        cn.country,
        cn.total_customers,
        cn.total_revenue,
        cn.avg_revenue_per_customer,
        cn.avg_invoice_value,
        cn.total_genres_purchased,
        ROUND(
            (cn.norm_rev_per_customer * 0.35 +
             cn.norm_total_revenue    * 0.25 +
             cn.norm_avg_invoice      * 0.20 +
             cn.norm_genre_diversity  * 0.20) * 100
        , 2) AS expansion_score,
        RANK() OVER (
            ORDER BY
                (cn.norm_rev_per_customer * 0.35 +
                 cn.norm_total_revenue    * 0.25 +
                 cn.norm_avg_invoice      * 0.20 +
                 cn.norm_genre_diversity  * 0.20) DESC
        ) AS country_rank
    FROM country_normalized cn
),

-- TASK 5 helper: TOP GENRE PER SEGMENT 
segment_genre_counts AS (
    SELECT
        cs.customer_segment,
        cfg.favorite_genre,
        COUNT(*) AS customers_who_love_it,
        RANK() OVER (
            PARTITION BY cs.customer_segment
            ORDER BY COUNT(*) DESC
        ) AS genre_rank_in_segment
    FROM customer_segments cs
    JOIN customer_favorite_genre cfg ON cfg.customer_id = cs.customer_id
    GROUP BY cs.customer_segment, cfg.favorite_genre
),
segment_top_genre AS (
    SELECT customer_segment, favorite_genre AS top_genre, customers_who_love_it
    FROM segment_genre_counts
    WHERE genre_rank_in_segment = 1
),

--  TASK 5 helper: REVENUE BY ARTIST 
artist_revenue AS (
    SELECT
        ar.artist_id,
        ar.name AS artist_name,
        SUM(il.unit_price * il.quantity) AS total_revenue,
        RANK() OVER (ORDER BY SUM(il.unit_price * il.quantity) DESC) AS artist_rank
    FROM artist ar
    JOIN album al        ON al.artist_id = ar.artist_id
    JOIN track t         ON t.album_id = al.album_id
    JOIN invoice_line il ON il.track_id = t.track_id
    GROUP BY ar.artist_id, ar.name
),

-- TASK 5 helper: REVENUE BY ALBUM 
album_revenue AS (
    SELECT
        al.album_id,
        al.title AS album_title,
        ar.name  AS artist_name,
        SUM(il.unit_price * il.quantity) AS total_revenue,
        RANK() OVER (ORDER BY SUM(il.unit_price * il.quantity) DESC) AS album_rank
    FROM album al
    JOIN artist ar        ON ar.artist_id = al.artist_id
    JOIN track t          ON t.album_id = al.album_id
    JOIN invoice_line il  ON il.track_id = t.track_id
    GROUP BY al.album_id, al.title, ar.name
),

-- TASK 5 helper: REVENUE BY EMPLOYEE

employee_revenue AS (
    SELECT
        e.employee_id,
        e.first_name || ' ' || e.last_name AS employee_name,
        e.title,
        COUNT(DISTINCT c.customer_id)      AS customers_supported,
        SUM(i.total)                        AS total_revenue,
        RANK() OVER (ORDER BY SUM(i.total) DESC) AS employee_rank
    FROM employee e
    JOIN customer c ON c.support_rep_id = e.employee_id
    JOIN invoice  i ON i.customer_id    = c.customer_id
    GROUP BY e.employee_id, e.first_name, e.last_name, e.title
)

-- TASKS AND THEIR OVERALL STUFF
-- 1. Customer Profile  
-- SELECT * FROM customer_profile
-- ORDER BY total_spent DESC;

-- 2. Customer Segements
-- SELECT * FROM customer_segments
-- ORDER BY composite_score DESC;

-- 3. Personalized Marketing Recommendations  +Customer segmentation results
-- SELECT * FROM customer_recommendations
-- ORDER BY customer_id, customer_segment, total_spent DESC;

--4. country Expansion Strategy + Country ranking results
-- SELECT * FROM country_ranking
-- ORDER BY country_rank;


-- 5. FINAL SELECT: Executive Report
----------------------------------------------------------------------------

SELECT report_section, item, context, metric_type, metric_value
FROM (
    -- 1. Customer Segment Summary  (how many customers per tier)
    SELECT 1 AS sk, 'Segment Summary' AS report_section, customer_segment AS item,
           NULL::text AS context, 'Customers' AS metric_type,
           COUNT(*)::numeric AS metric_value, MIN(score_quartile) AS osort
    FROM customer_segments
    GROUP BY customer_segment

    UNION ALL
    -- 2. Revenue by Segment
    SELECT 2, 'Revenue by Segment', customer_segment, NULL,
           'Revenue ($)', ROUND(SUM(total_spent), 2), MIN(score_quartile)
    FROM customer_segments
    GROUP BY customer_segment

    UNION ALL
    -- 3. Top Customer in each Segment  (highest composite score in the tier)
    SELECT 3, 'Top Customer per Segment', first_name || ' ' || last_name, customer_segment,
           'Total Spent ($)', ROUND(total_spent, 2), score_quartile
    FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_segment
                                     ORDER BY composite_score DESC) AS rn
        FROM customer_segments
    ) top_cust
    WHERE rn = 1

    UNION ALL
    -- 4. Top Genre in each Segment  (reuses segment_top_genre)
    SELECT 4, 'Top Genre per Segment', top_genre, customer_segment,
           'Fans in Segment', customers_who_love_it::numeric,
           CASE customer_segment WHEN 'Platinum' THEN 1 WHEN 'Gold' THEN 2
                                 WHEN 'Silver'  THEN 3 ELSE 4 END
    FROM segment_top_genre

    UNION ALL
    -- 5. Best Performing Country  (reuses country_ranking)
    SELECT 5, 'Best Performing Country', country, 'Rank #' || country_rank,
           'Expansion Score', expansion_score, 1
    FROM country_ranking
    WHERE country_rank = 1

    UNION ALL
    -- 6. Revenue Contribution by Country  (share of total revenue; top 5 kept below)
    SELECT 6, 'Revenue by Country (Top 5)', country, NULL,
           '% of Total Revenue',
           ROUND(100 * total_revenue / SUM(total_revenue) OVER (), 1),
           RANK() OVER (ORDER BY total_revenue DESC)
    FROM country_ranking

    UNION ALL
    -- 7. Top Employee by Revenue  (reuses new employee_revenue)
    SELECT 7, 'Top Employee by Revenue', employee_name, title,
           'Revenue ($)', ROUND(total_revenue, 2), 1
    FROM employee_revenue
    WHERE employee_rank = 1

    UNION ALL
    -- 8. Top Artist by Revenue  (reuses artist_revenue)
    SELECT 8, 'Top Artist by Revenue', artist_name, NULL,
           'Revenue ($)', ROUND(total_revenue, 2), 1
    FROM artist_revenue
    WHERE artist_rank = 1

    UNION ALL
    -- 9. Top Album by Revenue  (reuses album_revenue)
    SELECT 9, 'Top Album by Revenue', album_title, artist_name,
           'Revenue ($)', ROUND(total_revenue, 2), 1
    FROM album_revenue
    WHERE album_rank = 1
) dashboard
WHERE NOT (sk = 6 AND osort > 5)          -- top 5 countries
ORDER BY sk, osort, metric_value DESC;

