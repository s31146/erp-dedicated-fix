"""Remove / add the whale (tenant 1) at runtime, for the demo on the Ops page."""
import psycopg

from . import db
from .seed import WHALE_ORDERS

WHALE_ID = 1


def status() -> dict:
    with psycopg.connect(db.dsn_for(WHALE_ID)) as conn:
        orders = conn.execute("SELECT count(*) FROM orders WHERE tenant_id = %s", (WHALE_ID,)).fetchone()[0]
        exists = conn.execute("SELECT count(*) FROM tenants WHERE id = %s", (WHALE_ID,)).fetchone()[0]
    return {"present": bool(exists), "orders": orders}


def remove() -> None:
    with psycopg.connect(db.dsn_for(WHALE_ID), autocommit=True) as conn:
        # skip per-row foreign-key checks: orders are looked up in order_lines without a suitable index
        conn.execute("SET session_replication_role = replica")
        conn.execute("DELETE FROM order_lines WHERE tenant_id = %s", (WHALE_ID,))
        conn.execute("DELETE FROM orders WHERE tenant_id = %s", (WHALE_ID,))
        conn.execute("DELETE FROM tenants WHERE id = %s", (WHALE_ID,))
        conn.execute("ANALYZE")


def add() -> None:
    remove()  # start clean if a previous attempt left partial data
    with psycopg.connect(db.dsn_for(WHALE_ID), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO tenants (id, name, plan) VALUES (%s, 'Whale Distribution', 'enterprise') "
            "ON CONFLICT DO NOTHING",
            (WHALE_ID,),
        )
        conn.execute(
            """
            INSERT INTO orders (tenant_id, order_date, status)
            SELECT %s, date '2025-01-01' + (random() * 670)::int,
                   (ARRAY['new','paid','shipped','closed'])[1 + (random() * 3)::int]
            FROM generate_series(1, %s)
            """,
            (WHALE_ID, WHALE_ORDERS),
        )
        conn.execute(
            """
            INSERT INTO order_lines (tenant_id, order_id, product, qty, unit_price)
            SELECT o.tenant_id, o.id, 'SKU-' || (1 + (random() * 199)::int),
                   1 + (random() * 19)::int, round((5 + random() * 495)::numeric, 2)
            FROM orders o
            CROSS JOIN LATERAL generate_series(1, 1 + (o.id % 7))
            WHERE o.tenant_id = %s
            """,
            (WHALE_ID,),
        )
        conn.execute(
            "UPDATE orders o SET total = s.t FROM "
            "(SELECT order_id, sum(qty * unit_price) t FROM order_lines WHERE tenant_id = %s GROUP BY order_id) s "
            "WHERE s.order_id = o.id AND o.tenant_id = %s",
            (WHALE_ID, WHALE_ID),
        )
        conn.execute("ANALYZE")
