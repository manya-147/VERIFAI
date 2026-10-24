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
