-- Check the db
SELECT 'sales.salesorderheader' AS tbl, COUNT(*) FROM sales.salesorderheader
UNION ALL SELECT 'sales.salesorderdetail', COUNT(*) FROM sales.salesorderdetail
UNION ALL SELECT 'sales.customer', COUNT(*) FROM sales.customer
UNION ALL SELECT 'sales.salesperson', COUNT(*) FROM sales.salesperson
UNION ALL SELECT 'sales.salesterritory', COUNT(*) FROM sales.salesterritory
UNION ALL SELECT 'sales.store', COUNT(*) FROM sales.store
UNION ALL SELECT 'production.product', COUNT(*) FROM production.product
UNION ALL SELECT 'production.productinventory', COUNT(*) FROM production.productinventory
UNION ALL SELECT 'humanresources.employee', COUNT(*) FROM humanresources.employee
UNION ALL SELECT 'purchasing.vendor', COUNT(*) FROM purchasing.vendor
UNION ALL SELECT 'purchasing.purchaseorderheader', COUNT(*) FROM purchasing.purchaseorderheader
UNION ALL SELECT 'purchasing.purchaseorderdetail', COUNT(*) FROM purchasing.purchaseorderdetail;

SELECT table_schema, COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema IN ('person','humanresources','production','purchasing','sales')
GROUP BY table_schema
ORDER BY table_schema;

-----------------------------------
-- ANALYTICS PIPELINE

-- ------------------------------------------------------------
-- STAGE 0: Schema setup
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS kpi;

-- ------------------------------------------------------------
-- STAGE 1: Domain analytics tables
-- ------------------------------------------------------------
 
-- 1. date_analytics
DROP VIEW IF EXISTS analytics.date_analytics CASCADE;
CREATE VIEW analytics.date_analytics AS
WITH bounds AS (
    SELECT MIN(orderdate)::date AS min_d, MAX(orderdate)::date AS max_d
    FROM sales.salesorderheader
    UNION ALL
    SELECT MIN(orderdate)::date, MAX(orderdate)::date
    FROM purchasing.purchaseorderheader
),
date_range AS (
    SELECT MIN(min_d) AS min_date, MAX(max_d) AS max_date FROM bounds
),
calendar AS (
    SELECT generate_series(min_date, max_date, interval '1 day')::date AS date_key
    FROM date_range
)
SELECT
    date_key,
    EXTRACT(YEAR FROM date_key)::int AS year,
    EXTRACT(QUARTER FROM date_key)::int AS quarter,
    EXTRACT(MONTH FROM date_key)::int AS month,
    TRIM(TO_CHAR(date_key, 'Month')) AS month_name,
    TRIM(TO_CHAR(date_key, 'Day')) AS day_name,
    EXTRACT(ISODOW FROM date_key)::int AS day_of_week,
    (EXTRACT(ISODOW FROM date_key) IN (6,7)) AS is_weekend,
    CASE WHEN EXTRACT(MONTH FROM date_key) >= 7
         THEN EXTRACT(YEAR FROM date_key)::int + 1
         ELSE EXTRACT(YEAR FROM date_key)::int
    END AS fiscal_year
FROM calendar;
 
-- 2. product_analytics
DROP VIEW IF EXISTS analytics.product_analytics CASCADE;
CREATE VIEW analytics.product_analytics AS
SELECT
    p.productid,
    p.name AS product_name,
    p.productnumber,
    p.color,
    p.size,
    p.standardcost,
    p.listprice,
    (p.listprice - p.standardcost) AS margin,
    CASE WHEN p.listprice > 0
         THEN ROUND((((p.listprice - p.standardcost) / p.listprice) * 100)::numeric, 2)
         ELSE NULL END AS margin_pct,
    p.safetystocklevel,
    p.reorderpoint,
    psc.name AS subcategory_name,
    pc.name AS category_name,
    p.sellstartdate,
    p.sellenddate,
    p.discontinueddate,
    COALESCE(inv.total_qty, 0) AS total_inventory_qty
FROM production.product p
LEFT JOIN production.productsubcategory psc ON p.productsubcategoryid = psc.productsubcategoryid
LEFT JOIN production.productcategory pc ON psc.productcategoryid = pc.productcategoryid
LEFT JOIN (
    SELECT productid, SUM(quantity) AS total_qty
    FROM production.productinventory
    GROUP BY productid
) inv ON p.productid = inv.productid;
 
-- 3. territory_analytics
DROP VIEW IF EXISTS analytics.territory_analytics CASCADE;
CREATE VIEW analytics.territory_analytics AS
SELECT
    st.territoryid,
    st.name AS territory_name,
    st.countryregioncode,
    cr.name AS country_name,
    st."group" AS territory_group,
    st.salesytd,
    st.saleslastyear,
    st.costytd,
    st.costlastyear,
    sth.businessentityid AS current_salesperson_id,
    (SELECT COUNT(*) FROM person.stateprovince sp WHERE sp.territoryid = st.territoryid) AS state_count
FROM sales.salesterritory st
LEFT JOIN person.countryregion cr ON st.countryregioncode = cr.countryregioncode
LEFT JOIN LATERAL (
    SELECT sth.businessentityid
    FROM sales.salesterritoryhistory sth
    WHERE sth.territoryid = st.territoryid AND sth.enddate IS NULL
    ORDER BY sth.startdate DESC, sth.businessentityid
    LIMIT 1
) sth ON true;
 
-- 4. vendor_analytics
DROP VIEW IF EXISTS analytics.vendor_analytics CASCADE;
CREATE VIEW analytics.vendor_analytics AS
SELECT
    v.businessentityid AS vendor_id,
    v.name AS vendor_name,
    v.creditrating,
    v.preferredvendorstatus,
    v.activeflag,
    COUNT(DISTINCT pv.productid) AS products_supplied,
    ROUND(AVG(pv.averageleadtime)::numeric, 1) AS avg_lead_time_days,
    ROUND(AVG(pv.standardprice)::numeric, 2) AS avg_standard_price
FROM purchasing.vendor v
LEFT JOIN purchasing.productvendor pv ON v.businessentityid = pv.businessentityid
GROUP BY v.businessentityid, v.name, v.creditrating, v.preferredvendorstatus, v.activeflag;
 
-- 5. employee_analytics
DROP VIEW IF EXISTS analytics.employee_analytics CASCADE;
CREATE VIEW analytics.employee_analytics AS
SELECT
    e.businessentityid AS employee_id,
    p.firstname || ' ' || p.lastname AS employee_name,
    e.jobtitle,
    e.hiredate,
    EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hiredate))::int AS tenure_years,
    e.gender,
    e.salariedflag,
    d.name AS department_name,
    d.groupname AS department_group,
    (sp.businessentityid IS NOT NULL) AS is_salesperson,
    sp.territoryid,
    sp.salesquota,
    sp.salesytd,
    sp.saleslastyear
FROM humanresources.employee e
LEFT JOIN person.person p ON e.businessentityid = p.businessentityid
LEFT JOIN humanresources.employeedepartmenthistory edh
    ON e.businessentityid = edh.businessentityid AND edh.enddate IS NULL
LEFT JOIN humanresources.department d ON edh.departmentid = d.departmentid
LEFT JOIN sales.salesperson sp ON e.businessentityid = sp.businessentityid;
 
-- 6. customer_analytics
DROP VIEW IF EXISTS analytics.customer_analytics CASCADE;
CREATE VIEW analytics.customer_analytics AS
SELECT
    c.customerid,
    CASE WHEN c.personid IS NOT NULL THEN 'Individual' ELSE 'Store' END AS customer_type,
    COALESCE(p.firstname || ' ' || p.lastname, s.name) AS customer_name,
    c.territoryid,
    ta.territory_name,
    ta.territory_group,
    ta.country_name
FROM sales.customer c
LEFT JOIN person.person p ON c.personid = p.businessentityid
LEFT JOIN sales.store s ON c.storeid = s.businessentityid
LEFT JOIN analytics.territory_analytics ta ON c.territoryid = ta.territoryid;
 
-- 7. sales_analytics
DROP VIEW IF EXISTS analytics.sales_analytics CASCADE;
CREATE VIEW analytics.sales_analytics AS
SELECT
    sod.salesorderid,
    sod.salesorderdetailid,
    soh.orderdate,
    soh.customerid,
    soh.salespersonid,
    soh.territoryid,
    soh.status,
    sod.productid,
    sod.orderqty,
    sod.unitprice,
    sod.unitpricediscount,
    ROUND((sod.unitprice * (1 - sod.unitpricediscount) * sod.orderqty)::numeric, 2) AS line_total,
    ROUND((sod.orderqty * COALESCE(pch.standardcost, p.standardcost))::numeric, 2) AS line_cost,
    ROUND(
        ((sod.unitprice * (1 - sod.unitpricediscount) * sod.orderqty)
         - (sod.orderqty * COALESCE(pch.standardcost, p.standardcost)))::numeric, 2
    ) AS line_profit
FROM sales.salesorderdetail sod
JOIN sales.salesorderheader soh ON sod.salesorderid = soh.salesorderid
LEFT JOIN production.product p ON sod.productid = p.productid
LEFT JOIN production.productcosthistory pch
    ON sod.productid = pch.productid
    AND soh.orderdate BETWEEN pch.startdate AND COALESCE(pch.enddate, 'infinity'::timestamp);
 
-- 8. purchasing_analytics
DROP VIEW IF EXISTS analytics.purchasing_analytics CASCADE;
CREATE VIEW analytics.purchasing_analytics AS
SELECT
    pod.purchaseorderid,
    pod.purchaseorderdetailid,
    poh.orderdate,
    poh.shipdate,
    poh.vendorid,
    va.vendor_name,
    poh.employeeid,
    pod.productid,
    pod.orderqty,
    pod.unitprice,
    ROUND((pod.orderqty * pod.unitprice)::numeric, 2) AS line_total,
    pod.receivedqty,
    pod.rejectedqty,
    (pod.receivedqty - pod.rejectedqty) AS stocked_qty,
    (poh.shipdate::date - poh.orderdate::date) AS lead_time_days,
    CASE WHEN pod.orderqty > 0
         THEN ROUND((pod.rejectedqty / pod.orderqty)::numeric, 4)
         ELSE NULL END AS rejection_rate
FROM purchasing.purchaseorderdetail pod
JOIN purchasing.purchaseorderheader poh ON pod.purchaseorderid = poh.purchaseorderid
LEFT JOIN analytics.vendor_analytics va ON poh.vendorid = va.vendor_id;
 
-- 9. inventory_analytics
DROP VIEW IF EXISTS analytics.inventory_analytics CASCADE;
CREATE VIEW analytics.inventory_analytics AS
SELECT
    pa.productid,
    pa.product_name,
    pa.category_name,
    pa.subcategory_name,
    pa.total_inventory_qty,
    pa.safetystocklevel,
    pa.reorderpoint,
    CASE
        WHEN pa.total_inventory_qty <= pa.reorderpoint THEN 'Low Stock'
        WHEN pa.total_inventory_qty <= pa.safetystocklevel THEN 'Warning'
        ELSE 'Healthy'
    END AS stock_status
FROM analytics.product_analytics pa;
 
-- 10. geography_analytics
DROP VIEW IF EXISTS analytics.geography_analytics CASCADE;
CREATE VIEW analytics.geography_analytics AS
SELECT
    cr.countryregioncode,
    cr.name AS country_name,
    sp.stateprovinceid,
    sp.name AS state_name,
    sp.territoryid,
    COUNT(DISTINCT a.addressid) AS address_count,
    COUNT(DISTINCT a.city) AS distinct_cities
FROM person.countryregion cr
JOIN person.stateprovince sp ON cr.countryregioncode = sp.countryregioncode
LEFT JOIN person.address a ON sp.stateprovinceid = a.stateprovinceid
GROUP BY cr.countryregioncode, cr.name, sp.stateprovinceid, sp.name, sp.territoryid;
 
-- VERIFICATION: 

SELECT 'date_analytics' Analytics, COUNT(*) FROM analytics.date_analytics
UNION ALL SELECT 'product_analytics', COUNT(*) FROM analytics.product_analytics
UNION ALL SELECT 'territory_analytics', COUNT(*) FROM analytics.territory_analytics
UNION ALL SELECT 'vendor_analytics', COUNT(*) FROM analytics.vendor_analytics
UNION ALL SELECT 'employee_analytics', COUNT(*) FROM analytics.employee_analytics
UNION ALL SELECT 'customer_analytics', COUNT(*) FROM analytics.customer_analytics
UNION ALL SELECT 'sales_analytics', COUNT(*) FROM analytics.sales_analytics
UNION ALL SELECT 'purchasing_analytics', COUNT(*) FROM analytics.purchasing_analytics
UNION ALL SELECT 'inventory_analytics', COUNT(*) FROM analytics.inventory_analytics
UNION ALL SELECT 'geography_analytics', COUNT(*) FROM analytics.geography_analytics;

-- CHECKING SALES ANALYTICS
SELECT * FROM analytics.sales_analytics ORDER BY orderdate DESC LIMIT 10;

-- Customer analytics: Individual vs store customer split
SELECT customer_type, COUNT(*) AS customer_count
FROM analytics.customer_analytics
GROUP BY customer_type;


-- ============================================================
-- STAGE 2: Business metric views (Task 3)
-- this reads only from analytics.* (Stage 1), not from raw stuff
-- Three base summaries (the views: product_sales_summary,
-- salesperson_sales_summary, territory_sales_summary) are reused by
-- several named views below 
--

-- ===== SALES =====
--monthly revenue
DROP VIEW IF EXISTS kpi.monthly_revenue CASCADE;
CREATE VIEW kpi.monthly_revenue AS
SELECT
    da.year,
    da.month,
    da.month_name,
    COUNT(DISTINCT sa.salesorderid) AS order_count,
    SUM(sa.line_total) AS total_revenue,
    SUM(sa.line_cost) AS total_cost,
    SUM(sa.line_profit) AS total_profit
FROM analytics.sales_analytics sa
JOIN analytics.date_analytics da ON sa.orderdate::date = da.date_key
GROUP BY da.year, da.month, da.month_name
ORDER BY da.year, da.month;

-- quarterly revenue
DROP VIEW IF EXISTS kpi.quarterly_revenue CASCADE;
CREATE VIEW kpi.quarterly_revenue AS
SELECT
    da.year,
    da.quarter,
    COUNT(DISTINCT sa.salesorderid) AS order_count,
    SUM(sa.line_total) AS total_revenue,
    SUM(sa.line_cost) AS total_cost,
    SUM(sa.line_profit) AS total_profit
FROM analytics.sales_analytics sa
JOIN analytics.date_analytics da ON sa.orderdate::date = da.date_key
GROUP BY da.year, da.quarter
ORDER BY da.year, da.quarter;

-- sales growth 
DROP VIEW IF EXISTS kpi.sales_growth CASCADE;
CREATE VIEW kpi.sales_growth AS
SELECT
    year,
    month,
    month_name,
    total_revenue,
    LAG(total_revenue) OVER (ORDER BY year, month) AS prev_month_revenue,
    ROUND(
        ((total_revenue - LAG(total_revenue) OVER (ORDER BY year, month))
         / NULLIF(LAG(total_revenue) OVER (ORDER BY year, month), 0)) * 100, 2
    ) AS mom_growth_pct
FROM kpi.monthly_revenue;
 
-- Base aggregation reused by best_selling_products, lowest_performing_products,
-- product_rankings, product_profitability, category_performance

--product sales summary
DROP VIEW IF EXISTS kpi.product_sales_summary CASCADE;
CREATE VIEW kpi.product_sales_summary AS
SELECT
    pa.productid,
    pa.product_name,
    pa.category_name,
    pa.subcategory_name,
    pa.standardcost,
    pa.listprice,
    COALESCE(SUM(sa.orderqty), 0) AS total_qty_sold,
    COALESCE(SUM(sa.line_total), 0) AS total_revenue,
    COALESCE(SUM(sa.line_cost), 0) AS total_cost,
    COALESCE(SUM(sa.line_profit), 0) AS total_profit,
    (COALESCE(SUM(sa.orderqty), 0) = 0) AS never_sold,
    RANK() OVER (ORDER BY COALESCE(SUM(sa.line_total), 0) DESC) AS revenue_rank
FROM analytics.product_analytics pa
LEFT JOIN analytics.sales_analytics sa ON pa.productid = sa.productid
GROUP BY pa.productid, pa.product_name, pa.category_name, pa.subcategory_name, pa.standardcost, pa.listprice;

 --best selling products
DROP VIEW IF EXISTS kpi.best_selling_products CASCADE;
CREATE VIEW kpi.best_selling_products AS
SELECT productid, product_name, category_name, total_qty_sold, total_revenue, revenue_rank
FROM kpi.product_sales_summary
ORDER BY revenue_rank
LIMIT 10;

-- lowest performing products 
DROP VIEW IF EXISTS kpi.lowest_performing_products CASCADE;
CREATE VIEW kpi.lowest_performing_products AS
SELECT productid, product_name, category_name, total_qty_sold, total_revenue, revenue_rank
FROM kpi.product_sales_summary
WHERE NOT never_sold
ORDER BY revenue_rank DESC
LIMIT 10;
 
-- ===== MORE OF PRODUCTS =====

--product rankings
DROP VIEW IF EXISTS kpi.product_rankings CASCADE;
CREATE VIEW kpi.product_rankings AS
SELECT productid, product_name, category_name, total_revenue, total_qty_sold, revenue_rank
FROM kpi.product_sales_summary
ORDER BY revenue_rank;

-- profitable products
DROP VIEW IF EXISTS kpi.product_profitability CASCADE;
CREATE VIEW kpi.product_profitability AS
SELECT
    productid, product_name, category_name, subcategory_name,
    total_revenue, total_cost, total_profit,
    CASE WHEN total_revenue > 0 THEN ROUND((total_profit / total_revenue) * 100, 2) ELSE NULL END AS profit_margin_pct
FROM kpi.product_sales_summary
ORDER BY total_profit DESC;

--performance of each category
DROP VIEW IF EXISTS kpi.category_performance CASCADE;
CREATE VIEW kpi.category_performance AS
SELECT
    category_name,
    COUNT(DISTINCT productid) AS product_count,
    SUM(total_qty_sold) AS total_qty_sold,
    SUM(total_revenue) AS total_revenue,
    SUM(total_profit) AS total_profit,
    ROUND(AVG(CASE WHEN total_revenue > 0 THEN (total_profit / total_revenue) * 100 END), 2) AS avg_margin_pct,
    CASE
        WHEN SUM(total_revenue) >= 1000000 THEN 'High'
        WHEN SUM(total_revenue) >= 100000 THEN 'Medium'
        ELSE 'Low'
    END AS revenue_tier
FROM kpi.product_sales_summary
GROUP BY category_name
ORDER BY total_revenue DESC;
 
-- ===== EMPLOYEES =====
 --summary of sales of sales person
DROP VIEW IF EXISTS kpi.salesperson_sales_summary CASCADE;
CREATE VIEW kpi.salesperson_sales_summary AS
SELECT
    ea.employee_id,
    ea.employee_name,
    ea.territoryid,
    ea.salesquota,
    ea.salesytd,
    ea.saleslastyear,
    COALESCE(SUM(sa.line_total), 0) AS total_revenue,
    COALESCE(SUM(sa.line_profit), 0) AS total_profit,
    COUNT(DISTINCT sa.salesorderid) AS total_orders,
    RANK() OVER (ORDER BY COALESCE(SUM(sa.line_total), 0) DESC) AS revenue_rank
FROM analytics.employee_analytics ea
LEFT JOIN analytics.sales_analytics sa ON ea.employee_id = sa.salespersonid
WHERE ea.is_salesperson = true
GROUP BY ea.employee_id, ea.employee_name, ea.territoryid, ea.salesquota, ea.salesytd, ea.saleslastyear;

-- rankings of sales person
DROP VIEW IF EXISTS kpi.salesperson_rankings CASCADE;
CREATE VIEW kpi.salesperson_rankings AS
SELECT employee_id, employee_name, total_revenue, total_orders, revenue_rank
FROM kpi.salesperson_sales_summary
ORDER BY revenue_rank;

--contribution to revenue by employees
DROP VIEW IF EXISTS kpi.revenue_contribution CASCADE;
CREATE VIEW kpi.revenue_contribution AS
SELECT
    employee_id, employee_name, total_revenue,
    ROUND((total_revenue / NULLIF(SUM(total_revenue) OVER (), 0)) * 100, 2) AS pct_of_total_revenue
FROM kpi.salesperson_sales_summary
ORDER BY pct_of_total_revenue DESC;

 --comparing performance
DROP VIEW IF EXISTS kpi.performance_comparison CASCADE;
CREATE VIEW kpi.performance_comparison AS
SELECT
    employee_id, employee_name, salesquota, total_revenue,
    CASE
        WHEN salesquota IS NULL THEN 'No Quota Set'
        WHEN total_revenue >= salesquota THEN 'Above Quota'
        WHEN total_revenue >= salesquota * 0.8 THEN 'Near Quota'
        ELSE 'Below Quota'
    END AS quota_status
FROM kpi.salesperson_sales_summary;

 
-- ===== TERRITORIES =====
 -- sales summary of territories
DROP VIEW IF EXISTS kpi.territory_sales_summary CASCADE;
CREATE VIEW kpi.territory_sales_summary AS
SELECT
    ta.territoryid,
    ta.territory_name,
    ta.territory_group,
    ta.country_name,
    da.year,
    COALESCE(SUM(sa.line_total), 0) AS total_revenue,
    COALESCE(SUM(sa.line_profit), 0) AS total_profit,
    COUNT(DISTINCT sa.salesorderid) AS total_orders
FROM analytics.territory_analytics ta
LEFT JOIN analytics.sales_analytics sa ON ta.territoryid = sa.territoryid
LEFT JOIN analytics.date_analytics da ON sa.orderdate::date = da.date_key
GROUP BY ta.territoryid, ta.territory_name, ta.territory_group, ta.country_name, da.year;

-- revenue of regions
DROP VIEW IF EXISTS kpi.regional_revenue CASCADE;
CREATE VIEW kpi.regional_revenue AS
SELECT territoryid, territory_name, territory_group, country_name, year, total_revenue, total_orders
FROM kpi.territory_sales_summary
WHERE year IS NOT NULL
ORDER BY year, total_revenue DESC;

--growth of regions
DROP VIEW IF EXISTS kpi.regional_growth CASCADE;
CREATE VIEW kpi.regional_growth AS
SELECT
    territoryid, territory_name, year, total_revenue,
    LAG(total_revenue) OVER (PARTITION BY territoryid ORDER BY year) AS prev_year_revenue,
    ROUND(
        ((total_revenue - LAG(total_revenue) OVER (PARTITION BY territoryid ORDER BY year))
         / NULLIF(LAG(total_revenue) OVER (PARTITION BY territoryid ORDER BY year), 0)) * 100, 2
    ) AS yoy_growth_pct
FROM kpi.territory_sales_summary
WHERE year IS NOT NULL
ORDER BY territoryid, year;


-- top territores 
DROP VIEW IF EXISTS kpi.top_territories CASCADE;
CREATE VIEW kpi.top_territories AS
SELECT territoryid, territory_name, territory_group, SUM(total_revenue) AS lifetime_revenue,
       RANK() OVER (ORDER BY SUM(total_revenue) DESC) AS revenue_rank
FROM kpi.territory_sales_summary
GROUP BY territoryid, territory_name, territory_group
ORDER BY revenue_rank
LIMIT 5;

--lowest territories
DROP VIEW IF EXISTS kpi.lowest_territories CASCADE;
CREATE VIEW kpi.lowest_territories AS
SELECT territoryid, territory_name, territory_group, SUM(total_revenue) AS lifetime_revenue,
       RANK() OVER (ORDER BY SUM(total_revenue) DESC) AS revenue_rank
FROM kpi.territory_sales_summary
GROUP BY territoryid, territory_name, territory_group
ORDER BY revenue_rank DESC
LIMIT 5;
 
-- ===== CUSTOMERS =====

--metrics of customers
DROP VIEW IF EXISTS kpi.customer_metrics CASCADE;
CREATE VIEW kpi.customer_metrics AS
SELECT
    ca.customerid,
    ca.customer_type,
    ca.customer_name,
    ca.territory_name,
    COUNT(DISTINCT sa.salesorderid) AS order_count,
    COALESCE(SUM(sa.line_total), 0) AS total_spent,
    MIN(sa.orderdate) AS first_order_date,
    MAX(sa.orderdate) AS last_order_date,
    CASE WHEN MAX(sa.orderdate) IS NOT NULL
         THEN (CURRENT_DATE - MAX(sa.orderdate)::date)
         ELSE NULL END AS days_since_last_order
FROM analytics.customer_analytics ca
LEFT JOIN analytics.sales_analytics sa ON ca.customerid = sa.customerid
GROUP BY ca.customerid, ca.customer_type, ca.customer_name, ca.territory_name;

 --customer segmentss
DROP VIEW IF EXISTS kpi.customer_segments CASCADE;
CREATE VIEW kpi.customer_segments AS
SELECT
    customerid, customer_name, order_count, total_spent, days_since_last_order,
    CASE
        WHEN order_count = 0 THEN 'Never Purchased'
        WHEN order_count >= 5 AND total_spent > (SELECT AVG(total_spent) FROM kpi.customer_metrics) THEN 'VIP'
        WHEN order_count >= 2 THEN 'Repeat'
        ELSE 'One-Time'
    END AS segment
FROM kpi.customer_metrics;

-- customer lifetime value
DROP VIEW IF EXISTS kpi.customer_ltv CASCADE;
CREATE VIEW kpi.customer_ltv AS
SELECT
    customerid, customer_name, total_spent AS lifetime_value, order_count,
    CASE WHEN order_count > 0 THEN ROUND(total_spent / order_count, 2) ELSE 0 END AS avg_order_value
FROM kpi.customer_metrics
ORDER BY lifetime_value DESC;

--repeat customers
DROP VIEW IF EXISTS kpi.repeat_customers CASCADE;
CREATE VIEW kpi.repeat_customers AS
SELECT customerid, customer_name, order_count, total_spent
FROM kpi.customer_metrics
WHERE order_count > 1
ORDER BY order_count DESC;

--customers retained
DROP VIEW IF EXISTS kpi.customer_retention CASCADE;
CREATE VIEW kpi.customer_retention AS
WITH customer_years AS (
    SELECT sa.customerid, da.year
    FROM analytics.sales_analytics sa
    JOIN analytics.date_analytics da ON sa.orderdate::date = da.date_key
    GROUP BY sa.customerid, da.year
),
customer_year_count AS (
    SELECT customerid, COUNT(DISTINCT year) AS active_years
    FROM customer_years
    GROUP BY customerid
)
SELECT
    active_years,
    COUNT(*) AS customer_count,
    ROUND((COUNT(*)::numeric / SUM(COUNT(*)) OVER ()) * 100, 2) AS pct_of_customers
FROM customer_year_count
GROUP BY active_years
ORDER BY active_years;
 
-- ===== INVENTORY / PURCHASING =====

-- inventory health
DROP VIEW IF EXISTS kpi.inventory_health CASCADE;
CREATE VIEW kpi.inventory_health AS
SELECT
    category_name,
    COUNT(*) AS product_count,
    SUM(CASE WHEN stock_status = 'Low Stock' THEN 1 ELSE 0 END) AS low_stock_count,
    SUM(CASE WHEN stock_status = 'Warning' THEN 1 ELSE 0 END) AS warning_count,
    SUM(CASE WHEN stock_status = 'Healthy' THEN 1 ELSE 0 END) AS healthy_count,
    SUM(total_inventory_qty) AS total_units_on_hand
FROM analytics.inventory_analytics
GROUP BY category_name
ORDER BY low_stock_count DESC;

--low stock procducts
DROP VIEW IF EXISTS kpi.low_stock_products CASCADE;
CREATE VIEW kpi.low_stock_products AS
SELECT productid, product_name, category_name, total_inventory_qty, reorderpoint, stock_status
FROM analytics.inventory_analytics
WHERE stock_status IN ('Low Stock', 'Warning')
ORDER BY total_inventory_qty ASC;

-- supplier's performance
DROP VIEW IF EXISTS kpi.supplier_performance CASCADE;
CREATE VIEW kpi.supplier_performance AS
SELECT
    pa.vendorid,
    pa.vendor_name,
    COUNT(DISTINCT pa.purchaseorderid) AS total_orders,
    SUM(pa.line_total) AS total_spend,
    ROUND(AVG(pa.lead_time_days), 1) AS avg_lead_time_days,
    ROUND(AVG(pa.rejection_rate) * 100, 2) AS avg_rejection_rate_pct
FROM analytics.purchasing_analytics pa
GROUP BY pa.vendorid, pa.vendor_name
ORDER BY total_spend DESC;

--purchasing trends
DROP VIEW IF EXISTS kpi.purchasing_trends CASCADE;
CREATE VIEW kpi.purchasing_trends AS
SELECT
    da.year, da.month, da.month_name,
    COUNT(DISTINCT pa.purchaseorderid) AS order_count,
    SUM(pa.line_total) AS total_spend
FROM analytics.purchasing_analytics pa
JOIN analytics.date_analytics da ON pa.orderdate::date = da.date_key
GROUP BY da.year, da.month, da.month_name
ORDER BY da.year, da.month;
 
-- VERIFICATION

SELECT 'monthly_revenue' KPIs, COUNT(*) FROM kpi.monthly_revenue
UNION ALL SELECT 'quarterly_revenue', COUNT(*) FROM kpi.quarterly_revenue
UNION ALL SELECT 'sales_growth', COUNT(*) FROM kpi.sales_growth
UNION ALL SELECT 'product_sales_summary', COUNT(*) FROM kpi.product_sales_summary
UNION ALL SELECT 'best_selling_products', COUNT(*) FROM kpi.best_selling_products
UNION ALL SELECT 'lowest_performing_products', COUNT(*) FROM kpi.lowest_performing_products
UNION ALL SELECT 'product_rankings', COUNT(*) FROM kpi.product_rankings
UNION ALL SELECT 'product_profitability', COUNT(*) FROM kpi.product_profitability
UNION ALL SELECT 'category_performance', COUNT(*) FROM kpi.category_performance
UNION ALL SELECT 'salesperson_sales_summary', COUNT(*) FROM kpi.salesperson_sales_summary
UNION ALL SELECT 'salesperson_rankings', COUNT(*) FROM kpi.salesperson_rankings
UNION ALL SELECT 'revenue_contribution', COUNT(*) FROM kpi.revenue_contribution
UNION ALL SELECT 'performance_comparison', COUNT(*) FROM kpi.performance_comparison
UNION ALL SELECT 'territory_sales_summary', COUNT(*) FROM kpi.territory_sales_summary
UNION ALL SELECT 'regional_revenue', COUNT(*) FROM kpi.regional_revenue
UNION ALL SELECT 'regional_growth', COUNT(*) FROM kpi.regional_growth
UNION ALL SELECT 'top_territories', COUNT(*) FROM kpi.top_territories
UNION ALL SELECT 'lowest_territories', COUNT(*) FROM kpi.lowest_territories
UNION ALL SELECT 'customer_metrics', COUNT(*) FROM kpi.customer_metrics
UNION ALL SELECT 'customer_segments', COUNT(*) FROM kpi.customer_segments
UNION ALL SELECT 'customer_ltv', COUNT(*) FROM kpi.customer_ltv
UNION ALL SELECT 'repeat_customers', COUNT(*) FROM kpi.repeat_customers
UNION ALL SELECT 'customer_retention', COUNT(*) FROM kpi.customer_retention
UNION ALL SELECT 'inventory_health', COUNT(*) FROM kpi.inventory_health
UNION ALL SELECT 'low_stock_products', COUNT(*) FROM kpi.low_stock_products
UNION ALL SELECT 'supplier_performance', COUNT(*) FROM kpi.supplier_performance
UNION ALL SELECT 'purchasing_trends', COUNT(*) FROM kpi.purchasing_trends;

-- TASK 3 a: MONTHLY REVENUE's TREND
SELECT * FROM kpi.monthly_revenue ORDER BY year, month;

--TASK 3 B: BEST SELLING PRODUCTS
SELECT * FROM kpi.best_selling_products;

--TASK 3 C: CATEGORY PERFORMANCE
-- Shows conditional aggregation (avg_margin_pct) and the revenue_tier case when
SELECT * FROM kpi.category_performance;

---TASK 3 D: CUSTOMER SEGMENTS
SELECT segment, COUNT(*) AS customers
FROM kpi.customer_segments
GROUP BY segment
ORDER BY customers DESC;

-- TASK 3 E: SALESPERSON RANKINGS
-- Uses RANK() window function
SELECT * FROM kpi.salesperson_rankings;

--TASK 3 F: REGIONAL GROWTH
-- Uses LAG() window function for year over year percentage change
SELECT * FROM kpi.regional_growth ORDER BY territoryid, year;

--TASK 3 G: SUPPLIER PERFORMANCE
SELECT * FROM kpi.supplier_performance ORDER BY avg_rejection_rate_pct DESC LIMIT 10;


--   - Order history spans 2022-05-30 to 2025-06-29, so 2025 is a
--     PARTIAL year. Year-over-year comparisons with 2025 will
--     show random stuff, there wont be business trends
--   - 209 of 504 products have no category/subcategory assigned in
--     the source data (verified against production.product directly).
--   - All 701 store-type customers show zero direct orders in
--     SalesOrderHeader, while all individual customers have at least
--     one. Confirmed pattern, not a join bug.
-- ============================================================
 
-- ============================================================
-- STAGE 3: Executive KPI summary
-- goes across six stage 2 views into sing dashboard row
--for the notebook
--used lots of ctes
-- ============================================================
DROP VIEW IF EXISTS kpi.executive_summary CASCADE;
CREATE VIEW kpi.executive_summary AS
WITH revenue_summary AS (
    SELECT SUM(total_revenue) AS total_revenue, SUM(total_profit) AS total_profit, SUM(order_count) AS total_orders
    FROM kpi.monthly_revenue
),
customer_summary AS (
    SELECT COUNT(*) AS total_customers,
           COUNT(*) FILTER (WHERE order_count > 0) AS active_customers,
           COUNT(*) FILTER (WHERE order_count > 1) AS repeat_customers
    FROM kpi.customer_metrics
),
top_territory AS (
    SELECT territory_name, lifetime_revenue FROM kpi.top_territories ORDER BY revenue_rank LIMIT 1
),
top_product AS (
    SELECT product_name, total_revenue FROM kpi.best_selling_products ORDER BY revenue_rank LIMIT 1
),
top_salesperson AS (
    SELECT employee_name, total_revenue FROM kpi.salesperson_rankings ORDER BY revenue_rank LIMIT 1
),
inventory_summary AS (
    SELECT SUM(low_stock_count) AS total_low_stock, SUM(product_count) AS total_products
    FROM kpi.inventory_health
)
SELECT
    rs.total_revenue, rs.total_profit, rs.total_orders,
    cs.total_customers, cs.active_customers, cs.repeat_customers,
    tt.territory_name AS top_territory_name, tt.lifetime_revenue AS top_territory_revenue,
    tp.product_name AS top_product_name, tp.total_revenue AS top_product_revenue,
    tsp.employee_name AS top_salesperson_name, tsp.total_revenue AS top_salesperson_revenue,
    inv.total_low_stock, inv.total_products
FROM revenue_summary rs, customer_summary cs, top_territory tt, top_product tp, top_salesperson tsp, inventory_summary inv;
 
-- VERIFICATION
SELECT * FROM kpi.executive_summary;

