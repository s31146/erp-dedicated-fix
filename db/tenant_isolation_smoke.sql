-- Manual SQL smoke test for the dedicated enterprise database.
-- Run against both shared and db_whale databases after seeding.
SELECT current_database() AS database_name;
SELECT id, name, plan FROM tenants ORDER BY id LIMIT 25;
SELECT tenant_id, count(*) AS orders FROM orders GROUP BY tenant_id ORDER BY tenant_id;

-- Expected after correct routing:
-- db_whale contains enterprise tenant 1 only (and its dependent orders/lines).
-- shared DB contains small tenants (IDs 2+), not tenant 1.
