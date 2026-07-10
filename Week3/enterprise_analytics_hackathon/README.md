# Enterprise Analytics Hackathon: AdventureWorks

## How to run this

1. Create an empty PostgreSQL database named `AdventureWorks`.
2. The `install.sql` was already placed in the same folder as the CSVs.
3. Open pgAdmin's PSQL Tool against the new database, point it at that folder,
   and run the install script:
   ```
   \cd 'path/to/the/csv/folder'
   \i install.sql
   ```
   This makes all 68 raw tables across the 5 AdventureWorks schemas and loads
   every CSV in one pass.
4. Then run `analytics_pipeline.sql` in a normal Query Tool tab. This builds the full
   analytics layer
5. Open `executive_analysis.ipynb`, check the connection cell matches your
   local setup, and run all cells.

---

## Database Overview

We used the AdventureWorks sample database, the same one used by Microsoft.
Its spread across `person`, `humanresources`, `production`,
`purchasing`, and `sales`.

At full scale the database has:
- 31,465 sales orders and 121,317 order lines
- 19,820 customers (19,119 individual, 701 store/B2B)
- 504 products across 4 categories
- 290 employees, 17 of them salespeople
- 104 vendors and 4,012 purchase orders

The first copy of the dataset we were given had a real problem: 13 of the CSV files (`Person`, `Store`, `BusinessEntity`, and others) used a broken multi-character delimiter (+|, &|) instead of the tab delimiter the load script expects, which meant those tables loaded empty. I then confirmed this by running the load and checking row counts, not just by reading the files. A corrected copy of the dataset fixed this, and the load now runs clean with zero errors 

---

## Analytics architecture

So I built the analytics layer in three stages, each one only reading from the stage
before it. This way we never go back to the raw tables:

**Stage 1: Domain analytics tables** (schema `analytics`)
Ten tables, each built directly from the raw schemas, one per business area. This
is the only stage that touches `person`, `humanresources`, `production`,
`purchasing`, or `sales` directly.

**Stage 2: Business metric views** (schema `kpi`)
Twenty seven views covering sales, products, employees, territories, customers,
and inventory/purchasing. Every one of these reads only from `analytics.*`,
never from the raw schemas.

**Stage 3: Executive summary** (schema `kpi`)
One view, `kpi.executive_summary`, that chains together six of the Stage 2 views
into a single dashboard-ready row: total revenue, total profit, customer counts,
top territory, top product, top salesperson, and inventory health.

This gives a clean chain: raw tables to domain tables to metrics to executive
summary to the notebook, with each stage building on the one before it instead of
recalculating anything from scratch.

---


## Intermediate tables created

**Stage 1 (analytics schema), 10 tables:**

| Table | Business domain | What it covers |
|---|---|---|
| `date_analytics` | Generated | Calendar dimension spanning the full order history, with year, quarter, month, fiscal year |
| `product_analytics` | Production | Product catalog with category, margin, and current inventory |
| `territory_analytics` | Sales | Sales territories with current salesperson and country/state rollup |
| `vendor_analytics` | Purchasing | Vendors with product count supplied and average lead time |
| `employee_analytics` | HumanResources | All employees with department, tenure, and salesperson flag |
| `customer_analytics` | Sales | Every customer, individual or store, with territory |
| `sales_analytics` | Sales | Order line grain, with margin computed using cost at time of sale |
| `purchasing_analytics` | Purchasing | Purchase order line grain, with lead time and rejection rate |
| `inventory_analytics` | Production | Current stock level against reorder point per product |
| `geography_analytics` | Person | Address, city, and state counts by country |

**Stage 2 (kpi schema), 27 views** across Sales (monthly/quarterly revenue,
growth, best/lowest sellers), Products (rankings, profitability, category
performance), Employees (rankings, revenue contribution, quota comparison),
Territories (regional revenue, growth, top/bottom), Customers (segments,
lifetime value, repeat rate, retention), and Inventory/Purchasing (stock health,
low stock, supplier performance, purchasing trends).

**Stage 3 (kpi schema), 1 view:** `kpi.executive_summary`.

---

## SQL design decisions

**Schema separation over naming convention.** We used actual PostgreSQL schemas
(`analytics`, `kpi`) rather than a naming prefix, so the separation between raw
data and the analytics layer is enforced structurally, not just by convention.

**Shared base views to avoid recalculating metrics.** `product_sales_summary`,
`salesperson_sales_summary`, and `territory_sales_summary` each compute one
aggregation once, and everything downstream (rankings, profitability, growth,
etc.) reads from that base instead of repeating the same join and aggregation.

**Cost at time of sale, not current cost.** `sales_analytics` joins each order
line to `productcosthistory` using the date the order was placed, not the
product's current standard cost. This matters because product costs change over
time, and using today's cost against a three year old order would give a wrong
margin.

**Recomputing dropped columns.** The load script drops several columns that were
computed columns in the original SQL Server schema. We recompute these directly
in the relevant views rather than assuming they exist. See "Notes on the source
schema" below for the full list.

**Window functions over repeated subqueries.** Rankings use `RANK()`, growth
comparisons use `LAG()`, and revenue share uses `SUM() OVER ()`, all in a single
pass over the data rather than correlated subqueries.

---

## Notes on the source schema

`install.sql` drops several columns right after loading the data, since they
were computed columns in the original SQL Server schema and Postgres does not
recreate the same computation automatically. Every view in `analytics_pipeline.sql`
that needs one of these values recomputes it directly rather than assuming the
column exists.

| Column | Table | Recomputed as |
|---|---|---|
| `LineTotal` | `SalesOrderDetail` | `UnitPrice * (1 - UnitPriceDiscount) * OrderQty` |
| `LineTotal` | `PurchaseOrderDetail` | `OrderQty * UnitPrice` |
| `StockedQty` | `PurchaseOrderDetail` | `ReceivedQty - RejectedQty` |
| `SalesOrderNumber` | `SalesOrderHeader` | Not used in this project |
| `AccountNumber` | `Customer` | Not used in this project |
| `TotalDue` | `PurchaseOrderHeader` | Not used in this project |

----

## Challenges faced

- The first dataset had a broken delimiter in 13 CSV files, which we only caught
  by actually running the load and checking row counts against expected totals,
  not by reading the files by eye.
- Several columns we expected to read directly (`LineTotal`, `StockedQty`, and
  others) turned out to be dropped by the load script since they were computed
  columns in the original schema. Every view that needed them recomputes them.
- Our first version of `territory_analytics` returned 13 rows instead of 10,
  because three territories had two "current" salesperson history records
  instead of one. Fixed with a `LATERAL` join that picks exactly one per
  territory.
- 2025 is a partial year in this dataset (data runs through June 2025 only), so
  any year over year comparison involving 2025 needs a caveat or it reads as a
  real decline when it isn't one.

---

## Assumptions made

- "Lowest performing products" excludes products that were never sold at all.
  A product with zero sales is a different problem (never launched, or
  discontinued) than one that sold but underperformed, so we kept these
  separate rather than mixing them into one ranking.
- "Current" salesperson or vendor assignments use the history record with a
  null end date. Where more than one such record exists for the same entity,
  we pick the one with the latest start date, breaking ties by ID.
- Top and bottom territory rankings are limited to 5 each, since there are only
  10 territories total.
- 209 of 504 products have no category or subcategory assigned in the source
  data. We treat this as a genuine data gap rather than a bug, and label it
  "Uncategorized" in category level reporting rather than dropping those
  products from totals.
- All 701 store-channel customers show zero direct orders in the sales data.
  We report this as a finding rather than assuming it's an error, since we
  can't confirm from this dataset alone whether store purchases are tracked
  through a different channel.

  ---

  ## Author

  *Imama Zubair*

