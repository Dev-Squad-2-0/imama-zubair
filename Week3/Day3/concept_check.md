# Concept Check 

1. What is the difference between WHERE and HAVING?

WHERE filters individual rows before grouping, while HAVING filters grouped results after GROUP BY.

2. When would you use a correlated subquery instead of a JOIN?

When the inner query needs to use values from each row of the outer query, such as finding the highest-priced film in each category.

3. What is a CTE, and why is it more readable than a nested subquery?

A CTE is a temporary result set created with WITH. It makes long queries easier to read by breaking them into smaller steps.

4. Explain the difference between RANK() and DENSE_RANK().

Both give the same rank to tied values. RANK() skips the next rank after a tie, while DENSE_RANK() does not. There are no gaps in DENSE_RANK()

5. What does PARTITION BY do differently from GROUP BY?

GROUP BY combines rows into one result per group. PARTITION BY keeps all rows but performs calculations separately within each group.

6. Can a subquery return multiple rows? What operator would you use in that case?

Yes. Use operators like IN, ANY, or EXISTS when a subquery returns multiple rows.

7. Give an example of when CASE WHEN is useful inside an aggregate function.

You can count rentals over a certain amount or calculate total revenue for only a specific group of customers.