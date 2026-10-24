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

function drawTable(list) {
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const thead = $("table").querySelector("thead");
  const tbody = $("table").querySelector("tbody");
  thead.innerHTML = ""; tbody.innerHTML = "";
  const head = document.createElement("tr");
  columns.forEach((c) => { const th = document.createElement("th"); th.textContent = c.replace(/_/g, " "); head.appendChild(th); });
  thead.appendChild(head);
  list.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => tr.appendChild(cell(row[c])));
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
