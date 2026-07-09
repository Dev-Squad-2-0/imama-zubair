# Week 3 Day 4: Concept Check

## 1. Why are multiple CTEs preferred over one large nested query?

**Ans**: Multiple CTEs are easier to manage, they are resuable, can be debugged and and easy to maintain because each step has a clear purpose.


## 2. When would you use a window function instead of GROUP BY?

**Ans**: We do that when we need to calculate the aggregate the values but also want to retain all the rows. Unlike GROUP BY, a window function does not reduce the dataset.


## 3. Explain the difference between ROW_NUMBER(), RANK(), and DENSE_RANK().

**Ans**: It all depends on how they handle ties. ROW_NUMBER() ignores ties and assigns a unique number to every row, RANK() gives ties the same number but skips subsequent ranks, and DENSE_RANK() gives ties the same number without skipping any ranks. DENSE_RANK() is pretty good out of all of them.


## 4. What is conditional aggregation?

**Ans**: Conditional aggregation is when a CASE WHEN (condition) is encased inside an aggregate function
For example: SUM(CASE WHEN condition 1 ELSE condition 2)


## 5. How does CASE WHEN improve analytical reporting?

**Ans**: It allows data to be categorized into meaningful groups, such as customer segments or performance levels


## 6. Why should SQL queries be broken into logical stages?

**Ans**: It improves readability, avoids repeated calculations, simplifies debugging, and makes results reusable.

## 7. What makes a SQL query maintainable?

**Ans**: Clear formatting, descriptive names, comments, reusable CTEs, and avoiding duplicated logic is what makes a SQL query maintainable.

---