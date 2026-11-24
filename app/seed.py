"""Seed demo data into the selected tenant database.

SEED_SCOPE=all (default) seeds tenant 1 and small tenants 2..N+1.
SEED_SCOPE=small seeds only small tenants; use this for the shared database.
SEED_SCOPE=whale seeds only enterprise tenant 1; use this for db_whale.
The command truncates the target database before seeding.
"""
import os
import time

import psycopg

DSN = os.getenv("DATABASE_URL", "postgresql://erp:erp@localhost:5432/erp")
SEED_SCOPE = os.getenv("SEED_SCOPE", "all").lower()
SMALL_TENANTS = int(os.getenv("SMALL_TENANTS", "300"))
SMALL_ORDERS = int(os.getenv("SMALL_ORDERS", "300"))
WHALE_ORDERS = int(os.getenv("WHALE_ORDERS", "31500"))


def main() -> None:
    if SEED_SCOPE not in {"all", "small", "whale"}:
        raise ValueError("SEED_SCOPE must be one of: all, small, whale")
    t0 = time.time()
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("TRUNCATE order_lines, orders, tenants RESTART IDENTITY CASCADE")
        if SEED_SCOPE in {"all", "whale"}:
            conn.execute(
                "INSERT INTO tenants (id, name, plan) VALUES (1, 'Whale Distribution', 'enterprise')"
            )
        if SEED_SCOPE in {"all", "small"}:
            conn.execute(
                "INSERT INTO tenants (id, name, plan) "
                "SELECT g, 'Small Co ' || g, 'small' FROM generate_series(2, %s) g",
                (SMALL_TENANTS + 1,),
            )
        conn.execute(
            """
            INSERT INTO orders (tenant_id, order_date, status)
            SELECT t.id,
                   date '2025-01-01' + (random() * 670)::int,
                   (ARRAY['new','paid','shipped','closed'])[1 + (random() * 3)::int]
            FROM tenants t
            CROSS JOIN LATERAL generate_series(
                1, CASE WHEN t.id = 1 THEN %s ELSE %s END
            )
            """,
            (WHALE_ORDERS, SMALL_ORDERS),
        )
        conn.execute(
            """
            INSERT INTO order_lines (tenant_id, order_id, product, qty, unit_price)
            SELECT o.tenant_id, o.id,
                   'SKU-' || (1 + (random() * 199)::int),
                   1 + (random() * 19)::int,
                   round((5 + random() * 495)::numeric, 2)
            FROM orders o
            CROSS JOIN LATERAL generate_series(1, 1 + (o.id % 7))
            """
        )
        conn.execute(
            "UPDATE orders o SET total = s.t FROM "
            "(SELECT order_id, sum(qty * unit_price) t FROM order_lines GROUP BY order_id) s "
            "WHERE s.order_id = o.id"
        )
        conn.execute("ANALYZE")
        size = conn.execute(
            "SELECT pg_size_pretty(pg_database_size(current_database())) AS s"
        ).fetchone()[0]
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM orders WHERE tenant_id = 1) AS whale_orders, "
            "(SELECT count(*) FROM orders WHERE tenant_id <> 1) AS small_orders"
        ).fetchone()
    print(
        f"Seeded scope={SEED_SCOPE} in {time.time() - t0:.1f}s | db size {size} | "
        f"whale orders {counts[0]} | small-tenant orders {counts[1]}"
    )


if __name__ == "__main__":
    main()
