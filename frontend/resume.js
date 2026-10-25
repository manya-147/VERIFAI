// Resume Match: resume (PDF / text) -> profile (skills, experience, roles) -> TinyFish search + scrape -> ranked results.
//   POST /api/resume/parse  analyses the resume
//   POST /api/run {mode:"resume"} searches the web for fitting jobs and scores each one against the profile
const PAGE = "resume";
const READY = "Ready";
let tab = "file", file = null, resumeText = "";

const splitList = (v) => [...new Set(v.split(/[,\n]/).map((s) => s.trim()).filter(Boolean))];
const showParseError = (m) => { $("parseError").textContent = m; $("parseError").hidden = !m; };
const showError = (m) => { $("error").textContent = m; $("error").hidden = !m; };

function log(msg) { const li = document.createElement("li"); li.textContent = msg; $("progressLog").appendChild(li); }
function busy(btn, on, text) {
  btn.disabled = on;
  btn.querySelector(".spinner").hidden = !on;
  const label = btn.querySelector(".label");
  if (on) { label.dataset.text = label.textContent; label.textContent = text; } else if (label.dataset.text) label.textContent = label.dataset.text;
}

/* ───────── Step 1: input ───────── */
function setTab(name) {
  tab = name;
  $("tabFile").classList.toggle("active", name === "file");
  $("tabText").classList.toggle("active", name === "text");
  $("paneFile").hidden = name !== "file";
  $("paneText").hidden = name !== "text";
  showParseError("");
}
$("tabFile").addEventListener("click", () => setTab("file"));
$("tabText").addEventListener("click", () => setTab("text"));

function pickFile(f) {
  showParseError("");
  if (!f) return;
  const ok = /\.(pdf|txt|md)$/i.test(f.name) || /pdf|text/.test(f.type);
  if (!ok) { file = null; return showParseError("Please choose a PDF or a .txt file — or paste the text instead."); }
  if (f.size > 10 * 1024 * 1024) { file = null; return showParseError("That file is larger than 10 MB."); }
  file = f;
  $("dropTitle").textContent = f.name;
  $("dropHint").textContent = `${(f.size / 1024).toFixed(0)} KB · click to choose a different file`;
  $("dropzone").classList.add("has-file");
}
$("fileInput").addEventListener("change", (e) => pickFile(e.target.files[0]));
["dragenter", "dragover"].forEach((ev) => $("dropzone").addEventListener(ev, (e) => { e.preventDefault(); $("dropzone").classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => $("dropzone").addEventListener(ev, (e) => { e.preventDefault(); $("dropzone").classList.remove("drag"); }));
$("dropzone").addEventListener("drop", (e) => pickFile(e.dataTransfer.files[0]));

const readFile = (f, as) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(r.result);
  r.onerror = () => reject(new Error("Could not read that file."));
  as === "text" ? r.readAsText(f) : r.readAsDataURL(f);
});

$("analyzeBtn").addEventListener("click", async () => {
  showParseError("");
  let body;
  try {
    if (tab === "file") {
      if (!file) return showParseError("Choose a PDF or .txt file first, or switch to “Paste text”.");
      body = /\.pdf$/i.test(file.name) || file.type === "application/pdf" ? { pdf_b64: await readFile(file, "data") } : { text: await readFile(file, "text") };
    } else {
      const text = $("resumeText").value.trim();
      if (text.length < 40) return showParseError("Paste more of your resume — at least a few lines.");
      body = { text };
    }
  } catch (err) { return showParseError(err.message); }

  busy($("analyzeBtn"), true, "Reading…");
  try {
    const res = await fetch("/api/resume/parse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText);
    resumeText = data.text;
    showProfile(data.profile);
    store.form.resume = { profile: data.profile };
    saveStore();
  } catch (err) {
    showParseError(err.message || "Could not analyse the resume.");
  } finally { busy($("analyzeBtn"), false); }
});

/* ───────── Step 2: profile ───────── */
function drawChips() {
  const box = $("skillChips");
  box.innerHTML = "";
  splitList($("skills").value).forEach((s) => { const c = document.createElement("span"); c.className = "chip"; c.textContent = s; box.appendChild(c); });
}
$("skills").addEventListener("input", drawChips);

function showProfile(p) {
  $("searchForm").hidden = false;
  $("profileName").textContent = p.name ? `· ${p.name}` : "";
  $("roles").value = (p.roles || []).join(", ");
  $("skills").value = (p.skills || []).join(", ");
  $("years").value = p.years ?? 0;
  $("level").value = p.level || "entry";
  $("jobType").value = p.job_type || "both";
  if (p.location) $("region").value = p.location;
  $("education").textContent = p.education || "";
  $("eduBox").hidden = !p.education;
  $("parseWarn").textContent = p.warning || "";
  $("parseWarn").hidden = !p.warning;
  drawChips();
  $("searchForm").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("minus").addEventListener("click", () => { $("limit").value = Math.max(1, (+$("limit").value || 1) - 1); });
$("plus").addEventListener("click", () => { $("limit").value = Math.min(30, (+$("limit").value || 1) + 1); });

/* ───────── Search ───────── */
$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  const payload = {
    mode: "resume",
    roles: splitList($("roles").value),
    skills: splitList($("skills").value),
    years: parseFloat($("years").value) || 0,
    level: $("level").value,
    job_type: $("jobType").value,
    region: $("region").value.trim(),
    limit: Math.min(30, Math.max(1, parseInt($("limit").value, 10) || 1)),
  };
  if (!payload.skills.length && !payload.roles.length) return showError("Add at least one skill or target role.");

  busy($("submitBtn"), true, "Working…");
  $("statusPill").textContent = "Running"; $("statusPill").classList.add("busy");
  $("viewResults").hidden = true; $("progressLog").innerHTML = "";
  $("progressCard").classList.remove("done"); $("progressTitle").textContent = "Working…"; $("progressCard").hidden = false;
  $("progressCard").scrollIntoView({ behavior: "smooth", block: "nearest" });

  let pages = []; const partial = [];
  const startedAt = Date.now();
  const ticker = setInterval(() => {
    const s = Math.floor((Date.now() - startedAt) / 1000);
    $("progressTitle").textContent = `Working… ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
  const controller = new AbortController();
  const cutoff = setTimeout(() => controller.abort(), 8 * 60 * 1000);
  const form = { profile: { ...(store.form.resume?.profile || {}), roles: payload.roles, skills: payload.skills, years: payload.years, level: payload.level, job_type: payload.job_type, location: payload.region } };
  const finish = (rows, note, text, ok) => {
    store.mode = "resume"; store.pages = pages; store.limit = payload.limit; store.raw = undefined;
    store.results = rows; store.note = note; store.form.resume = form;
    record(text, { ok, listings: rows.length, links: pages.length });
    saveRun({ mode: "resume", text, ok, query: payload.roles.join(", "), pages, results: rows, limit: payload.limit, note, form });
    saveStore();
    $("progressCard").classList.add("done");
    $("viewResults").hidden = false;
    setTimeout(() => { location.href = "results.html"; }, 900);
  };
  try {
    const result = await run(payload, log, (p) => { pages = p; }, controller.signal, (batch) => {
      partial.push(...batch); log(`${partial.length} listing${partial.length === 1 ? "" : "s"} collected so far`);
    });
    const rows = result.listings || [];
    $("progressTitle").textContent = "Complete";
    finish(rows, result.note || "", `Resume match completed — ${rows.length} listings from ${pages.length} page${pages.length === 1 ? "" : "s"}`, true);
  } catch (err) {
    if (partial.length) {
      $("progressTitle").textContent = "Partial results";
      return finish(partial.slice(0, 100), "Partial results (not ranked): the run was cut off before every page finished.", `Resume match partial — ${partial.length} listings`, true);
    }
    $("progressCard").hidden = true;
    showError(`Could not complete the search: ${err.name === "AbortError" ? "it took longer than 8 minutes, so it was stopped. Try fewer pages." : err.message}`);
    record(`Resume match failed — ${err.message}`, { ok: false });
    saveRun({ mode: "resume", text: `Resume match failed — ${err.message}`, ok: false, query: payload.roles.join(", ") });
  } finally {
    clearInterval(ticker); clearTimeout(cutoff);
    busy($("submitBtn"), false);
    $("statusPill").textContent = READY; $("statusPill").classList.remove("busy");
  }
});

// Restore the last profile in this tab.
const last = store.form.resume?.profile;
if (last && (last.skills || []).length) showProfile(last);
