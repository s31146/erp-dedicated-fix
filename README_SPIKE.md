# Enterprise Dedicated Environment — spike notes

This spike extends the Mini-ERP starter to demonstrate the refinement decision: keep the 300 small tenants on the shared stack and route enterprise tenant ID 1 to its own PostgreSQL database and connection pool.

## Implemented in this spike

- Tenant-to-DSN routing via TENANT_DSN_MAP; a pool is created per unique DSN.
- A report concurrency guard for small tenants (maximum two simultaneous monthly reports per tenant); excess requests receive HTTP 429. Enterprise reports are not constrained by this small-tenant budget.
- Operations dashboard metrics for p50/p95/p99 latency, request errors, pool pressure, DB routing, simulation state and backup configuration.
- Acceptance-criteria targets are visible in the UI, without claiming that a target has been met.

## Enable the dedicated enterprise database in Codespaces

The base compose file includes a shared db service. Add a second PostgreSQL service named db_whale using the same schema initialization:

    db_whale:
      image: postgres:16
      environment:
        POSTGRES_USER: erp
        POSTGRES_PASSWORD: erp
        POSTGRES_DB: erp
      volumes:
        - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U erp"]
        interval: 3s
        retries: 20

Set these variables on the api service:

    TENANT_DSN_MAP: '{"1": "postgresql://erp:erp@db_whale:5432/erp"}'
    POOL_MAX: "10"

Add db_whale to api.depends_on with condition service_healthy. Then rebuild and start:

    docker compose up -d --build
    docker compose run --rm api python -m app.seed

The seed command writes the demo tenant dataset to the default database. To seed the dedicated database, run the seed command with DATABASE_URL=postgresql://erp:erp@db_whale:5432/erp in the one-off api container or execute the seed module with that environment override.

In Codespaces, inspect the Ports tab and open port 8000. Customer view is /; operations dashboard is /ops.

## Acceptance criteria verification plan

1. Data isolation: Configure tenant 1 to use db_whale; verify /t/1/orders and /t/1/reports/monthly return only tenant-1 records. Verify tenant IDs 2–20 continue using the shared DB. Add negative tests for attempted cross-tenant reads/writes before claiming this criterion complete. The current URL tenant ID is a demo-only identity mechanism, not authentication; production must derive tenant identity from a verified auth token.
2. Performance: Run the load test with the agreed 1,200-user profile. Record p95 standard request latency; target ≤ 2,000 ms. This spike alone does not prove the target.
3. Existing tenants: Capture a baseline for small tenants, run enterprise month-end load, then compare equivalent small-tenant average response times. Target degradation ≤ 5%. The in-memory guard limits concurrent small-tenant reports, but the threshold requires a repeatable load test.
4. Availability: A rolling production measurement must show ≥ 99.9% availability over the SLA measurement window. Health endpoint checks in this prototype are not an availability certification.

## Important production gaps

- The in-memory report limiter is per process; use a distributed limiter or database/resource isolation across multiple replicas.
- TENANT_DSN_MAP supports dedicated DB routing but does not provide identity/authentication security.
- Production backup requires encrypted off-site storage, retention policy, alerting, restore tests, and documented RPO/RTO. The dashboard only reports whether BACKUP_DIR is configured.
- Monitoring shown here is process-local; export metrics to a central monitoring system before operating an SLA.
