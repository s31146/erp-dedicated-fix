"""Per-tenant latency metrics and protection for shared small tenants.

The in-memory concurrency guard is intentionally a spike implementation:
use a distributed limiter (for example Redis) before running multiple API
replicas in production.
"""
import re
import threading
from collections import defaultdict, deque
from contextlib import contextmanager
from fastapi import HTTPException

WHALE_ID = 1
_PATH = re.compile(r"^/t/(\d+)/")
_lat: dict[int, deque] = defaultdict(lambda: deque(maxlen=1000))
_lock = threading.Lock()
_inflight_reports: dict[int, int] = defaultdict(int)
_REPORT_LIMIT_SMALL = 2


def tenant_from_path(path: str):
    m = _PATH.match(path)
    return int(m.group(1)) if m else None


def record(tenant_id: int, ms: float, status: int) -> None:
    with _lock:
        _lat[tenant_id].append((ms, status))


@contextmanager
def report_budget(tenant_id: int):
    """Limit concurrent monthly reports for small tenants; whale has its own pool."""
    with _lock:
        limit = _REPORT_LIMIT_SMALL
        current = _inflight_reports[tenant_id]
        if tenant_id != WHALE_ID and current >= limit:
            raise HTTPException(status_code=429, detail="monthly report concurrency limit reached for this tenant")
        _inflight_reports[tenant_id] += 1
    try:
        yield
    finally:
        with _lock:
            _inflight_reports[tenant_id] = max(0, _inflight_reports[tenant_id] - 1)


def check(tenant_id: int) -> int:
    """Validate tenant route parameter and return it for dependency injection."""
    if tenant_id < 1:
        raise HTTPException(status_code=404, detail="unknown tenant")
    return tenant_id


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 1)


def _summ(samples: list[tuple[float, int]]) -> dict:
    ms = [m for m, _ in samples]
    return {"requests": len(ms), "errors": sum(1 for _, st in samples if st >= 400),
            "p50_ms": _pct(ms, 50), "p95_ms": _pct(ms, 95), "p99_ms": _pct(ms, 99)}


def snapshot() -> dict:
    with _lock:
        whale = list(_lat.get(WHALE_ID, []))
        small = [s for tid, d in _lat.items() if tid != WHALE_ID for s in d]
        per_tenant = {tid: list(d) for tid, d in _lat.items() if tid != WHALE_ID}
        inflight = dict(_inflight_reports)
    worst = sorted(({"tenant_id": tid, **_summ(s)} for tid, s in per_tenant.items() if s),
                   key=lambda x: x["p95_ms"] or 0, reverse=True)[:5]
    return {"whale": _summ(whale), "small_tenants": _summ(small),
            "worst_small_tenants": worst, "reports_inflight": inflight,
            "small_report_concurrency_limit": _REPORT_LIMIT_SMALL}


def reset() -> None:
    with _lock:
        _lat.clear()
