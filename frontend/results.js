// Results page: pages visited, listings table (or raw result for a single page), filter, JSON download.
const rows = store.results;

function download(data, name) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

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

function cell(value, column) {
  const td = document.createElement("td");
  if (value == null) return td;
  if (column === "match_score") {
    const b = document.createElement("span");
    b.className = "score " + (value >= 70 ? "hi" : value >= 40 ? "mid" : "lo");
    b.textContent = value + "%";
    td.appendChild(b);
    return td;
  }
  if (typeof value === "string" && isValidUrl(value)) {
    const a = document.createElement("a");
    a.href = value; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = value;
    td.appendChild(a);
  } else if (typeof value === "object") td.textContent = JSON.stringify(value);
  else td.textContent = String(value);
  return td;
}

const WIDE = ["title", "product_name", "required_skills", "matched_skills", "missing_skills", "summary"];

function drawTable(list) {
  // Most useful columns first; "source" (the page it came from) last.
  const FIRST = ["match_score", "title", "product_name", "organization", "store", "location", "remote", "apply_link", "link", "product_link", "price", "date", "deadline", "matched_skills", "missing_skills", "experience_required", "category", "required_skills"];
  const all = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const columns = [...FIRST.filter((c) => all.includes(c)), ...all.filter((c) => !FIRST.includes(c) && c !== "source"), ...all.filter((c) => c === "source")];
  const thead = $("table").querySelector("thead");
  const tbody = $("table").querySelector("tbody");
  thead.innerHTML = ""; tbody.innerHTML = "";
  const head = document.createElement("tr");
  columns.forEach((c) => { const th = document.createElement("th"); if (WIDE.includes(c)) th.style.minWidth = "220px"; th.textContent = c.replace(/_/g, " "); head.appendChild(th); });
  thead.appendChild(head);
  list.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => { const td = cell(row[c], c); if (WIDE.includes(c)) td.style.minWidth = "220px"; tr.appendChild(td); });
    tbody.appendChild(tr);
  });
}

if (store.mode === "single" && store.raw !== undefined) {
  // scrape_one: the raw run result (None when the run did not complete)
  if ((store.pages || []).length) renderLinks(store.pages);
  $("rawBox").hidden = false;
  $("rawTitle").textContent = store.completed ? "Result" : "Run did not complete";
  $("rawJson").textContent = store.raw === null ? "No result was returned." : JSON.stringify(store.raw, null, 2);
  $("rawDownload").hidden = store.raw === null;
  $("rawDownload").addEventListener("click", () => download(store.raw, "result.json"));
} else if (rows === null) {
  $("noSearch").hidden = false;
} else {
  renderLinks(store.pages || []);
  $("results").hidden = false;
  $("resultsTitle").textContent = store.mode === "links"
    ? `Results (${rows.length} of up to ${store.limit})`
    : `Results (${rows.length})${store.note ? " — " + store.note : ""}`;
  const empty = rows.length === 0;
  $("empty").hidden = !empty;
  $("tableWrap").hidden = empty;
  $("downloadBtn").hidden = empty;
  $("filter").hidden = empty;
  if (!empty) drawTable(rows);
}

$("filter").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  drawTable(q ? rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q)) : rows);
});
$("downloadBtn").addEventListener("click", () => download(rows, "listings.json"));
