CREATE TABLE superstore_sales (
    "Row ID" INT,
    "Order ID" VARCHAR(30),
    "Order Date" DATE,
    "Ship Date" DATE,
    "Ship Mode" VARCHAR(50),
    "Customer ID" VARCHAR(30),
    "Customer Name" VARCHAR(100),
    "Segment" VARCHAR(50),
    "Country" VARCHAR(50),
    "City" VARCHAR(100),
    "State" VARCHAR(100),
    "Postal Code" VARCHAR(20),
    "Region" VARCHAR(50),
    "Product ID" VARCHAR(30),
    "Category" VARCHAR(50),
    "Sub-Category" VARCHAR(50),
    "Product Name" TEXT,
    "Sales" NUMERIC(10,2),
    "Quantity" INT,
    "Discount" NUMERIC(5,2),
    "Profit" NUMERIC(10,2)
);

copy superstore_sales ("Row ID","Order ID","Order Date","Ship Date","Ship Mode","Customer ID","Customer Name","Segment","Country","City","State","Postal Code","Region","Product ID","Category","Sub-Category","Product Name","Sales","Quantity","Discount","Profit") 
    FROM 'D:\repos\NETIXSOL\imama-zubair\Week3\Day1\superstore_sales.csv'
    WITH (FORMAT csv, HEADER, DELIMITER ',', ENCODING 'WIN1252')


SELECT COUNT(*)
FROM superstore_sales;

SELECT *
FROM superstore_sales
LIMIT 10;

SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'superstore_sales';