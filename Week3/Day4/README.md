# Week 3 Day 4: Advanced SQL Business Intelligence Challenge (Music Store Database)

--- 

## Goal

Work with a new enterprise database and solve a complete business problem using SQL. Instead of writing independent queries, build a chain of analytical queries where each step depends on the previous one. Students should decide how to structure their solution using CTEs, window functions, subqueries, aggregations, and joins.

--- 

## Dataset

**Database:** Music Store Database (`music_store_postgres.sql`)

The database contains information about customers, invoices, employees, artists, albums, tracks, genres, and playlists.

### Main Tables Used

- Customer
- Invoice
- Invoice_Line
- Track
- Album
- Artist
- Genre
- Employee

---


## Project Structure

```text
Customer Profile
        ↓
Customer Segments
        ↓
Favorite Genres
        ↓
Marketing Recommendations
        ↓
Country Metrics
        ↓
Country Rankings
        ↓
Executive Report
```
---

## **Task 1: Customer Profile**

Built one row per customer with total spend, total invoices, tracks purchased, unique genres, unique artists, purchase months, and average invoice value. This became the base that every other task reused.


---

## **Task 2: Customer Segments**

Split customers into Platinum, Gold, Silver, and Bronze. Fixed thresholds didn't work because most customers in this dataset spend a pretty similar amount(none fell in bronze). So instead I built a composite score out of spending, invoice frequency, genre diversity, and artist diversity, and split customers into four even groups using NTILE.

### Segmentation Logic & Justification

Fixed thresholds didn't work well because most customers had similar spending and invoice counts. Instead, I gave each customer a **composite score**:

```text
composite_score = 0.40 × normalized(total_spent)
                + 0.20 × normalized(total_invoices)
                + 0.20 × normalized(unique_genres)
                + 0.20 × normalized(unique_artists)
```

Each value is normalized (0-1) by dividing it by the highest value in that metric. Spending has the highest weight, while the other metrics measure customer engagement.

I then used `NTILE(4)` to split customers into four equal groups:

- **Platinum:** Top 25%
- **Gold:** Next 25%
- **Silver:** Next 25%
- **Bronze:** Bottom 25%

---

## **Task 3: Marketing Recommendation **

Found each customer's favorite genre with a window function, then matched every segment to a campaign (early access, bundles, genre discounts, first purchase coupons).

### Favorite Genre & Campaigns (Marketing Recommendation Strategy)

Each customer's favorite genre is found using `ROW_NUMBER()` to rank genres by the number of tracks purchased, then keeping only the top-ranked genre.

This is joined with the customer segments from Task 2, and a `CASE WHEN` assigns a marketing campaign:

| Segment | Campaign |
|----------|----------|
| **Platinum** | Early access to new releases |
| **Gold** | Album bundle discounts |
| **Silver** | Discount codes for their favorite genre |
| **Bronze** | First purchase coupon |

---

## **Task 4: Country Expansion Strategy**

Built a weighted score for each country using revenue, customers, revenue per customer, invoice value, and genre diversity, then ranked all countries and picked the top three for expansion.

### Country Ranking Methodology

Countries are ranked using a weighted **expansion score**:

```text
expansion_score = 0.35 × normalized(avg_revenue_per_customer)
                + 0.25 × normalized(total_revenue)
                + 0.20 × normalized(avg_invoice_value)
                + 0.20 × normalized(genre_diversity)
```

All values are normalized (0-1). Average revenue per customer has the highest weight since it reflects customer value, while the other metrics measure market size and buying behavior.

**Top countries for expansion:**

1. **USA** - Highest revenue, most customers, and greatest genre diversity.
2. **Canada** - Strong performance across almost every metric.
3. **France** - Smaller customer base but high revenue per customer and good genre diversity.

---

## **Task 5: Executive SQL Report**

Combined everything above into one report: segment summary, revenue by segment, top country, top employee, top artist, and top album.

---

## Actionable Recommendations

1. Focus expansion budget on USA and Canada first, they have the strongest combination of revenue and customer count (expansion score)

2. Run the Silver-tier genre discount campaign soon, it's a large group sitting right below Gold and a good target to nudge things up

3. Treat Platinum's early access perk as a retention tool, losing even a couple of these customers has a real revenue impact (they may be less in number but are super valuable :D)

4. Run small pilot campaigns in France, Czech Republic, and Chile to test if their strong per-customer revenue scales with more customers (they are top 3-5)

5. Recalculate customer segments every quarter so NTILE(4) keeps the groups balanced.

---

## Challenges Faced

1. Fixed thresholds did not work since most customers in this dataset spend a pretty similar amount(none fell in bronze) so didnt end up using it

2. Joining invoices with invoice lines duplicated invoice-level metrics like invoice counts.

3. Combining metrics with different scales (e.g., dollars and counts) into one score.

4. Making the SQL work both as one complete pipeline,

---

## Solutions to those Challenges

1. Used a normalized composite score with `NTILE(4)` to create four balanced customer segments

2. Calculated invoice-level and line-item metrics in separate CTEs before joining them (no more dupes)

3. Normalized all metrics to a 0-1 scale before applying weights (pretty standard)

4. Made each task self-contained with its own CTEs so it can run independently so that in the future, if certain pieces of the pipeline need to be checked, we can do that easily.

---

## Skills Demonstrated


* Multi-level and chained CTEs
* Window functions (aggregate + ranking(ROW_NUMBER, RANK, NTILE))
* Conditional aggregation and CASE WHEN logic
* Business KPI design and weighted scoring (composite score and expansion score)
* Data normalization for fair metric comparison
* SQL query organization and readability

---

## Author 

*Imama Zubair*

AI & Data Science Intern @ Netixsol


