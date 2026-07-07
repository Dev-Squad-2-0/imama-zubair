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