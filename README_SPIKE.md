# Enterprise Dedicated Environment — spike notes

This spike routes enterprise tenant ID 1 through a dedicated API service (`api_whale`) and dedicated PostgreSQL database (`db_whale`). Existing small tenants stay on the shared API service (`api`) and shared PostgreSQL database (`db`). Nginx routes `/t/1/...` to the enterprise API; all other requests go to the shared API.

## Implemented in this spike

- Tenant-to-DSN routing via TENANT_DSN_MAP, with a separate connection pool per unique DSN.
- Dedicated db_whale PostgreSQL service in docker-compose.yml; tenant 1 is routed there by default.
- A per-process concurrency guard for small-tenant monthly reports (maximum two simultaneous reports per tenant); excess requests receive HTTP 429.
- Operations dashboard metrics for p50/p95/p99 latency, request errors, pool pressure, DB routing, simulation state and backup configuration.
- A seed scope option to populate the shared database with small tenants and the dedicated database with tenant 1 only.
- Acceptance-criteria targets are visible in the UI, without claiming that a target has been met.

## Start and seed the two databases

The compose file now defines both db and db_whale, waits for both health checks, and configures tenant 1 routing.

Rebuild and start the services:

    docker compose up -d --build

Scale only the enterprise application service independently when needed:

    docker compose up -d --scale api_whale=2

Seed only the small tenants into the shared database:

    docker compose run --rm -e SEED_SCOPE=small api python -m app.seed

Seed only the enterprise tenant into the dedicated database:

    docker compose run --rm -e DATABASE_URL=postgresql://erp:erp@db_whale:5432/erp -e SEED_SCOPE=whale api python -m app.seed

Important: the seed command truncates the target database before populating it. Run the small and whale seed commands against their respective databases only. Do not run the default SEED_SCOPE=all against either database when testing split tenancy.

In Codespaces, inspect the Ports tab and open port 8000. Customer view is /; operations dashboard is /ops.

## Acceptance criteria verification plan

1. Data isolation: verify db_whale contains tenant 1 and its orders only; verify the shared database contains small tenants (IDs 2+), not tenant 1. Verify /t/1/orders and /t/1/reports/monthly return only tenant-1 records. Add negative tests for attempted cross-tenant reads/writes before claiming this criterion complete. The current URL tenant ID is a demo-only identity mechanism, not authentication; production must derive tenant identity from a verified auth token.
2. Performance: run the load test with the agreed 1,200-user profile. Record p95 standard request latency; target ≤ 2,000 ms. This spike alone does not prove the target.
3. Existing tenants: capture a baseline for small tenants, run enterprise month-end load, then compare equivalent small-tenant average response times. Target degradation ≤ 5%. The in-memory guard limits concurrent small-tenant reports, but the threshold requires a repeatable load test.
4. Availability: a rolling production measurement must show ≥ 99.9% availability over the SLA measurement window. Health endpoint checks in this prototype are not an availability certification.

## Important production gaps

- The in-memory report limiter is per process; use a distributed limiter or database/resource isolation across multiple replicas.
- TENANT_DSN_MAP supports dedicated DB routing but does not provide identity/authentication security.
- Production backup requires encrypted off-site storage, retention policy, alerting, restore tests, and documented RPO/RTO. The dashboard only reports whether BACKUP_DIR is configured.
- Monitoring shown here is process-local; export metrics to a central monitoring system before operating an SLA.
- No load test has yet demonstrated 1,200 concurrent users, the ≤5% small-tenant degradation target, or 99.9% availability.

## Load-test execution

After both databases are seeded and the API is healthy, run the 1,200 virtual-small-user profile from the Codespace terminal:

    python loadtest/loadtest.py --label ac2-ac3-1200-users --small-workers 1200 --whale-workers 40 --duration 60

The report prints small-tenant p95 under enterprise load for AC2 and average-latency degradation between the baseline and enterprise-load phases for AC3. It also saves raw summaries under results/. This is a workload test, not proof of a production SLA; record the actual run output and environment before making acceptance claims.


## Isolation and security boundary

The gateway provides network-level separation of tenant 1 application traffic and its database connection. SQL queries are tenant-scoped. However, this prototype still accepts the tenant ID from the URL and does not implement authenticated tenant identity or per-tenant credentials. Therefore AC1 is not production-verified: before launch, add authenticated identity-to-tenant binding, least-privilege database roles, and negative cross-tenant authorization tests. Do not expose this demo publicly with production data.

## Backup and recovery

No backup destination or restore process is provisioned by this spike. Before production, configure scheduled PostgreSQL backups for both database volumes, encryption, off-site retention, monitoring/alerting, and tested restore procedures with agreed RPO/RTO. AC4 requires external uptime monitoring and an SLA measurement window; local health checks are not proof of 99.9% availability.
