"""Load test: small tenants alone vs. small tenants + whale month-end reports.

    python loadtest/loadtest.py --label baseline-shared
    python loadtest/loadtest.py --label whale-dedicated-db --whale-workers 16

Phase 1 'small_only'  : small tenants do normal work (reads + writes).
Phase 2 'with_whale'  : same traffic + whale workers hammering the heavy report.
The number that matters for the go/no-go: p95 of SMALL tenants, phase 1 vs 2.
Results are also saved to results/<label>.json
"""
import argparse
import asyncio
import json
import os
import random
import time

import httpx


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 1)


async def small_worker(client, stop_at, lat, errors, n_small):
    while time.perf_counter() < stop_at:
        tid = random.randint(2, n_small + 1)
        t0 = time.perf_counter()
        try:
            if random.random() < 0.8:
                r = await client.get(f"/t/{tid}/orders", params={"limit": 20})
            else:
                r = await client.post(
                    f"/t/{tid}/orders",
                    json={"lines": [{"product": "SKU-1", "qty": 2, "unit_price": "9.99"}]},
                )
            ok = r.status_code < 400
        except httpx.HTTPError:
            ok = False
        lat.append((time.perf_counter() - t0) * 1000)
        if not ok:
            errors[0] += 1
        await asyncio.sleep(random.uniform(0.01, 0.05))  # think time


async def whale_worker(client, stop_at, lat, errors):
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            r = await client.get("/t/1/reports/monthly", params={"year": 2026})
            ok = r.status_code < 400
        except httpx.HTTPError:
            ok = False
        lat.append((time.perf_counter() - t0) * 1000)
        if not ok:
            errors[0] += 1


async def run_phase(args, whale_workers):
    small_lat, whale_lat, small_err, whale_err = [], [], [0], [0]
    connection_capacity = max(500, args.small_workers + whale_workers)
    limits = httpx.Limits(max_connections=connection_capacity, max_keepalive_connections=connection_capacity)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30, limits=limits) as client:
        stop_at = time.perf_counter() + args.duration
        tasks = [small_worker(client, stop_at, small_lat, small_err, args.small_tenants)
                 for _ in range(args.small_workers)]
        tasks += [whale_worker(client, stop_at, whale_lat, whale_err) for _ in range(whale_workers)]
        await asyncio.gather(*tasks)
    summary = lambda lat, err: {
        "requests": len(lat), "rps": round(len(lat) / args.duration, 1), "errors": err[0],
        "avg_ms": round(sum(lat) / len(lat), 1) if lat else None,
        "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95), "p99_ms": pct(lat, 99),
    }
    return {"small": summary(small_lat, small_err), "whale": summary(whale_lat, whale_err)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--duration", type=int, default=20, help="seconds per phase")
    ap.add_argument("--small-workers", type=int, default=10)
    ap.add_argument("--whale-workers", type=int, default=8, help="concurrent whale report runners")
    ap.add_argument("--small-tenants", type=int, default=300)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    print(f"[{args.label}] phase 1: small tenants only ({args.duration}s)")
    base = await run_phase(args, 0)
    print(f"[{args.label}] phase 2: + whale, {args.whale_workers} report workers ({args.duration}s)")
    with_whale = await run_phase(args, args.whale_workers)

    result = {"label": args.label, "args": vars(args), "small_only": base, "with_whale": with_whale}
    os.makedirs("results", exist_ok=True)
    with open(f"results/{args.label}.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n{'':<22}{'rps':>8}{'avg ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'errors':>8}")
    for name, r in (("small, no whale", base["small"]), ("small, with whale", with_whale["small"]),
                    ("whale reports", with_whale["whale"])):
        print(f"{name:<22}{r['rps']:>8}{r['avg_ms']!s:>10}{r['p95_ms']!s:>10}{r['p99_ms']!s:>10}{r['errors']:>8}")
    b, w = base["small"]["avg_ms"], with_whale["small"]["avg_ms"]
    if b is not None and w is not None and b > 0:
        degradation = (w - b) / b * 100
        print(f"\nAC3 average-latency degradation: {degradation:.1f}% (target <= 5%)")
    p95 = with_whale["small"]["p95_ms"]
    print(f"AC2 small-tenant p95 under enterprise load: {p95} ms (target <= 2000 ms)")


if __name__ == "__main__":
    asyncio.run(main())
