// One script for the four collection pages. Each page maps to a function in backend/:
//   search   → backend.collect_from_pages(pages, goal, limit, on_progress)
//   single   → models.scrape_one(url, goal)
//   sources  → models.scrape(PAGES, goal, collection_key, schema)         (backend mode 2)
//   discover → TinyFish().search.query(...) then models.scrape(...)       (backend mode 3)
// server.py runs them and streams NDJSON: {type: progress | pages | result | error}.

const PAGE = document.body.dataset.page;
const MODE = { search: "links", single: "single", sources: "sources", discover: "discover" }[PAGE];
const FIELDS = ["links", "url", "query", "goal", "collection", "limit", "category", "region",
  "includeDomains", "excludeDomains", "afterDate", "beforeDate", "recency", "searchType", "language"].filter((id) => $(id));
let config = {};

function showError(msg) { $("error").textContent = msg; $("error").hidden = !msg; }
function setLoading(on) {
  $("submitBtn").disabled = on;
  document.querySelector("#submitBtn .spinner").hidden = !on;
  $("statusPill").textContent = on ? "Running" : "Ready";
  $("statusPill").classList.toggle("busy", on);
  const label = document.querySelector("#submitBtn .label");
  if (on) { label.dataset.text = label.textContent; label.textContent = "Working…"; }
  else if (label.dataset.text) label.textContent = label.dataset.text;
}
function log(msg) {
  const li = document.createElement("li");
  li.textContent = msg;
  $("progressLog").appendChild(li);
}

function readForm() {
  const value = (id) => ($(id) ? $(id).value : "");
  return {
    mode: MODE,
    links: $("links") ? [...new Set(value("links").split("\n").map((l) => l.trim()).filter(Boolean))] : [],
    url: value("url").trim(),
    query: value("query").trim(),
    goal: value("goal"),
    collection: value("collection").trim(),
    category: value("category") || "auto",
    region: value("region").trim(),
    include_domains: value("includeDomains").trim(),
    exclude_domains: value("excludeDomains").trim(),
    after_date: value("afterDate"),
    before_date: value("beforeDate"),
    recency_minutes: parseInt(value("recency"), 10) || null,
    domain_type: value("searchType"),
    language: value("language").trim(),
    limit: Math.min(100, Math.max(1, parseInt(value("limit"), 10) || 1)),
  };
}

function validate(p) {
  if (MODE === "links") {
    if (!p.links.length) return "Enter at least one URL to search.";
    if (p.links.some((u) => !isValidUrl(u))) return "Every link must be a complete URL beginning with http:// or https://.";
  } else if (MODE === "single") {
    if (!p.url) return "Enter a URL to scrape.";
    if (!isValidUrl(p.url)) return "The link must be a complete URL beginning with http:// or https://.";
  } else if (MODE === "discover") {
    if (!p.query) return "Enter a search query.";
    if (p.after_date && p.before_date && p.after_date > p.before_date) return "“Published after” must be earlier than “Published before”.";
    if (p.recency_minutes != null && (p.recency_minutes < 1 || p.recency_minutes > 5256000)) return "Recency must be between 1 and 5256000 minutes.";
  }
  return "";
}

const WHAT = { links: "Search", single: "Single page", sources: "Saved sources", discover: "Find & scrape" };

$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  const payload = readForm();
  const problem = validate(payload);
  if (problem) return showError(problem);

  setLoading(true);
  $("viewResults").hidden = true;
  $("progressLog").innerHTML = "";
  $("progressCard").classList.remove("done");
  $("progressTitle").textContent = "Working…";
  $("progressCard").hidden = false;
  if (MODE === "links") log(`Visiting up to ${payload.links.length} links until ${payload.limit} listings are collected.`);

  let pages = [];
  const partial = [];   // listings that arrived before the final result
  // Live timer, and a hard stop so the page can never look stuck forever (server limits are ~5 min).
  const startedAt = Date.now();
  const ticker = setInterval(() => {
    const s = Math.floor((Date.now() - startedAt) / 1000);
    $("progressTitle").textContent = `Working… ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
  const controller = new AbortController();
  const cutoff = setTimeout(() => controller.abort(), 8 * 60 * 1000);
  try {
    const result = await run(payload, log, (p) => { pages = p; }, controller.signal, (batch) => {
      partial.push(...batch);
      log(`${partial.length} result${partial.length === 1 ? "" : "s"} collected so far`);
    });

    store.mode = MODE;
    store.pages = pages;
    store.limit = payload.limit;
    store.form[PAGE] = Object.fromEntries(FIELDS.map((id) => [id, $(id).value]));
    let summary;
    if (MODE === "single") {
      store.raw = result.raw ?? null;
      store.results = null;
      store.completed = !!result.completed;
      summary = result.completed ? "Single page scraped" : "Single page run did not complete";
      record(summary, { ok: !!result.completed, links: 1 });
      saveRun({ mode: MODE, text: summary, ok: !!result.completed, query: payload.url, pages, raw: store.raw, results: null, completed: store.completed, limit: payload.limit, form: store.form[PAGE] });
    } else {
      store.raw = undefined;
      store.results = result.listings || [];
      store.note = result.note || "";
      summary = `${WHAT[MODE]} completed — ${store.results.length} listings from ${pages.length} page${pages.length === 1 ? "" : "s"}`;
      record(summary, { ok: true, listings: store.results.length, links: pages.length });
      saveRun({ mode: MODE, text: summary, ok: true, query: payload.query || payload.links[0] || "", pages, results: store.results, limit: payload.limit, note: store.note, form: store.form[PAGE] });
    }
    saveStore();

    $("progressCard").classList.add("done");
    $("progressTitle").textContent = "Complete";
    $("viewResults").hidden = false;
    setTimeout(() => { location.href = "results.html"; }, 900);
  } catch (err) {
    if (MODE !== "single" && partial.length) {
      // Something was cut off (timeout, dropped connection) but we already have results: keep them.
      store.mode = MODE;
      store.pages = pages;
      store.limit = payload.limit;
      store.form[PAGE] = Object.fromEntries(FIELDS.map((id) => [id, $(id).value]));
      store.raw = undefined;
      store.results = partial.slice(0, payload.limit);
      store.note = "Partial results: the run was cut off before every page finished.";
      const text = `${WHAT[MODE]} partial — ${store.results.length} listings`;
      record(text, { ok: true, listings: store.results.length, links: pages.length });
      saveRun({ mode: MODE, text, ok: true, query: payload.query || payload.links[0] || "", pages, results: store.results, limit: payload.limit, note: store.note, form: store.form[PAGE] });
      saveStore();
      $("progressCard").classList.add("done");
      $("progressTitle").textContent = "Partial results";
      $("viewResults").hidden = false;
      setTimeout(() => { location.href = "results.html"; }, 900);
      return;
    }
    $("progressCard").hidden = true;
    const msg = err.name === "AbortError" ? "It took longer than 8 minutes, so it was stopped. Try fewer pages or a more specific search." : err.message;
    showError(`Could not complete the search: ${msg}`);
    const failText = `${WHAT[MODE]} failed — ${err.message}`;
    record(failText, { ok: false });
    saveRun({ mode: MODE, text: failText, ok: false, query: payload.query || payload.url || payload.links[0] || "" });
  } finally {
    clearInterval(ticker);
    clearTimeout(cutoff);
    setLoading(false);
  }
});

/* ───────── Controls ───────── */
if ($("limit")) {
  $("minus").addEventListener("click", () => { $("limit").value = Math.max(1, (+$("limit").value || 1) - 1); });
  $("plus").addEventListener("click", () => { $("limit").value = Math.min(100, (+$("limit").value || 1) + 1); });
}

// Restore what was last used on this page, otherwise take defaults from the backend.
const saved = store.form[PAGE] || {};
FIELDS.forEach((id) => { if (saved[id] != null) $(id).value = saved[id]; });
if ($("advanced") && ["includeDomains", "excludeDomains", "afterDate", "beforeDate", "recency", "searchType", "language"].some((id) => $(id).value)) $("advanced").open = true;

fetch("/api/config")
  .then((r) => r.json())
  .then((c) => {
    config = c;
    const fill = (id, v) => { if ($(id) && !$(id).value && v != null) $(id).value = v; };
    if (PAGE !== "discover") fill("goal", MODE === "links" ? c.default_goal : c.internship_goal);   // DEFAULT_GOAL vs INTERNSHIP_GOAL
    fill("collection", c.default_collection);
    if (PAGE !== "discover") fill("query", c.default_query);   // discover starts empty: it searches anything
    if (PAGE === "discover" && saved.limit == null) $("limit").value = c.default_search_limit;
    if ($("sourcesList")) {
      const entries = Object.entries(c.pages || {});
      $("sourcesCount").textContent = entries.length;
      entries.forEach(([name, url]) => {
        const a = document.createElement("a");
        a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = name;
        a.title = url;
        $("sourcesList").appendChild(a);
      });
    }
  })
  .catch(() => {});
