"""Mini-ERP API with measurable dedicated-tenant spike capabilities."""
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db, guardrail, simulation, whale

app = FastAPI(title="Mini-ERP Enterprise Dedicated Environment Spike")

@app.middleware("http")
async def measure(request: Request, call_next):
    tenant_id = guardrail.tenant_from_path(request.url.path)
    start = time.perf_counter()
    response = await call_next(request)
    if tenant_id is not None:
        guardrail.record(tenant_id, (time.perf_counter() - start) * 1000, response.status_code)
    return response

class Line(BaseModel):
    product: str
    qty: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)

class OrderIn(BaseModel):
    lines: list[Line] = Field(min_length=1)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def page_client(): return FileResponse(STATIC_DIR / "index.html")

@app.get("/ops", include_in_schema=False)
def page_ops(): return FileResponse(STATIC_DIR / "ops.html")

@app.get("/api/tenants")
def list_tenants():
    # Small tenants live in the shared DB; enterprise tenant 1 lives in db_whale.
    with db.tenant_conn(2) as conn:
        small = conn.execute(
            "SELECT id, name, plan FROM tenants WHERE id BETWEEN 2 AND 20 ORDER BY id"
        ).fetchall()
    with db.tenant_conn(whale.WHALE_ID) as conn:
        enterprise = conn.execute(
            "SELECT id, name, plan FROM tenants WHERE id = %s", (whale.WHALE_ID,)
        ).fetchall()
    return sorted([*enterprise, *small], key=lambda tenant: tenant["id"])

@app.get("/health")
def health(): return {"ok": True, "routing": db.routing_status()}

@app.get("/t/{tenant_id}/orders")
def list_orders(tenant_id: int = Depends(guardrail.check), limit: int = Query(50, le=500)):
    with db.tenant_conn(tenant_id) as conn:
        return conn.execute("SELECT id, order_date, status, total FROM orders WHERE tenant_id = %s ORDER BY order_date DESC, id DESC LIMIT %s", (tenant_id, limit)).fetchall()

@app.post("/t/{tenant_id}/orders", status_code=201)
def create_order(order: OrderIn, tenant_id: int = Depends(guardrail.check)):
    total = sum(l.qty * l.unit_price for l in order.lines)
    try:
        with db.tenant_conn(tenant_id) as conn:
            row = conn.execute("INSERT INTO orders (tenant_id, order_date, status, total) VALUES (%s, CURRENT_DATE, 'new', %s) RETURNING id", (tenant_id, total)).fetchone()
            conn.cursor().executemany("INSERT INTO order_lines (tenant_id, order_id, product, qty, unit_price) VALUES (%s, %s, %s, %s, %s)", [(tenant_id, row["id"], l.product, l.qty, l.unit_price) for l in order.lines])
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(status_code=404, detail="unknown tenant")
    return {"id": row["id"], "total": total}

@app.get("/t/{tenant_id}/reports/monthly")
def monthly_report(tenant_id: int = Depends(guardrail.check), year: int = 2026):
    # The guardrail ensures a small tenant cannot be starved by unlimited report fan-out.
    with guardrail.report_budget(tenant_id):
        with db.tenant_conn(tenant_id) as conn:
            return conn.execute("""SELECT date_trunc('month', o.order_date)::date AS month, l.product,
                sum(l.qty * l.unit_price) AS revenue, sum(l.qty) AS units
                FROM orders o JOIN order_lines l ON l.order_id = o.id AND l.tenant_id = o.tenant_id
                WHERE o.tenant_id = %s AND o.order_date >= %s AND o.order_date < %s
                GROUP BY 1, 2 ORDER BY 1, revenue DESC LIMIT 200""",
                (tenant_id, date(year, 1, 1), date(year + 1, 1, 1))).fetchall()

@app.get("/admin/metrics")
def metrics(): return {**guardrail.snapshot(), "pools": db.pool_stats(), "routing": db.routing_status()}

@app.post("/admin/metrics/reset")
def metrics_reset(): guardrail.reset(); return {"reset": True}

@app.get("/admin/whale")
def whale_status(): return whale.status()

@app.post("/admin/whale/remove")
def whale_remove(): whale.remove(); return whale.status()

@app.post("/admin/whale/add")
def whale_add(): whale.add(); return whale.status()

@app.get("/admin/simulation")
def simulation_status(): return {"running": simulation.running()}

@app.post("/admin/simulation/start")
def simulation_start(): simulation.start(); return {"running": simulation.running()}

@app.post("/admin/simulation/stop")
def simulation_stop(): simulation.stop(); return {"running": False}

@app.get("/admin/backup/status")
def backup_status():
    return {"configured": bool(__import__('os').getenv('BACKUP_DIR')), "directory": __import__('os').getenv('BACKUP_DIR'),
            "note": "Spike status only; configure encrypted off-site storage and restore drills for production."}
