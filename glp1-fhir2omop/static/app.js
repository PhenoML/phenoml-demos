/* GLP-1 Cohort Studio frontend — plain JS, no build step. */
"use strict";

const MED_SLOT = { zepbound: "s1", wegovy: "s2", ozempic: "s3" }; // fixed by entity, never cycled
const MED_VAR = { zepbound: "--series-1", wegovy: "--series-2", ozempic: "--series-3" };

const state = {
  cohort: [],
  selected: new Set(),
  omop: null,
  activeTab: null,
  polling: {},
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts ? {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  } : undefined);
  if (!r.ok) throw new Error(`${path} -> ${r.status}: ${(await r.text()).slice(0, 300)}`);
  return r.json();
}

/* ============================ cohort ============================ */
async function loadConfig() {
  try {
    const cfg = await api("/api/config");
    $("provider-chip").textContent = `provider: ${cfg.provider_id}`;
  } catch { $("provider-chip").textContent = "provider: (backend unreachable)"; }
}

async function loadCohort() {
  $("cohort-body").innerHTML = `<tr><td colspan="7" class="empty">loading cohort…</td></tr>`;
  try {
    const data = await api("/api/cohort");
    state.cohort = data.patients || [];
    for (const id of [...state.selected]) {
      if (!state.cohort.some((p) => p.patient_id === id)) state.selected.delete(id);
    }
    renderCohort(data.hint);
  } catch (e) {
    $("cohort-body").innerHTML = `<tr><td colspan="7" class="empty">failed to load: ${esc(e.message)}</td></tr>`;
  }
}

function medChip(m) {
  return `<span class="chip" style="--chip-hue: var(${MED_VAR[m.key] || "--series-1"})">
    <span class="dot ${MED_SLOT[m.key] || "s1"}"></span>${esc(m.brand)}
    <span class="muted">${esc(m.rxnorm)}</span></span>`;
}

function renderCohort(hint) {
  $("cohort-count").textContent = state.cohort.length
    ? `— ${state.cohort.length} patients on a demo GLP-1` : "";
  if (!state.cohort.length) {
    $("cohort-body").innerHTML =
      `<tr><td colspan="7" class="empty">${esc(hint || "No cohort found — run seed_glp1_data.py first.")}</td></tr>`;
    updateActionLabels();
    return;
  }
  $("cohort-body").innerHTML = state.cohort.map((p) => {
    const notes = p.notes.map((n) =>
      `<span class="chip neutral">${n.kind === "followup" ? "follow-up" : "initial"} · ${esc((n.date || "").slice(0, 10))}</span>`
    ).join(" ");
    const extracted = p.extracted.length
      ? p.extracted.map((x) => `<span class="chip finding" title="${esc(x.type)}/${esc(x.id)}">${esc(x.label)}</span>`).join(" ")
      : `<span class="muted">—</span>`;
    return `<tr class="clickable" data-pid="${esc(p.patient_id)}">
      <td class="chk"><input type="checkbox" data-pid="${esc(p.patient_id)}"
          ${state.selected.has(p.patient_id) ? "checked" : ""}></td>
      <td><strong>${esc(p.name)}</strong><span class="patient-id">${esc(p.patient_id)}</span></td>
      <td>${p.meds.map(medChip).join(" ")}</td>
      <td>${esc((p.meds[0]?.authoredOn || "").slice(0, 10))}</td>
      <td>${p.diagnoses.map(esc).join("<br>") || `<span class="muted">—</span>`}</td>
      <td>${notes || `<span class="muted">—</span>`}</td>
      <td>${extracted}</td>
    </tr>`;
  }).join("");

  document.querySelectorAll('#cohort-body input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener("click", (ev) => {
      ev.stopPropagation();
      cb.checked ? state.selected.add(cb.dataset.pid) : state.selected.delete(cb.dataset.pid);
      updateActionLabels();
    });
  });
  document.querySelectorAll("#cohort-body tr.clickable").forEach((tr) => {
    tr.addEventListener("click", () => openDrawer(tr.dataset.pid));
  });
  updateActionLabels();
}

function setSelection(pred) {
  state.selected = new Set(state.cohort.filter(pred).map((p) => p.patient_id));
  renderCohort();
}

function selectedRows() {
  return state.cohort.filter((p) => state.selected.has(p.patient_id));
}

function docsInScope(rows) {
  const scope = $("extract-scope").value;
  return rows.flatMap((p) => p.notes.filter((n) => scope === "all" || n.kind === "followup"))
             .map((n) => n.id);
}

function updateActionLabels() {
  const rows = selectedRows();
  $("btn-extract").textContent = `Run lang2fhir on selected (${rows.length} pt / ${docsInScope(rows).length} notes)`;
  $("btn-omop").textContent = `Run fhir2omop on selected (${rows.length} pt)`;
  $("btn-extract").disabled = !rows.length;
  $("btn-omop").disabled = !rows.length;
  $("chk-all").checked = rows.length && rows.length === state.cohort.length;
}

/* ============================ notes drawer ============================ */
function highlightFindings(text) {
  // demo affordance: make the buried AE language easy to spot in the raw note
  return esc(text).replace(/(headaches?|nausea)/gi, "<mark>$1</mark>");
}

async function openDrawer(pid) {
  const p = state.cohort.find((r) => r.patient_id === pid);
  if (!p) return;
  $("drawer-title").textContent = `${p.name} — progress notes`;
  $("drawer-body").innerHTML = `<p class="muted">loading ${p.notes.length} note(s)…</p>`;
  $("drawer").hidden = false; $("drawer-backdrop").hidden = false;
  const cards = [];
  for (const n of p.notes) {
    try {
      const d = await api(`/api/notes/${n.id}`);
      const ex = d.extracted.length
        ? `<div class="extract-line"><span class="muted">extracted:</span>
             ${d.extracted.map((x) => `<span class="chip finding">${esc(x.label)}</span>`).join("")}</div>`
        : `<div class="extract-line"><span class="muted">nothing extracted from this note yet</span></div>`;
      cards.push(`<div class="note-card">
        <div class="note-head">
          <strong>${esc(d.title || "progress note")}</strong>
          <span class="muted">${esc(d.kind)} · ${esc((d.date || "").slice(0, 10))} · ${esc(n.id)}</span>
        </div>
        <pre>${highlightFindings(d.text)}</pre>
        ${ex}
        <div class="toolbar right">
          <button class="ghost btn-note-extract" data-doc="${esc(n.id)}">Run lang2fhir on this note</button>
        </div>
      </div>`);
    } catch (e) {
      cards.push(`<div class="note-card"><span class="muted">failed to load note ${esc(n.id)}: ${esc(e.message)}</span></div>`);
    }
    $("drawer-body").innerHTML = cards.join("") || `<p class="muted">no notes</p>`;
  }
  document.querySelectorAll(".btn-note-extract").forEach((b) =>
    b.addEventListener("click", () => { closeDrawer(); startExtract([b.dataset.doc]); }));
}

function closeDrawer() { $("drawer").hidden = true; $("drawer-backdrop").hidden = true; }

/* ============================ jobs ============================ */
function renderJob(el, job) {
  const icon = job.status === "done" ? `<span class="ok">✓ done</span>`
    : job.status === "error" ? `<span class="err">✕ failed</span>`
    : `<span>⟳ running…</span>`;
  const pct = job.total ? Math.round((100 * job.done) / job.total) : 0;
  el.innerHTML = `
    <div class="status">${icon}<span class="muted">${esc(job.kind)} · ${job.done}/${job.total}</span></div>
    <div class="progress"><div style="width:${pct}%"></div></div>
    ${job.error ? `<div class="status"><span class="err">${esc(job.error)}</span></div>` : ""}
    <pre class="log">${esc((job.log || []).slice(-40).join("\n"))}</pre>`;
}

function pollJob(jobId, el, onDone) {
  el.hidden = false;
  clearInterval(state.polling[el.id]);
  state.polling[el.id] = setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      renderJob(el, job);
      if (job.status !== "running") {
        clearInterval(state.polling[el.id]);
        onDone && onDone(job);
      }
    } catch (e) {
      clearInterval(state.polling[el.id]);
      el.innerHTML = `<div class="status"><span class="err">poll failed: ${esc(e.message)}</span></div>`;
    }
  }, 1200);
}

/* ============================ lang2fhir ============================ */
async function startExtract(docIds) {
  if (!docIds.length) return;
  $("btn-extract").disabled = true;
  try {
    const { job_id } = await api("/api/extract", { doc_ids: docIds, force: $("extract-force").checked });
    renderJob($("job-extract"), { kind: "lang2fhir", status: "running", done: 0, total: docIds.length, log: [`submitted ${docIds.length} note(s)`] });
    pollJob(job_id, $("job-extract"), () => { loadCohort(); });
  } catch (e) {
    $("job-extract").hidden = false;
    $("job-extract").innerHTML = `<div class="status"><span class="err">${esc(e.message)}</span></div>`;
  } finally {
    $("btn-extract").disabled = false;
  }
}

/* ============================ fhir2omop ============================ */
async function startOmop() {
  const pids = [...state.selected];
  if (!pids.length) return;
  $("btn-omop").disabled = true;
  try {
    const { job_id } = await api("/api/omop", { patient_ids: pids });
    renderJob($("job-omop"), { kind: "fhir2omop", status: "running", done: 0, total: 6, log: [`submitted ${pids.length} patient(s)`] });
    pollJob(job_id, $("job-omop"), (job) => {
      if (job.status === "done") { state.omop = job.result; renderOmop(); }
    });
  } catch (e) {
    $("job-omop").hidden = false;
    $("job-omop").innerHTML = `<div class="status"><span class="err">${esc(e.message)}</span></div>`;
  } finally {
    $("btn-omop").disabled = false;
  }
}

const TABLE_ORDER = ["person", "visit_occurrence", "condition_occurrence", "drug_exposure",
                     "procedure_occurrence", "measurement", "observation"];

function renderOmop() {
  const res = state.omop;
  if (!res) return;
  $("omop-card").hidden = false;
  const stats = res.stats || {};
  const ms = stats.mapping_status || {};
  const totalMap = Object.values(ms).reduce((a, b) => a + b, 0);
  const mapped = Object.entries(ms)
    .filter(([k]) => !["UNMAPPED", "UNCHECKED", "UNKNOWN"].includes(k))
    .reduce((a, [, v]) => a + v, 0); // ALREADY_STANDARD, MAPPED, ... count as resolved

  const tiles = [
    { l: "patients sent", v: stats.patients ?? "—" },
    { l: "FHIR resources sent", v: stats.resources_sent ?? "—" },
    ...TABLE_ORDER.filter((t) => (stats.rows || {})[t] != null)
      .map((t) => ({ l: `${t} rows`, v: stats.rows[t] })),
    { l: "codings mapped to standard concepts", v: totalMap ? `${mapped}/${totalMap}` : "—" },
  ];
  $("omop-tiles").innerHTML = tiles.map((t) =>
    `<div class="tile"><div class="v">${esc(t.v)}</div><div class="l">${esc(t.l)}</div></div>`).join("");
  $("omop-meta").textContent = res.vocab_version ? `OMOP vocab ${res.vocab_version}` : "";

  const tabs = [...TABLE_ORDER.filter((t) => res.tables[t]),
                ...Object.keys(res.tables).filter((t) => !TABLE_ORDER.includes(t))];
  if (res.mappings?.length) tabs.push("mappings");
  if (res.dropped?.length) tabs.push("dropped");
  state.activeTab = tabs.includes(state.activeTab) ? state.activeTab : tabs[0];
  $("omop-tabs").innerHTML = tabs.map((t) => {
    const n = t === "mappings" ? res.mappings.length : t === "dropped" ? res.dropped.length : res.tables[t].length;
    return `<button data-tab="${esc(t)}" class="${t === state.activeTab ? "active" : ""}">${esc(t)} (${n})</button>`;
  }).join("");
  document.querySelectorAll("#omop-tabs button").forEach((b) =>
    b.addEventListener("click", () => { state.activeTab = b.dataset.tab; renderOmop(); }));

  renderOmopTable();
  $("omop-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function activeRows() {
  const res = state.omop;
  if (!res || !state.activeTab) return [];
  if (state.activeTab === "mappings") return res.mappings || [];
  if (state.activeTab === "dropped") return res.dropped || [];
  return res.tables[state.activeTab] || [];
}

function renderOmopTable() {
  const rows = activeRows().map((r) =>
    Object.fromEntries(Object.entries(r).map(([k, v]) =>
      [k, (v && typeof v === "object") ? JSON.stringify(v) : v])));
  const head = $("omop-table").querySelector("thead");
  const body = $("omop-table").querySelector("tbody");
  if (!rows.length) { head.innerHTML = ""; body.innerHTML = `<tr><td class="empty">no rows</td></tr>`; return; }
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const numeric = Object.fromEntries(cols.map((c) => [c, rows.every((r) => r[c] == null || typeof r[c] === "number")]));
  head.innerHTML = `<tr>${cols.map((c) => `<th class="${numeric[c] ? "num" : ""}">${esc(c)}</th>`).join("")}</tr>`;
  body.innerHTML = rows.map((r) =>
    `<tr>${cols.map((c) => `<td class="${numeric[c] ? "num" : ""}">${esc(r[c] ?? "")}</td>`).join("")}</tr>`).join("");
}

/* ============================ downloads ============================ */
function download(name, mime, content) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function csvOfActive() {
  const rows = activeRows().map((r) =>
    Object.fromEntries(Object.entries(r).map(([k, v]) =>
      [k, (v && typeof v === "object") ? JSON.stringify(v) : v])));
  if (!rows.length) return "";
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const cell = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n");
}

/* ============================ NL cohort (cohort.analyze) ============================ */
async function analyzeCohort() {
  const text = $("nl-input").value.trim();
  if (!text) return;
  const out = $("nl-result");
  out.hidden = false;
  out.innerHTML = "analyzing cohort description…";
  $("btn-analyze").disabled = true;
  try {
    const res = await api("/api/cohort/analyze", { text });
    const inCohort = new Set(state.cohort.map((p) => p.patient_id));
    const hits = (res.patient_ids || []).filter((id) => inCohort.has(id));
    state.selected = new Set(hits);
    renderCohort();
    out.innerHTML = `${res.queries.map((q) =>
        `<span class="q">${q.exclude ? "EXCLUDE " : ""}${esc(q.resource_type)}?${esc(q.search_params)}` +
        ` <span class="muted">(${q.error ? esc(q.error) : `${q.matched_patients} pts`})</span></span>`).join("")}
      <strong>${res.patient_ids?.length ?? 0}</strong> matching patients on the server,
      <strong>${hits.length}</strong> in this GLP-1 cohort — selected.`;
  } catch (e) {
    out.innerHTML = `<span class="q">failed: ${esc(e.message)}</span>`;
  } finally {
    $("btn-analyze").disabled = false;
  }
}

/* ============================ wire-up ============================ */
$("btn-refresh").addEventListener("click", loadCohort);
$("chk-all").addEventListener("click", () => setSelection(() => $("chk-all").checked));
document.querySelectorAll(".sel-btn").forEach((b) => b.addEventListener("click", () => {
  const k = b.dataset.sel;
  if (k === "all") setSelection(() => true);
  else if (k === "none") setSelection(() => false);
  else setSelection((p) => p.meds.some((m) => m.key === k));
}));
$("extract-scope").addEventListener("change", updateActionLabels);
$("btn-extract").addEventListener("click", () => startExtract(docsInScope(selectedRows())));
$("btn-omop").addEventListener("click", startOmop);
$("btn-analyze").addEventListener("click", analyzeCohort);
$("nl-input").addEventListener("keydown", (e) => { if (e.key === "Enter") analyzeCohort(); });
$("drawer-close").addEventListener("click", closeDrawer);
$("drawer-backdrop").addEventListener("click", closeDrawer);
$("btn-dl-json").addEventListener("click", () =>
  state.omop && download("fhir2omop_result.json", "application/json", JSON.stringify(state.omop, null, 2)));
$("btn-dl-csv").addEventListener("click", () =>
  state.omop && download(`omop_${state.activeTab}.csv`, "text/csv", csvOfActive()));

loadConfig();
loadCohort();
