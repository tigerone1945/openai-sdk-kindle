SELECT
    category,
    SUM(sales_amount)
FROM sales
GROUP BY category;
