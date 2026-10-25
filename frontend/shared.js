// Shared by every page: sidebar, session state (like st.session_state), small helpers.
// State lives in sessionStorage so it follows you between pages and resets when the tab closes.

const $ = (id) => document.getElementById(id);

/* ───────── Session state ───────── */
const STORE_KEY = "opportunityFinder.session";
const emptyStore = () => ({
  searches: 0, ok: 0, listings: 0, links: 0, history: [],
  mode: null,      // which backend function produced the latest result
  pages: null,     // pages visited by the latest successful run (st.session_state["target_pages"])
  results: null,   // listings of the latest successful run      (st.session_state["listings"])
  raw: undefined,  // raw TinyFish result of a single-page run
  limit: 10,       // limit used for that run                    (st.session_state["result_limit"])
  form: {},        // last values entered on each page
});

let store = emptyStore();
try { store = { ...emptyStore(), ...JSON.parse(sessionStorage.getItem(STORE_KEY) || "{}") }; } catch {}

function saveStore() { try { sessionStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch {} }

function record(text, { ok, listings = 0, links = 0 }) {
  store.searches += 1;
  if (ok) store.ok += 1;
  store.listings += listings;
  store.links += links;
  store.history.unshift({ text, ts: Date.now(), ok });
  store.history = store.history.slice(0, 50);
  saveStore();
}

function clearHistory() {
  store = emptyStore();
  saveStore();
  try { localStorage.removeItem(RUNS_KEY); } catch {}
}

/* ───────── Saved runs (kept in localStorage so they survive closing the tab) ───────── */
const RUNS_KEY = "opportunityFinder.runs";
const MAX_RUNS = 30;

function loadRuns() {
  try { const r = JSON.parse(localStorage.getItem(RUNS_KEY) || "[]"); return Array.isArray(r) ? r : []; } catch { return []; }
}
function writeRuns(runs) {
  // If storage is full, drop the oldest runs until it fits.
  for (let list = runs.slice(0, MAX_RUNS); ; list.pop()) {
    try { localStorage.setItem(RUNS_KEY, JSON.stringify(list)); return; } catch { if (!list.length) return; }
  }
}
// run: {mode, text, ok, query, pages, results, raw, limit, note, completed, form}
function saveRun(run) {
  writeRuns([{ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), ts: Date.now(), ...run }, ...loadRuns()]);
}
function deleteRun(id) { writeRuns(loadRuns().filter((r) => r.id !== id)); }

// Put a saved run back as the "latest result" and open it on the Results page.
function loadRun(id) {
  const r = loadRuns().find((x) => x.id === id);
  if (!r) return false;
  store.mode = r.mode; store.pages = r.pages || []; store.results = r.results ?? null;
  store.raw = r.raw; store.limit = r.limit || 10; store.note = r.note || ""; store.completed = r.completed;
  if (r.form) store.form[r.mode === "links" ? "search" : r.mode === "single" ? "single" : r.mode] = r.form;
  saveStore();
  return true;
}

const RUN_LABEL = { links: "search", single: "single", sources: "sources", discover: "discover", resume: "resume" };

function renderSavedRuns(listEl, countEl) {
  const runs = loadRuns();
  countEl.textContent = `${runs.length} saved`;
  listEl.innerHTML = "";
  if (!runs.length) {
    listEl.innerHTML = '<li class="muted">No saved runs yet — run a search and it will show up here.</li>';
    return;
  }
  runs.forEach((r) => {
    const li = document.createElement("li");
    li.className = "run" + (r.ok === false ? " fail" : "");
    const info = document.createElement("div");
    info.className = "run-info";
    const title = document.createElement("div");
    title.className = "run-title";
    title.textContent = r.text;
    const n = r.results ? r.results.length : null;
    const meta = document.createElement("small");
    meta.textContent = [RUN_LABEL[r.mode] || r.mode, n != null ? `${n} result${n === 1 ? "" : "s"}` : null, timeAgo(r.ts)].filter(Boolean).join(" · ");
    info.append(title, meta);
    if (r.query) { const q = document.createElement("em"); q.textContent = r.query; info.appendChild(q); }

    const actions = document.createElement("div");
    actions.className = "run-actions";
    if (r.ok !== false) {
      const load = document.createElement("button");
      load.type = "button"; load.className = "btn btn-teal btn-sm"; load.textContent = "↪ Load";
      load.addEventListener("click", () => { if (loadRun(r.id)) location.href = "results.html"; });
      actions.appendChild(load);
    }
    const del = document.createElement("button");
    del.type = "button"; del.className = "btn btn-ghost btn-sm"; del.textContent = "🗑 Delete";
    del.addEventListener("click", () => { deleteRun(r.id); renderSavedRuns(listEl, countEl); });
    actions.appendChild(del);
    li.append(info, actions);
    listEl.appendChild(li);
  });
}

/* ───────── Streaming run (POST /api/run, NDJSON) ───────── */
async function run(payload, onProgress, onPages, signal, onPartial) {
  const res = await fetch("/api/run", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", result = null;
  const handle = (line) => {
    if (!line.trim()) return;
    const msg = JSON.parse(line);
    if (msg.type === "progress") onProgress(msg.message);
    else if (msg.type === "pages") onPages(msg.pages);
    else if (msg.type === "partial") onPartial && onPartial(msg.listings || []);
    else if (msg.type === "result") result = msg;
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
  if (!result) throw new Error("The server closed the connection before returning results.");
  return result;
}

/* ───────── Helpers ───────── */
function isValidUrl(value) {
  try {
    const u = new URL(value);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host;
  } catch { return false; }
}

function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function renderActivity(listEl, limit) {
  listEl.innerHTML = "";
  if (!store.history.length) {
    listEl.innerHTML = '<li class="muted">No activity yet — run your first search.</li>';
    return;
  }
  store.history.slice(0, limit).forEach((h) => {
    const li = document.createElement("li");
    if (h.ok === false) li.className = "fail";
    li.textContent = h.text;
    const small = document.createElement("small");
    small.textContent = timeAgo(h.ts);
    li.appendChild(small);
    listEl.appendChild(li);
  });
}

/* ───────── Sidebar ───────── */
const NAV = [
  ["Overview", [["index.html", "🏠", "Dashboard", "dashboard"]]],
  ["Collect", [
    ["search.html", "🔗", "Search Links", "search"],
    ["single.html", "📄", "Single Page", "single"],
    ["sources.html", "🏢", "Saved Sources", "sources"],
    ["discover.html", "🌍", "Find & Scrape", "discover"],
    ["resume.html", "🎯", "Resume Match", "resume"],
  ]],
  ["Output", [
    ["results.html", "📋", "Results", "results"],
    ["activity.html", "⚡", "Recent Activity", "activity"],
  ]],
];

(function buildSidebar() {
  const current = document.body.dataset.page;
  const side = $("sidebar");
  side.innerHTML = `
    <div class="brand">
      <div class="brand-logo">🔎</div>
      <div><div class="brand-name">Opportunity Finder</div><div class="brand-sub">powered by TinyFish</div></div>
    </div>
    <nav class="nav">
      ${NAV.map(([group, items]) => `
        <div class="nav-group">${group}</div>
        ${items.map(([href, icon, label, id]) =>
          `<a href="${href}" class="nav-item${id === current ? " active" : ""}"><span>${icon}</span>${label}</a>`).join("")}
      `).join("")}
    </nav>
    <div class="sidebar-foot">
      <button class="nav-item" id="clearHistory" type="button"><span>🧹</span>Clear history</button>
    </div>`;

  $("clearHistory").addEventListener("click", () => { clearHistory(); location.reload(); });
  $("menuBtn").addEventListener("click", () => side.classList.toggle("open"));
})();
