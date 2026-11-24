"""Tenant-aware PostgreSQL routing with isolated connection pools."""
import json
import os
import threading
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_DSN = os.getenv("DATABASE_URL", "postgresql://erp:erp@localhost:5432/erp")
POOL_MAX = int(os.getenv("POOL_MAX", "10"))
POOL_TIMEOUT = float(os.getenv("POOL_TIMEOUT", "10"))
TENANT_DSN_MAP = {int(k): v for k, v in json.loads(os.getenv("TENANT_DSN_MAP", "{}")).items()}
_pools: dict[str, ConnectionPool] = {}
_lock = threading.Lock()


def _pool_for(dsn: str) -> ConnectionPool:
    with _lock:
        if dsn not in _pools:
            _pools[dsn] = ConnectionPool(dsn, min_size=1, max_size=POOL_MAX,
                timeout=POOL_TIMEOUT, kwargs={"row_factory": dict_row}, open=True)
        return _pools[dsn]


def dsn_for(tenant_id: int) -> str:
    return TENANT_DSN_MAP.get(tenant_id, DEFAULT_DSN)


@contextmanager
def tenant_conn(tenant_id: int):
    with _pool_for(dsn_for(tenant_id)).connection() as conn:
        yield conn


def pool_stats() -> dict:
    out = {}
    with _lock:
        pools = list(_pools.items())
    for dsn, pool in pools:
        s = pool.get_stats()
        label = dsn.split("@")[-1]
        out[label] = {"pool_size": s.get("pool_size"), "pool_available": s.get("pool_available"),
                      "requests_waiting": s.get("requests_waiting"), "requests_errors": s.get("requests_errors")}
    return out


def routing_status() -> dict:
    return {"dedicated_tenants": sorted(TENANT_DSN_MAP),
            "default_database": DEFAULT_DSN.split("@")[-1],
            "routing_mode": "dedicated" if TENANT_DSN_MAP else "shared"}
