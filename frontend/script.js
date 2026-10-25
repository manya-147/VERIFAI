// Frontend for the Python backend (backend/backend.py → collect_from_pages).
// The page never re-implements scraping logic; it calls server.py, which calls the backend.
//   GET  /api/config  -> { default_goal }          (backend.models.DEFAULT_GOAL)
//   POST /api/search  -> NDJSON stream of {type:"progress"|"result"|"error", ...}
//                        progress = the backend's on_progress(message) callback

const $ = (id) => document.getElementById(id);
const state = { listings: [], filtered: [] };

/* ───────── Session state (in memory only, like st.session_state) ───────── */
let store = { searches: 0, ok: 0, listings: 0, links: 0, history: [] };

function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function renderStats() {
  $("statSearches").textContent = store.searches;
  $("statListings").textContent = store.listings;
  $("statLinks").textContent = store.links;
  $("statRate").textContent = store.searches ? Math.round((store.ok / store.searches) * 100) + "%" : "—";

  const list = $("activityList");
  list.innerHTML = "";
  if (!store.history.length) {
    list.innerHTML = '<li class="muted">No activity yet — run your first search.</li>';
    return;
  }
  store.history.slice(0, 6).forEach((h) => {
    const li = document.createElement("li");
    li.textContent = h.text;
    const small = document.createElement("small");
    small.textContent = timeAgo(h.ts);
    li.appendChild(small);
    list.appendChild(li);
  });
}

function record(text, { ok, listings = 0, links = 0 }) {
  store.searches += 1;
  if (ok) store.ok += 1;
  store.listings += listings;
  store.links += links;
  store.history.unshift({ text, ts: Date.now() });
  store.history = store.history.slice(0, 20);
  renderStats();
}

/* ───────── Helpers ───────── */
function isValidUrl(value) {
  try {
    const u = new URL(value);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host;
  } catch { return false; }
}
function parseLinks() {
  return [...new Set($("links").value.split("\n").map((l) => l.trim()).filter(Boolean))];
}
function showError(msg) { $("error").textContent = msg; $("error").hidden = !msg; }
function setStatus(text, busy) {
  $("statusText").textContent = text;
  $("statusPill").textContent = text;
  $("statusPill").classList.toggle("busy", !!busy);
}
function setLoading(on) {
  $("submitBtn").disabled = on;
  document.querySelector("#submitBtn .spinner").hidden = !on;
  document.querySelector("#submitBtn .label").textContent = on ? "Searching…" : "Search links";
  setStatus(on ? "Searching" : "Ready", on);
}
function log(msg) {
  const li = document.createElement("li");
  li.textContent = msg;
  $("progressLog").appendChild(li);
}
function syncMeta() {
  $("metaLimit").textContent = Math.min(100, Math.max(1, parseInt($("limit").value, 10) || 1));
  $("metaLinks").textContent = parseLinks().length;
}

/* ───────── Rendering ───────── */
function renderLinks(links) {
  $("linksCount").textContent = links.length;
  $("linksList").innerHTML = "";
  links.forEach((url) => {
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = url;
    $("linksList").appendChild(a);
  });
  $("linksBox").hidden = false;
}

function cell(value) {
  const td = document.createElement("td");
  if (value == null) return td;
  if (typeof value === "string" && isValidUrl(value)) {
    const a = document.createElement("a");
    a.href = value; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = value;
    td.appendChild(a);
  } else if (typeof value === "object") td.textContent = JSON.stringify(value);
  else td.textContent = String(value);
  return td;
}

function drawTable(rows) {
  const columns = [...new Set(state.listings.flatMap((r) => Object.keys(r)))];
  const thead = $("table").querySelector("thead");
  const tbody = $("table").querySelector("tbody");
  thead.innerHTML = ""; tbody.innerHTML = "";
  const head = document.createElement("tr");
  columns.forEach((c) => { const th = document.createElement("th"); th.textContent = c.replace(/_/g, " "); head.appendChild(th); });
  thead.appendChild(head);
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => tr.appendChild(cell(row[c])));
    tbody.appendChild(tr);
  });
}

function renderResults(listings, limit) {
  state.listings = listings;
  $("filter").value = "";
  $("results").hidden = false;
  $("resultsTitle").textContent = `Results (${listings.length} of up to ${limit})`;
  const empty = listings.length === 0;
  $("empty").hidden = !empty;
  $("tableWrap").hidden = empty;
  $("downloadBtn").hidden = empty;
  $("filter").hidden = empty;
  if (!empty) drawTable(listings);
}

$("filter").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  drawTable(q ? state.listings.filter((r) => JSON.stringify(r).toLowerCase().includes(q)) : state.listings);
});

/* ───────── Backend (collect_from_pages via server.py) ───────── */
async function collectFromPages(pages, goal, limit, onProgress) {
  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ links: Object.keys(pages), goal, limit }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let listings = null;
  const handle = (line) => {
    if (!line.trim()) return;
    const msg = JSON.parse(line);
    if (msg.type === "progress") onProgress(msg.message);
    else if (msg.type === "result") listings = msg.listings || [];
    else if (msg.type === "error") throw new Error(msg.message);
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.forEach(handle);
  }
  handle(buffer);
  if (listings === null) throw new Error("The server closed the connection before returning results.");
  return listings;
}

/* ───────── Form ───────── */
$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");

  const links = parseLinks();
  const goal = $("goal").value;
  const limit = Math.min(100, Math.max(1, parseInt($("limit").value, 10) || 1));

  if (!links.length) return showError("Enter at least one URL to search.");
  if (links.some((u) => !isValidUrl(u)))
    return showError("Every link must be a complete URL beginning with http:// or https://.");

  setLoading(true);
  $("progressLog").innerHTML = "";
  $("progressCard").classList.remove("done");
  $("progressTitle").textContent = "Searching supplied links…";
  $("progressCard").hidden = false;
  log(`Visiting up to ${links.length} links until ${limit} listings are collected.`);

  try {
    const pages = Object.fromEntries(links.map((u) => [u, u]));
    const listings = await collectFromPages(pages, goal, limit, log);
    renderLinks(links);
    renderResults(listings, limit);
    $("progressCard").classList.add("done");
    $("progressTitle").textContent = "Search complete";
    record(`Search completed — ${listings.length} listings from ${links.length} link${links.length > 1 ? "s" : ""}`, { ok: true, listings: listings.length, links: links.length });
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    $("progressCard").hidden = true;
    showError(`Could not complete the search: ${err.message}`);
    record(`Search failed — ${err.message}`, { ok: false });
  } finally {
    setLoading(false);
  }
});

/* ───────── Controls ───────── */
const limitInput = $("limit");
$("minus").addEventListener("click", () => { limitInput.value = Math.max(1, (+limitInput.value || 1) - 1); syncMeta(); });
$("plus").addEventListener("click", () => { limitInput.value = Math.min(100, (+limitInput.value || 1) + 1); syncMeta(); });
limitInput.addEventListener("input", syncMeta);
$("links").addEventListener("input", syncMeta);

document.querySelectorAll(".preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".preset").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    $("goal").value = btn.dataset.goal;
    $("search").scrollIntoView({ behavior: "smooth" });
    $("links").focus({ preventScroll: true });
  });
});

$("loadExample").addEventListener("click", () => {
  $("links").value = "https://example.com/careers\nhttps://another.example/jobs";
  syncMeta();
  $("search").scrollIntoView({ behavior: "smooth" });
});

$("downloadBtn").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(state.listings, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "listings.json";
  a.click();
  URL.revokeObjectURL(a.href);
});

$("clearHistory").addEventListener("click", () => {
  store = { searches: 0, ok: 0, listings: 0, links: 0, history: [] };
  renderStats();
});

/* ───────── Sidebar: mobile toggle + active section highlight ───────── */
$("menuBtn").addEventListener("click", () => $("sidebar").classList.toggle("open"));
document.querySelectorAll(".nav-item[data-target]").forEach((a) =>
  a.addEventListener("click", () => $("sidebar").classList.remove("open"))
);

const navItems = [...document.querySelectorAll(".nav-item[data-target]")];
const sections = navItems.map((n) => $(n.dataset.target)).filter(Boolean);
function updateActive() {
  let current = "top";
  const y = window.scrollY + 140;
  sections.forEach((s) => { if (!s.hidden && s.offsetTop <= y) current = s.id; });
  if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) current = "activity";
  navItems.forEach((n) => n.classList.toggle("active", n.dataset.target === current));
}
window.addEventListener("scroll", updateActive, { passive: true });

renderStats();
syncMeta();
updateActive();

// Default "Information to collect" comes from backend.models.DEFAULT_GOAL.
fetch("/api/config")
  .then((r) => r.json())
  .then((c) => { if (c.default_goal) $("goal").value = c.default_goal; })
  .catch(() => {});
