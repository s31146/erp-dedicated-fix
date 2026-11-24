const $ = (id) => document.getElementById(id);
const fmtMs = (v) => v == null ? "—" : `${Number(v).toFixed(1)} ms`;

async function json(url, options) {
  const r = await fetch(url, options);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
}

async function loadMetrics() {
  try {
    const [m, w, s, b] = await Promise.all([
      json("/admin/metrics"), json("/admin/whale"), json("/admin/simulation"), json("/admin/backup/status")
    ]);
    $("tenant-state").textContent = w.present ? "PROVISIONED" : "NOT PROVISIONED";
    $("tenant-meta").textContent = `${w.orders.toLocaleString("en-US")} demo orders · tenant ID 1`;
    $("routing-mode").textContent = m.routing.routing_mode.toUpperCase();
    $("routing-detail").textContent = m.routing.dedicated_tenants.length
      ? `Dedicated tenant IDs: ${m.routing.dedicated_tenants.join(", ")}`
      : "No TENANT_DSN_MAP configured; tenants currently use shared DB";
    $("sim-state").textContent = s.running ? "RUNNING" : "STOPPED";
    $("sim-toggle").textContent = s.running ? "Stop month-end simulation" : "Start month-end simulation";
    $("whale-remove").disabled = !w.present;
    $("whale-add").disabled = w.present;
    $("whale-p95").textContent = fmtMs(m.whale.p95_ms);
    $("whale-count").textContent = `${m.whale.requests} requests · ${m.whale.errors} errors`;
    $("small-p95").textContent = fmtMs(m.small_tenants.p95_ms);
    $("small-count").textContent = `${m.small_tenants.requests} requests · ${m.small_tenants.errors} errors`;
    $("report-slots").textContent = `${m.small_report_concurrency_limit} / tenant`;
    const pools = Object.entries(m.pools || {});
    $("pool-rows").innerHTML = pools.length ? pools.map(([name,p]) => `<tr><td>${name}</td><td>${p.pool_size ?? "—"}</td><td>${p.pool_available ?? "—"}</td><td>${p.requests_waiting ?? "—"}</td><td>${p.requests_errors ?? "—"}</td></tr>`).join("") : "<tr><td colspan='5'>No DB connection pools opened yet</td></tr>";
    $("pool-msg").textContent = pools.length ? "Separate pool per configured DSN." : "Make a customer request to initialize a database pool.";
    $("backup-state").textContent = b.configured ? `BACKUP_DIR configured: ${b.directory}` : "Not configured in this Codespace (BACKUP_DIR is unset).";
  } catch (e) { $("action-msg").textContent = e.message; }
}

async function action(url, message) {
  $("action-msg").textContent = message;
  try { await json(url, {method:"POST"}); $("action-msg").textContent = "Action completed."; await loadMetrics(); }
  catch (e) { $("action-msg").textContent = e.message; }
}

$("whale-remove").addEventListener("click", () => action("/admin/whale/remove", "Removing enterprise demo data…"));
$("whale-add").addEventListener("click", () => action("/admin/whale/add", "Provisioning enterprise demo data…"));
$("sim-toggle").addEventListener("click", async () => {
  try { const s = await json("/admin/simulation"); await action(`/admin/simulation/${s.running ? "stop" : "start"}`, "Updating load simulation…"); }
  catch (e) { $("action-msg").textContent = e.message; }
});
$("refresh").addEventListener("click", loadMetrics);
loadMetrics();
setInterval(loadMetrics, 5000);
