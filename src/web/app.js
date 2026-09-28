/* Pramaan dashboard — vanilla JS, no build step, no CDN (runs air-gapped). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(1)}%`);
const FIELD_ACTIONS = new Set(["COLLECT_NOW", "COLLECTION_WINDOW_PASSED", "DIGITAL_OVERWRITE", "PERISHABLE", "QUALITY_AT_RISK",
  "COLD_CHAIN_REQUIRED", "TIME_CRITICAL_COLLECTION", "DIGITAL_VOLATILE", "SAFETY_UNLOAD_FIRST", "MANDATED_EXAMINATION"]);
const TIER_COLOR = { P1: "#b3261e", P2: "#b86e00", P3: "#1f6f78", P4: "#6b7280" };
const POLICY_NAME = { recommended: "Pramaan", status_quo: "Status quo", fifo: "FIFO", priority: "Static sort" };
const state = { health: null, cases: [], profiles: [], scenarios: [], data: null, caseId: null, filter: "all", policy: "recommended", loaded: {}, lastAIReview: null };

async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const headers = isForm ? (opts.headers || {}) : { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(path, { ...opts, headers });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = res.statusText;
    if (body && body.detail) msg = Array.isArray(body.detail) ? body.detail.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join("; ") : body.detail;
    throw new Error(msg);
  }
  return body;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast show${err ? " err" : ""}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast"), err ? 6000 : 2800);
}

function fmtHours(h) {
  if (h === null || h === undefined) return "stable";
  if (h <= 0) return "lost";
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} d`;
}
const timeToLoss = (d) => {
  const c = [d.hours_to_risk, d.field_window_remaining_h].filter((x) => x !== null && x !== undefined);
  return c.length ? Math.max(0, Math.min(...c)) : null;
};
const tierChip = (t) => `<span class="tier ${esc(t)}">${esc(t)}</span>`;
const flagChips = (flags, sev = ["critical", "high", "medium", "info"]) =>
  flags.filter((f) => sev.includes(f.severity)).map((f) => `<span class="flag ${esc(f.severity)}" title="${esc(f.message)}">${esc(f.code)}</span>`).join("");

function epiBar(s) {
  const p = 100 * s.weights.probative * s.probative, u = 100 * s.weights.urgency * s.urgency, r = 100 * s.weights.irreplaceable * s.irreplaceable;
  const floor = Math.max(0, s.epi - (p + u + r));
  return `<div class="epi" title="probative ${p.toFixed(1)} + urgency ${u.toFixed(1)} + irreplaceable ${r.toFixed(1)}${floor > 0.5 ? " + statutory floor " + floor.toFixed(1) : ""}">
    <div class="bar"><span class="seg-p" style="width:${p}%"></span><span class="seg-u" style="width:${u}%"></span><span class="seg-r" style="width:${r}%"></span>${floor > 0.5 ? `<span class="seg-f" style="width:${floor}%"></span>` : ""}</div>
    <b>${s.epi.toFixed(1)}</b></div>`;
}

// ---------------------------------------------------------------- chrome
async function loadHealth() {
  try {
    state.health = await api("/api/health");
    const h = state.health;
    const ran = Object.values(h.ai_models || {}).filter((m) => m.last_inference_at).length;
    $("#status").innerHTML = `<span>engine <b>v${esc(h.engine_version)}</b></span><span>KB <b>${esc(h.kb_hash.slice(0, 10))}</b></span>
      <span>AI <b>${ran}/5 ran</b></span><span>MCP <b>${esc(h.mcp_endpoint)}</b></span>`;
  } catch (e) {
    $("#status").textContent = "API unreachable";
  }
}

async function loadCases() {
  try { state.cases = await api("/api/cases"); } catch (e) { return; }
  $("#case-count").textContent = state.cases.length ? `(${state.cases.length})` : "";
  $("#cases").innerHTML = state.cases.map((c) => `<li><a href="#/case/${encodeURIComponent(c.case_id)}" class="${c.case_id === state.caseId ? "active" : ""}">
      <span class="cref">${esc(c.case_ref)}</span>
      <span class="cmeta">${tierChip("P1")} ${c.counts.P1 ?? 0} · ${esc(c.crime_type.replace(/_/g, " "))} · <span class="mono">${esc(c.case_id.slice(-5))}</span></span></a></li>`).join("")
    || `<li class="note" style="padding:8px 10px">No cases yet — run a triage.</li>`;
}

function setNav(key) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === key));
}

// ---------------------------------------------------------------- intake
function toLocalInput(iso) { return iso ? String(iso).slice(0, 16) : ""; }
function fromLocalInput(v) { return v ? `${v}:00+05:30` : null; }

async function showNew() {
  setNav("new"); state.caseId = null; loadCases();
  if (!state.profiles.length) state.profiles = await api("/api/knowledge/crime-profiles");
  if (!state.scenarios.length) state.scenarios = await api("/api/scenarios");
  $("#main").innerHTML = `
  <div class="eyebrow">New triage</div><h1>Describe the scene and the exhibits</h1>
  <p class="note"><b>PRAMAAN-X AI path is the default here.</b> M1 extracts the notes, the rule parser independently checks them, M3/M4 add semantic/contradiction controls, then the deterministic engine produces EPI and the FSL plan. Attach photographs to run M2; enable M5 only when you deliberately want the heavier Granite Vision shadow scan. Times are IST. Never enter names, phone or Aadhaar numbers.</p>
  <form class="intake" id="intake">
    <div class="card">
      <div class="row2"><div class="field"><label>Case reference (FIR / Cr. No.)</label><input name="case_ref" required placeholder="Cr. No. 123/2026, PS …"></div>
        <div class="field"><label>Crime type</label><select name="crime_type">${state.profiles.map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("")}</select></div></div>
      <div class="field"><label>Title (optional)</label><input name="title" placeholder="Short description of the scene"></div>
      <div class="row"><div class="field"><label>Incident time</label><input type="datetime-local" name="incident_time"></div>
        <div class="field"><label>Triage "now"</label><input type="datetime-local" name="reference_time"></div>
        <div class="field"><label>Scene temp °C</label><input type="number" name="ambient_temp_c" step="0.5"></div></div>
      <div class="row"><div class="field"><label>Setting</label><select name="setting"><option>outdoor</option><option>indoor</option><option>vehicle</option><option>mixed</option></select></div>
        <div class="field"><label>Weather</label><select name="weather"><option>dry</option><option>rain</option><option>humid</option></select></div>
        <div class="field"><label>Custody start</label><input type="datetime-local" name="custody_start"></div></div>
      <label class="check"><input type="checkbox" name="accused_in_custody"> Accused in custody (BNSS §187(3) custody / default-bail milestone applies)</label>
      <div class="field"><label>Exhibits / scene notes</label><textarea name="description" required placeholder="Ex-A1: half-burnt cigarette butt, 3 m from the body&#10;Ex-A2: CCTV at toll plaza, not yet seized&#10;Ex-A3: viscera kept at ambient temperature"></textarea></div>
      <div class="field"><label>Scene photo captions (one per line, optional)</label><textarea class="short" name="photo_captions" placeholder="IMG_0012 Ex-A1 butt in situ with scale"></textarea></div>
      <div class="field"><label>Scene photographs for M2 / M5 (optional)</label><input type="file" name="photos" accept="image/jpeg,image/png" multiple><div class="note">M2 YOLO-World runs automatically when photos are attached. Visual detections remain investigator-review candidates.</div></div>
      <label class="check"><input type="checkbox" name="run_m5"> Also run M5 Granite Vision shadow scan (slow / RAM heavy)</label>
      <button class="btn" id="run" type="submit">Run PRAMAAN-X AI triage</button>
    </div>
    <div>
      <div class="card"><h2>Load a synthetic scenario</h2>
        ${state.scenarios.map((s) => `<div class="scen"><div><div class="t">${esc(s.title)}</div><div class="m">${esc(s.crime_type)} · ${esc(s.case_ref)}</div></div>
          <button class="btn ghost sm" type="button" data-scen="${esc(s.name)}">Load</button></div>`).join("")}
      </div>
      <div class="card"><h2>What happens next</h2><p class="note">Every exhibit gets a type from the knowledge base, an <b>Evidentiary Priority Index</b> (probative value × urgency × irreplaceability), urgent-testing flags, a non-destructive-first examination sequence and a slot in a degradation-aware FSL schedule — compared, not claimed, against first-in-first-out. The run is hashed into the chain-of-custody ledger.</p></div>
    </div>
  </form>`;
  document.querySelectorAll("[data-scen]").forEach((b) => b.addEventListener("click", () => fillScenario(b.dataset.scen)));
  $("#intake").addEventListener("submit", submitIntake);
}

async function fillScenario(name) {
  const s = await api(`/api/scenarios/${encodeURIComponent(name)}`);
  const f = $("#intake");
  f.case_ref.value = s.case_ref || ""; f.title.value = s.title || ""; f.crime_type.value = s.crime_type;
  f.incident_time.value = toLocalInput(s.incident_time); f.reference_time.value = toLocalInput(s.reference_time);
  f.custody_start.value = toLocalInput(s.custody_start); f.accused_in_custody.checked = !!s.accused_in_custody;
  f.setting.value = s.scene?.setting || "outdoor"; f.weather.value = s.scene?.weather || "dry";
  f.ambient_temp_c.value = s.scene?.ambient_temp_c ?? "";
  f.description.value = s.description || ""; f.photo_captions.value = (s.photo_captions || []).join("\n");
  toast(`Loaded scenario: ${s.title}`);
}

function safeUploadName(file, index = 0) {
  const original = String(file?.name || "scene.jpg");
  const dot = original.lastIndexOf(".");
  const ext = dot >= 0 ? original.slice(dot).toLowerCase() : ".jpg";
  const allowedExt = [".jpg", ".jpeg", ".png"].includes(ext) ? ext : ".jpg";
  // The server stores uploads under UUID names, so a short transport name is
  // sufficient and avoids OS/browser filenames causing validation failures.
  return `scene_${index + 1}${allowedExt}`;
}

function fileToBase64(file, index = 0) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.onload = () => {
      const value = String(reader.result || "");
      const comma = value.indexOf(",");
      resolve({ filename: safeUploadName(file, index), data_base64: comma >= 0 ? value.slice(comma + 1) : value });
    };
    reader.readAsDataURL(file);
  });
}

async function submitIntake(ev) {
  ev.preventDefault();
  const f = ev.target, btn = $("#run");
  const body = {
    case_ref: f.case_ref.value.trim(), title: f.title.value.trim() || null, crime_type: f.crime_type.value,
    incident_time: fromLocalInput(f.incident_time.value), reference_time: fromLocalInput(f.reference_time.value),
    scene: { setting: f.setting.value, weather: f.weather.value, ambient_temp_c: f.ambient_temp_c.value === "" ? null : Number(f.ambient_temp_c.value) },
    accused_in_custody: f.accused_in_custody.checked, custody_start: fromLocalInput(f.custody_start.value),
    description: f.description.value, photo_captions: f.photo_captions.value.split("\n").map((x) => x.trim()).filter(Boolean),
  };

  btn.disabled = true; btn.textContent = f.photos.files.length ? "Preparing photos…" : "Running AI control layer…";
  try {
    const selectedFiles = Array.from(f.photos.files || []);
    if (f.run_m5.checked && !selectedFiles.length) {
      throw new Error("M5 Granite Vision requires at least one JPG/PNG scene photograph.");
    }
    const photos = await Promise.all(selectedFiles.map((file, index) => fileToBase64(file, index)));
    btn.textContent = photos.length ? (f.run_m5.checked ? "Running all 5 models…" : "Running M1–M4 + M2…") : "Running M1 + M3 + M4…";
    const r = await api("/api/ai/triage", { method: "POST", body: JSON.stringify({ case: body, run_m5: f.run_m5.checked, photos }) });

    // NEEDS_REVIEW is a GuardRail outcome, not an application error.  The
    // visual branch still runs, so show the live five-model proof instead of a
    // red failure toast when deterministic EPI/FSL triage is intentionally held.
    if (!r.case_id || !r.triage) {
      state.lastAIReview = r;
      location.hash = "#/ai";
      const ran = Object.values(r.ai?.model_runtime || {}).filter((m) => m.last_inference_at).length;
      toast(`${r.status || "NEEDS_REVIEW"}: AI control completed · ${ran}/5 models ran · investigator review required`);
      return;
    }
    state.lastAIReview = null;
    await loadCases();
    state.data = null;
    location.hash = `#/case/${encodeURIComponent(r.case_id)}/ai`;
    toast(`PRAMAAN-X ${r.status}: ${r.triage.counts.total} exhibits · AI provenance saved`);
  } catch (e) { toast(e.message, true); } finally { btn.disabled = false; btn.textContent = "Run PRAMAAN-X AI triage"; }
}

// ------------------------------------------------------------------ case
async function showCase(id, tab) {
  setNav(null);
  if (state.caseId !== id || !state.data) {
    state.caseId = id; state.filter = "all"; state.policy = "recommended";
    try { state.data = await api(`/api/cases/${encodeURIComponent(id)}`); } catch (e) { $("#main").innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
  }
  loadCases();
  renderCase(tab || "queue");
}

function renderCase(tab) {
  const { result: r, verify } = state.data;
  const c = r.counts, rec = r.schedule.recommended, bl = r.schedule.baselines;
  const ref = bl.status_quo || bl.fifo;
  const acts = [];
  r.items.forEach((it) => it.flags.forEach((f) => { if (f.severity === "critical" && FIELD_ACTIONS.has(f.code)) acts.push([it, f]); }));
  const nElec = r.items.filter((i) => i.authenticity).length;
  const ai = state.data.ai_control;
  const aiState = ai?.final_gate?.state || ai?.status || "—";
  const tabs = [["queue", "Evidence queue", c.total], ["ai", "AI Control · M1–M5", ai ? aiState : "—"], ["lab", "Lab plan", rec.ops.length], ["gaps", "Gaps", r.gaps.length], ["authenticity", "Authenticity · BSA", nElec], ["ledger", "Custody ledger", state.data.ledger.length], ["packet", "FSL packet", ""]];
  $("#main").innerHTML = `
  <section class="case-head"><div>
      <div class="eyebrow">${esc(r.crime_label)} · <span class="mono">${esc(r.case_id)}</span></div>
      <h1>${esc(r.case_ref)}</h1><div class="sub">${esc(r.title || "")}</div></div>
    <div class="integrity">knowledge base <span class="mono">${esc(r.kb_hash.slice(0, 12))}</span> · engine v${esc(r.engine_version)} · LLM ${esc(r.llm_provider)}<br>
      result sha-256 <span class="mono">${esc(r.result_sha256.slice(0, 16))}</span> ${verify.ok ? `<span class="ok">✓ matches ledger</span>` : `<span class="bad">✗ integrity check failed</span>`}</div></section>
  <section class="tiles">
    <div class="tile"><div class="k">Exhibits</div><div class="v">${c.total}</div></div>
    <div class="tile p1"><div class="k">P1 critical</div><div class="v">${c.P1}</div></div>
    <div class="tile p2"><div class="k">P2 high</div><div class="v">${c.P2}</div></div>
    <div class="tile p4"><div class="k">Held · stage 2</div><div class="v">${c.held ?? 0}</div></div>
    <div class="tile"><div class="k">Urgent flags</div><div class="v">${c.urgent}</div></div>
    <div class="tile"><div class="k">Custody deadline</div><div class="v" style="font-size:16px;padding-top:5px">${r.custody_deadline ? new Date(r.custody_deadline + "Z").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—"}</div></div>
    <div class="tile wide"><div class="k">Evidential value retained · P1 days</div><div class="v">${pct(rec.value_retained)} <small>vs ${pct(ref.value_retained)} ${ref === bl.status_quo ? "status quo" : "FIFO"} · ${rec.p1_mean_completion_days ?? "–"} vs ${ref.p1_mean_completion_days ?? "–"} d</small></div></div>
  </section>
  ${acts.length ? `<section class="actnow"><h2><span class="pulse"></span>Act now — ${acts.length} field / preservation action${acts.length > 1 ? "s" : ""}</h2><ul>
    ${acts.map(([it, f]) => `<li><span class="exh">${esc(it.label)}</span><span><span class="code">${esc(f.code)}</span> ${esc(f.message)}</span></li>`).join("")}</ul></section>` : ""}
  <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="#/case/${encodeURIComponent(r.case_id)}/${k}" class="${k === tab ? "active" : ""}">${l}${n !== "" ? `<span class="n">${n}</span>` : ""}</a>`).join("")}</nav>
  <section id="tabbody"></section>`;
  ({ queue: renderQueue, ai: renderAIControl, lab: renderLab, gaps: renderGaps, authenticity: renderAuthenticity, ledger: renderLedger, packet: renderPacket }[tab] || renderQueue)();
}

function renderQueue() {
  const r = state.data.result;
  const f = state.filter;
  const items = r.items.filter((it) => f === "all" || (f === "held" ? it.stage === 2 : it.tier === f && it.stage === 1));
  const chips = [["all", "All"], ["P1", "P1"], ["P2", "P2"], ["P3", "P3"], ["held", "Held"]];
  $("#tabbody").innerHTML = `
  <div class="filters">${chips.map(([k, l]) => `<button class="chip ${k === f ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}
    <div class="legend"><span><i class="seg-p"></i>probative</span><span><i class="seg-u"></i>urgency</span><span><i class="seg-r"></i>irreplaceable</span><span><i class="seg-f"></i>statutory floor</span></div></div>
  <div class="card" style="padding:0">
  <table class="tbl"><thead><tr><th>#</th><th>Exhibit</th><th>Description</th><th>Type</th><th>Tier</th><th>EPI (0–100)</th><th>Time to loss</th><th>Flags</th></tr></thead><tbody>
  ${items.map((it) => {
    const ttl = timeToLoss(it.degradation);
    return `<tr data-item="${esc(it.item_id)}" class="${it.stage === 2 ? "held" : ""}"><td class="mono">${it.rank}</td><td><span class="exh">${esc(it.label)}</span></td>
      <td class="desc">${esc(it.description)}</td><td>${esc(it.classification.type_name)}</td><td>${tierChip(it.tier)}</td><td>${epiBar(it.score)}</td>
      <td class="ttl ${ttl !== null && ttl < 72 ? "hot" : ""}">${fmtHours(ttl)}</td><td>${flagChips(it.flags)}</td></tr>`;
  }).join("")}</tbody></table></div>
  ${r.parse_warnings.length ? `<div class="card"><h3>Parser warnings</h3>${r.parse_warnings.map((w) => `<div class="note">• ${esc(w)}</div>`).join("")}</div>` : ""}`;
  document.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { state.filter = b.dataset.f; renderQueue(); }));
  document.querySelectorAll("tr[data-item]").forEach((tr) => tr.addEventListener("click", () => openDrawer(tr.dataset.item)));
}

function modelStatusChip(row) {
  const status = row?.status || "NOT_LOADED";
  const cls = status === "INFERENCE_OK" || status === "COMPLETED" ? "READY" : status === "ERROR" ? "AT_RISK" : "ADVISORY";
  return `<span class="st ${cls}">${esc(status)}</span>`;
}

function renderAIControl() {
  const c = state.data.ai_control;
  if (!c) {
    $("#tabbody").innerHTML = `<div class="card"><h2>No AI-control snapshot for this case</h2><p class="note">This case was created through the deterministic-only endpoint. Create a new case with <b>Run PRAMAAN-X AI triage</b> or use Bob's <span class="mono">analyze_scene_ai</span> tool.</p></div>`;
    return;
  }
  const ai = c.ai || {}, gate = c.final_gate || {}, runtime = ai.model_runtime || {}, rec = ai.reconciliation || {};
  const modelRows = ["m1","m2","m3","m4","m5"].map((k) => {
    const x = runtime[k] || {};
    return `<tr><td class="mono"><b>${k.toUpperCase()}</b></td><td>${esc(x.name || "—")}</td><td class="mono">${esc(x.model || "—")}</td><td>${modelStatusChip(x)}</td><td>${x.last_inference_at ? esc(x.last_inference_at) : "—"}</td><td class="note">${esc(x.error || "")}</td></tr>`;
  }).join("");
  const visual = ai.visual || {};
  const m2 = (visual.m2 || []).flatMap((x) => x.detections || []);
  const m5 = (visual.m5 || []).flatMap((x) => x.candidates || []);
  const twins = ai.digital_twins || [];
  $("#tabbody").innerHTML = `
    <div class="ai-gate ${esc(gate.state || c.status || "NEEDS_REVIEW")}">
      <div><div class="eyebrow">PRAMAAN GuardRail</div><h2>${esc(gate.state || c.status || "UNKNOWN")}</h2></div>
      <div class="note">${esc(gate.summary || c.message || "")}</div>
      <div class="inline"><span class="pill">triage ${gate.triage_allowed ? "allowed" : "blocked"}</span><span class="pill">submission ${gate.submission_allowed ? "allowed" : "review required"}</span></div>
    </div>
    <div class="card"><h2>Five-model execution proof</h2><p class="note">Status is recorded by the live Python process. <b>INFERENCE_OK</b> means that model actually performed inference. M2/M5 remain NOT_LOADED until photographs are supplied; M5 only runs when explicitly enabled.</p>
      <div class="table-scroll"><table class="tbl ai-model-table"><thead><tr><th>Module</th><th>Name</th><th>Model</th><th>Status</th><th>Last inference UTC</th><th>Error</th></tr></thead><tbody>${modelRows}</tbody></table></div>
    </div>
    <div class="grid3">
      <div class="card kpi"><span class="l">M1 candidates</span><span class="big">${rec.counts?.m1 ?? "—"}</span></div>
      <div class="card kpi"><span class="l">Reconciled twins</span><span class="big">${twins.length}</span></div>
      <div class="card kpi"><span class="l">M4 contradictions</span><span class="big">${(ai.m4?.contradictions || []).length}</span></div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Reconciliation & Digital Twins</h2>
        <div class="kv"><div>Matches</div><div>${(rec.matches || []).length}</div><div>Missing from M1</div><div>${(rec.missing_from_m1 || []).length}</div><div>Missing from rules</div><div>${(rec.missing_from_rules || []).length}</div><div>Rule-only text</div><div>${(rec.unclassified_rule_candidates || []).length}</div></div>
        <table class="tbl" style="margin-top:10px"><thead><tr><th>Twin</th><th>Description</th><th>Type</th><th>Decision confidence</th></tr></thead><tbody>
        ${twins.map((t) => `<tr><td class="mono">${esc(t.twin_id || "—")}</td><td>${esc(t.description)}</td><td>${esc(t.classification?.type_id || "—")}</td><td>${esc(t.decision_confidence?.label || t.decision_confidence?.level || "—")} ${t.decision_confidence?.value !== undefined ? `(${Number(t.decision_confidence.value).toFixed(3)})` : ""}</td></tr>`).join("") || `<tr><td colspan="4" class="note">No twins</td></tr>`}
        </tbody></table>
      </div>
      <div class="card"><h2>Visual AI</h2><div class="kv"><div>M2 detections</div><div>${m2.length}</div><div>M5 candidates</div><div>${m5.length}</div><div>Unlinked candidates</div><div>${(visual.unlinked_visual_candidates || []).length}</div></div>
        <h3>M2 YOLO-World</h3>${m2.map((d) => `<div class="visual-candidate"><b>${esc(d.visual_label)}</b> → ${esc(d.pramaan_type_candidate)} <span class="pill">${Number(d.visual_confidence || 0).toFixed(2)}</span><div class="note">Candidate only · investigator confirmation required</div></div>`).join("") || `<div class="note">No M2 candidates. Attach a JPG/PNG during case creation to run M2.</div>`}
        <h3>M5 Granite Vision</h3>${m5.map((d) => `<div class="visual-candidate"><b>${esc(d.visual_description)}</b> → ${esc(d.suggested_type)} <span class="pill">${esc(d.visual_confidence)}</span><div class="note">${esc(d.manifest_status)} · ${esc(d.reason || "")}</div></div>`).join("") || `<div class="note">No M5 candidates. M5 runs only when a photo is attached and the M5 checkbox is enabled.</div>`}
      </div>
    </div>
    ${gate.issues?.length ? `<div class="card"><h2>GuardRail issues</h2>${gate.issues.map((i) => `<div class="gap ${esc(i.severity)}"><div class="sev">${esc(i.code)} · ${esc(i.severity)}</div><div>${esc(i.message)}</div></div>`).join("")}</div>` : ""}`;
}

// ---------------------------------------------------------------- drawer
function openDrawer(itemId) {
  const r = state.data.result;
  const it = r.items.find((i) => i.item_id === itemId);
  if (!it) return;
  const s = it.score, d = it.degradation, w = s.weights;
  const f = (name, cls, val, weight) => `<div class="factor"><span>${name}</span><div class="fb"><span class="${cls}" style="width:${(val * 100).toFixed(0)}%"></span></div><span class="pts">${(100 * weight * val).toFixed(1)} pt</span></div>`;
  $("#drawer").innerHTML = `
    <button class="x" aria-label="close" onclick="closeDrawer()">×</button>
    <div class="eyebrow">Rank ${it.rank} · ${esc(it.classification.category)} · ${it.stage === 2 ? "held for stage 2" : "stage 1 submission"}</div>
    <h1><span class="exh" style="font-size:16px">${esc(it.label)}</span> ${esc(it.classification.type_name)}</h1>
    <p>${esc(it.description)}</p>
    <div class="inline">${tierChip(it.tier)} <span class="pill">EPI ${s.epi.toFixed(1)}</span>
      ${it.engine_tier && it.engine_tier !== it.tier ? `<span class="pill">engine tier ${esc(it.engine_tier)}</span>` : ""}
      <span class="pill">confidence ${it.classification.confidence} · ${esc(it.classification.method)}</span></div>
    <h3>Why this priority</h3>
    ${f("Probative", "seg-p", s.probative, w.probative)}${f("Urgency", "seg-u", s.urgency, w.urgency)}${f("Irreplaceable", "seg-r", s.irreplaceable, w.irreplaceable)}
    ${s.legal_floor_applied ? `<div class="note">Raised to the statutory floor of 85 (mandated examination).</div>` : ""}
    <p class="note">${esc(it.rationale)}</p>
    <h3>Degradation</h3>
    <div class="quality"><i style="left:calc(${(d.quality_now * 100).toFixed(0)}% - 1px)"></i></div>
    <div class="kv"><div>Quality now</div><div>${(d.quality_now * 100).toFixed(0)}% (risk threshold 60%)</div>
      <div>Condition</div><div>${esc(d.condition)} · ${esc(d.profile)} profile</div>
      <div>Usable for</div><div>${fmtHours(d.hours_to_risk)}${d.better_condition ? ` → ${fmtHours(d.hours_to_risk_if_preserved)} if ${esc(d.better_condition)}` : ""}</div>
      ${d.field_window_remaining_h !== null ? `<div>Field window left</div><div>${fmtHours(d.field_window_remaining_h)}</div>` : ""}</div>
    <div class="inline" style="margin-top:8px"><span class="note">What if stored as</span>
      ${["refrigerated", "frozen", "dry_sealed", "ambient"].map((c) => `<button class="btn ghost sm" data-sim="${c}">${c}</button>`).join("")}</div>
    <div id="sim"></div>
    <h3>Examination sequence (least destructive first)</h3>
    <ol class="steps">${it.exam_sequence.map((st) => `<li>${esc(st.name)} <span class="muted">· ${esc(st.division)} · ${st.hours} h</span>${st.destructive ? `<span class="d">DESTRUCTIVE</span>` : ""}</li>`).join("") || "<li>No examinations</li>"}</ol>
    <h3>Flags</h3>${it.flags.map((fl) => `<div style="margin:4px 0"><span class="flag ${esc(fl.severity)}">${esc(fl.code)}</span> <span class="note">${esc(fl.message)}</span></div>`).join("") || `<div class="note">None</div>`}
    <h3>Interpretation guardrails</h3>
    <div class="kv"><div>Does not prove</div><div>${esc(it.caveat)}</div><div>Corroborate with</div><div>${esc(it.corroborate_with.join("; "))}</div><div>Handling</div><div>${esc(it.handling)}</div></div>
    <h3>Officer override (logged)</h3>
    <div class="inline"><select id="ov-tier">${["P1", "P2", "P3", "P4"].map((t) => `<option ${t === it.tier ? "selected" : ""}>${t}</option>`).join("")}</select>
      <input id="ov-reason" placeholder="Reason (required, written to ledger)" style="flex:1;min-width:200px"><button class="btn sm" id="ov-go">Apply</button></div>
    <h3>Chain-of-custody event</h3>
    <div class="inline"><select id="cu-ev"><option>sealed</option><option>handed_over</option><option>received</option><option>opened_for_examination</option><option>resealed</option></select>
      <input id="cu-from" placeholder="from (role)" size="9"><input id="cu-to" placeholder="to (role)" size="9">
      <label class="check" style="margin:0"><input type="checkbox" id="cu-seal" checked> seal intact</label><button class="btn sm" id="cu-go">Record</button></div>`;
  $("#drawer").classList.add("open"); $("#scrim").classList.add("open");
  document.querySelectorAll("[data-sim]").forEach((b) => b.addEventListener("click", () => simulate(it, b.dataset.sim)));
  $("#ov-go").addEventListener("click", () => override(it));
  $("#cu-go").addEventListener("click", () => custody(it));
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); }
window.closeDrawer = closeDrawer;

async function simulate(it, condition) {
  try {
    const s = await api(`/api/cases/${encodeURIComponent(state.caseId)}/items/${encodeURIComponent(it.item_id)}/simulate`, { method: "POST", body: JSON.stringify({ condition }) });
    $("#sim").innerHTML = `<div class="sim-out"><b>${esc(s.item)} → ${esc(condition)}</b>: usable window ${fmtHours(s.hours_to_risk.from)} → <b>${fmtHours(s.hours_to_risk.to)}</b>;
      EPI ${s.epi.from} → ${s.epi.to}; tier ${s.tier.from} → ${s.tier.to}; case value retained ${pct(s.case_value_retained.from)} → <b>${pct(s.case_value_retained.to)}</b>. <span class="muted">(what-if only — nothing saved)</span></div>`;
  } catch (e) { toast(e.message, true); }
}

async function override(it) {
  const tier = $("#ov-tier").value, reason = $("#ov-reason").value.trim();
  try {
    await api(`/api/cases/${encodeURIComponent(state.caseId)}/items/${encodeURIComponent(it.item_id)}/update`,
      { method: "POST", body: JSON.stringify({ changes: { override_tier: tier, override_reason: reason }, reason }) });
    closeDrawer(); state.data = null; await showCase(state.caseId, "queue"); toast(`${it.label} set to ${tier} — logged in the ledger`);
  } catch (e) { toast(e.message, true); }
}

async function custody(it) {
  try {
    const e = await api(`/api/cases/${encodeURIComponent(state.caseId)}/items/${encodeURIComponent(it.item_id)}/custody`, {
      method: "POST", body: JSON.stringify({ event: $("#cu-ev").value, from_party: $("#cu-from").value || null, to_party: $("#cu-to").value || null, seal_intact: $("#cu-seal").checked }) });
    state.data = await api(`/api/cases/${encodeURIComponent(state.caseId)}`);
    toast(`Recorded as ledger entry #${e.seq} (${e.hash.slice(0, 12)}…)`);
  } catch (e) { toast(e.message, true); }
}

// -------------------------------------------------------------- lab plan
function gantt(sched, tierOf, bph) {
  const ops = sched.ops;
  if (!ops.length) return `<div class="note">No operations.</div>`;
  const keys = [...new Set(ops.map((o) => `${o.division}|${o.examiner}`))].sort();
  const maxH = Math.max(...ops.map((o) => o.end_h)), days = maxH / bph;
  const left = 150, W = Math.max(980, Math.min(2400, 26 * days + left + 40)), rowH = 21, top = 26;
  const H = top + keys.length * rowH + 10, sx = (W - left - 16) / maxH;
  const step = [1, 2, 5, 10, 20, 50].find((s) => days / s <= 14) || 100;
  let svg = `<svg class="gantt" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><g class="axis">`;
  for (let dd = 0; dd <= days + 0.001; dd += step) {
    const x = left + dd * bph * sx;
    svg += `<line x1="${x}" y1="${top - 6}" x2="${x}" y2="${H - 6}" stroke="#e6dfd0"/><text x="${x + 2}" y="${top - 10}">day ${dd}</text>`;
  }
  svg += `</g>`;
  keys.forEach((k, i) => {
    const [div, ex] = k.split("|"), y = top + i * rowH;
    if (i % 2 === 0) svg += `<rect x="0" y="${y}" width="${W}" height="${rowH}" fill="#faf6ec"/>`;
    svg += `<text x="6" y="${y + 14}">${esc(div.toLowerCase())} · ${ex}</text>`;
  });
  ops.forEach((o) => {
    const i = keys.indexOf(`${o.division}|${o.examiner}`), y = top + i * rowH + 3;
    const x = left + o.start_h * sx, w = Math.max(1.5, (o.end_h - o.start_h) * sx), t = tierOf[o.item_id] || "P3";
    svg += `<g><rect x="${x}" y="${y}" width="${w}" height="${rowH - 6}" rx="3" fill="${TIER_COLOR[t]}" opacity="${o.quality_at_start < 0.7 ? 0.55 : 0.92}">
      <title>${esc(o.label)} · ${esc(o.exam_name)} · day ${(o.start_h / bph).toFixed(1)}–${(o.end_h / bph).toFixed(1)} · quality ${(o.quality_at_start * 100).toFixed(0)}%</title></rect>
      ${w > 44 ? `<text class="bl" x="${x + 4}" y="${y + 11}">${esc(o.label.split("/").pop())}</text>` : ""}</g>`;
  });
  return svg + `</svg>`;
}

function renderLab() {
  const r = state.data.result, sc = r.schedule, bph = state.health?.bench_hours_per_day || 8;
  const pols = [["recommended", sc.recommended], ...Object.entries(sc.baselines)];
  const sel = pols.find(([k]) => k === state.policy) || pols[0];
  const tierOf = Object.fromEntries(r.items.map((i) => [i.item_id, i.tier]));
  $("#tabbody").innerHTML = `
  <div class="card"><h2>Recommended plan</h2><p style="margin:0">${esc(sc.summary)}</p></div>
  <div class="grid${pols.length >= 4 ? "3" : "3"}" style="grid-template-columns:repeat(${pols.length},1fr);margin-bottom:14px">
  ${pols.map(([k, p]) => `<div class="policy ${k === "recommended" ? "rec" : ""} ${k === sel[0] ? "sel" : ""}" data-pol="${k}">
    <div class="pn">${esc(POLICY_NAME[k] || k)} <span class="muted" style="text-transform:none">${esc(p.policy)}</span></div>
    <div class="metrics"><span>value retained</span><b>${pct(p.value_retained)}</b><span>perishable value</span><b>${pct(p.perishable_value_retained)}</b>
      <span>late exhibits</span><b>${p.late_count}</b><span>P1 mean (days)</span><b>${p.p1_mean_completion_days ?? "–"}</b><span>makespan (days)</span><b>${p.makespan_days}</b></div></div>`).join("")}
  </div>
  <div class="filters"><b>Examination timeline — ${esc(POLICY_NAME[sel[0]] || sel[0])}</b><span class="note">(click a policy card to compare; bars coloured by tier, faded = quality below 70% when examined)</span>
    <div class="legend">${["P1", "P2", "P3", "P4"].map((t) => `<span><i style="background:${TIER_COLOR[t]}"></i>${t}</span>`).join("")}</div></div>
  <div class="gantt-wrap">${gantt(sel[1], tierOf, bph)}</div>
  <div class="card" style="margin-top:14px"><h2>Division load</h2><table class="tbl"><thead><tr><th>Division</th><th>Examiners</th><th class="right">Bench hours</th><th class="right">Busy (working days)</th></tr></thead><tbody>
  ${sel[1].divisions.map((d) => `<tr><td>${esc(d.name)}</td><td>${d.examiners}</td><td class="right mono">${d.total_hours}</td><td class="right mono">${d.working_days}</td></tr>`).join("")}</tbody></table></div>`;
  document.querySelectorAll("[data-pol]").forEach((el) => el.addEventListener("click", () => { state.policy = el.dataset.pol; renderLab(); }));
}

function renderGaps() {
  const r = state.data.result;
  $("#tabbody").innerHTML = `<p class="note">A ranking can only order what was collected. These checks compare the exhibit list with what a ${esc(r.crime_label.toLowerCase())} investigation normally needs, and with the scene photographs.</p>
  ${r.gaps.map((g) => `<div class="gap ${esc(g.severity)}"><div class="sev">${esc(g.severity)} · ${esc(g.id)}</div><div><b>${esc(g.message)}</b></div><div class="act">${esc(g.action)}</div></div>`).join("") || `<div class="card">No gaps detected.</div>`}`;
}

function renderLedger() {
  const { ledger } = state.data;
  $("#tabbody").innerHTML = `
  <div class="filters"><button class="btn sm" id="verify">Verify entire hash chain</button><span class="note">Each entry's SHA-256 covers its content and the previous entry's hash — editing, deleting or re-ordering any row breaks the chain.</span></div>
  <div id="vres"></div>
  <div class="card" style="padding:0"><table class="tbl"><thead><tr><th>Seq</th><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Item</th><th>Details</th><th>Hash ← previous</th></tr></thead><tbody>
  ${ledger.map((e) => `<tr><td class="mono">${e.seq}</td><td class="mono">${esc(e.ts.slice(0, 19).replace("T", " "))}</td><td><span class="pill">${esc(e.actor)}</span></td><td><b>${esc(e.action)}</b></td>
    <td class="mono">${esc(e.item_id || "")}</td><td class="note">${esc(JSON.stringify(e.payload).slice(0, 110))}</td>
    <td class="hash">${esc(e.hash.slice(0, 14))}<br>← ${esc(e.prev_hash.slice(0, 14))}</td></tr>`).join("")}</tbody></table></div>`;
  $("#verify").addEventListener("click", async () => {
    const v = await api("/api/ledger/verify");
    $("#vres").innerHTML = v.ok ? `<div class="banner ok">✓ Chain intact — ${v.entries} entries, head ${esc((v.head_hash || "").slice(0, 24))}…</div>`
      : `<div class="banner bad">✗ Chain broken at entry #${v.first_bad_seq}: ${esc(v.reason)}</div>`;
  });
}

async function renderPacket() {
  const id = encodeURIComponent(state.caseId);
  $("#tabbody").innerHTML = `<div class="filters"><a class="btn" href="/api/cases/${id}/packet.pdf" target="_blank">Open PDF packet</a>
    <a class="btn ghost" href="/api/cases/${id}/packet.md" target="_blank">Markdown</a>
    <a class="btn ghost" href="/api/cases/${id}/report.html" target="_blank">report.html</a>
    <a class="btn ghost" href="/api/cases/${id}/graph.html" target="_blank">graph.html</a>
    <a class="btn ghost" href="/api/cases/${id}/state.json" target="_blank">state.json</a>
    <a class="btn ghost" href="/api/cases/${id}/audit.jsonl" target="_blank">audit.jsonl</a><span class="note">Forwarding note · ACT NOW · ranked schedule · handling & caveats · held items · gaps · lab plan · method & integrity block</span></div>
    <pre class="md" id="md">Loading…</pre>`;
  try { $("#md").textContent = await api(`/api/cases/${id}/packet.md`); } catch (e) { $("#md").textContent = e.message; }
}

// ------------------------------------------------- authenticity (BSA 2023)
const ST = (s) => `<span class="st ${esc(s)}">${esc(String(s).replace("_", " "))}</span>`;
async function renderAuthenticity() {
  const id = encodeURIComponent(state.caseId);
  $("#tabbody").innerHTML = `<div class="loading">Assessing authenticity…</div>`;
  let rep;
  try { rep = await api(`/api/cases/${id}/authenticity`); } catch (e) { $("#tabbody").innerHTML = `<div class="card">${esc(e.message)}</div>`; return; }
  const elec = rep.items.filter((r) => r.assessment.kind === "electronic"), phys = rep.items.filter((r) => r.assessment.kind === "physical");
  const cond = (k, l, v) => `<label class="cb"><input type="checkbox" name="${k}" ${v ? "checked" : ""}> ${l}</label>`;
  $("#tabbody").innerHTML = `
  <div class="filters"><b>Bharatiya Sakshya Adhiniyam, 2023 — ss.61, 62, 63(2), 63(4) · BNSS s.105</b>
    <a class="btn sm" href="/api/cases/${id}/authenticity.pdf" target="_blank">Authenticity report (PDF)</a>
    <a class="btn ghost sm" href="/api/legal/bsa-analysis.pdf" target="_blank">Legal analysis (PDF)</a></div>
  <p class="note">${esc(rep.disclaimer)}</p>
  <div class="grid3" style="grid-template-columns:repeat(4,1fr);margin-bottom:14px">
    <div class="card kpi"><span class="l">Electronic records ready</span><span class="big">${rep.electronic_ready}/${rep.electronic_records}</span></div>
    <div class="card kpi"><span class="l">READY</span><span class="big" style="color:var(--ok)">${rep.counts.READY}</span></div>
    <div class="card kpi"><span class="l">CURABLE GAPS</span><span class="big" style="color:var(--p2)">${rep.counts.CURABLE_GAPS}</span></div>
    <div class="card kpi"><span class="l">AT RISK</span><span class="big" style="color:var(--p1)">${rep.counts.AT_RISK}</span></div></div>
  <h2>Electronic records (BSA s.63)</h2>
  ${elec.map((r) => { const a = r.assessment, e = r.electronic_input || {};
    return `<div class="ecard"><h3><span class="exh">${esc(r.label)}</span>${esc(r.type)} ${ST(a.status)} <span class="pill">score ${a.score}</span>
      <a class="btn ghost sm" style="margin-left:auto" href="/api/cases/${id}/items/${encodeURIComponent(r.item_id)}/bsa63-certificate.pdf" target="_blank">s.63(4) certificate draft</a></h3>
      <div class="note">${esc(a.route)} — ${esc(a.summary)}</div>
      <table class="tbl" style="margin-top:6px"><thead><tr><th>Check</th><th>Law</th><th>Requirement</th><th>Status</th><th>Detail / remedy</th></tr></thead><tbody>
      ${a.checks.map((c) => `<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.law)}</td><td>${esc(c.requirement)}</td><td>${ST(c.status)}</td>
        <td class="note">${esc(c.detail)}${c.status === "PASS" || c.status === "NA" ? "" : " → " + esc(c.remedy)}</td></tr>`).join("")}</tbody></table>
      <details><summary>Record s.63 facts for ${esc(r.label)}</summary><form class="eform" data-item="${esc(r.item_id)}">
        <label>Acquisition<select name="acquisition">${["original_device", "forensic_image", "exported_copy", "screen_capture", "printout"].map((o) => `<option ${e.acquisition === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>
        <label>Device (make &amp; model)<input name="device" value="${esc(e.device || "")}"></label>
        <label>Serial / IMEI / MAC<input name="device_id" value="${esc(e.device_id || "")}"></label>
        <label>SHA-256 at acquisition<input name="hash_at_acquisition" value="${esc(e.hash_at_acquisition || "")}"></label>
        <label>SHA-256 at FSL<input name="hash_at_lab" value="${esc(e.hash_at_lab || "")}"></label>
        <label>Clock offset (s, CCTV)<input name="clock_offset_s" type="number" value="${e.clock_offset_s ?? ""}"></label>
        ${cond("regular_use", "s.63(2)(a) regular use", e.regular_use)}${cond("ordinary_course", "s.63(2)(b) ordinary course", e.ordinary_course)}
        ${cond("operating_properly", "s.63(2)(c) operating properly", e.operating_properly)}${cond("derived_from_ordinary_course", "s.63(2)(d) derived from ordinary course", e.derived_from_ordinary_course)}
        ${cond("write_blocker_used", "write blocker used", e.write_blocker_used)}${cond("certificate_part_a", "Part A signed", e.certificate_part_a)}
        <label>Part A signatory (designation)<input name="part_a_signatory_role" value="${esc(e.part_a_signatory_role || "")}"></label>
        ${cond("certificate_part_b", "Part B signed (expert)", e.certificate_part_b)}
        <label>Expert (designation)<input name="expert_role" value="${esc(e.expert_role || "")}"></label>
        <label style="grid-column:span 2">Reason (ledger)<input name="reason" placeholder="e.g. DVR export hashed at seizure"></label>
        <div style="align-self:end"><button class="btn sm" type="submit">Save facts</button></div></form></details></div>`; }).join("") || `<div class="card note">No electronic records in this case.</div>`}
  <h2>Physical exhibits — reliability of custody &amp; documentation</h2>
  <div class="card" style="padding:0"><table class="tbl"><thead><tr><th>Exhibit</th><th>Type</th><th>Status</th><th>Score</th><th>Open items</th></tr></thead><tbody>
  ${phys.map((r) => `<tr><td><span class="exh">${esc(r.label)}</span></td><td>${esc(r.type)}</td><td>${ST(r.assessment.status)}</td><td class="mono">${r.assessment.score}</td>
    <td class="note">${r.assessment.checks.filter((c) => c.status === "FAIL" || c.status === "MISSING").map((c) => esc(c.id)).join(", ") || "—"}</td></tr>`).join("")}</tbody></table></div>`;
  document.querySelectorAll("form.eform").forEach((f) => f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(f), details = {};
    ["acquisition", "device", "device_id", "hash_at_acquisition", "hash_at_lab", "part_a_signatory_role", "expert_role"].forEach((k) => { const v = (fd.get(k) || "").trim(); if (v) details[k] = v; });
    const off = fd.get("clock_offset_s"); if (off !== "" && off !== null) details.clock_offset_s = Number(off);
    ["regular_use", "ordinary_course", "operating_properly", "derived_from_ordinary_course", "write_blocker_used", "certificate_part_a", "certificate_part_b"].forEach((k) => { details[k] = f.querySelector(`[name=${k}]`).checked; });
    const reason = (fd.get("reason") || "").trim() || "s.63 facts recorded from dashboard";
    try {
      await api(`/api/cases/${id}/items/${encodeURIComponent(f.dataset.item)}/update`, { method: "POST", body: JSON.stringify({ changes: { electronic: details }, reason }) });
      state.data = await api(`/api/cases/${id}`); toast("s.63 facts saved — re-triaged and logged"); renderAuthenticity();
    } catch (e) { toast(e.message, true); }
  }));
}

// --------------------------------------------------------- FSL network
async function showNetwork(params = "") {
  setNav("network"); state.caseId = null; loadCases();
  $("#main").innerHTML = `<div class="loading">Planning the FSL network…</div>`;
  const q = await api(`/api/network-plan${params}`);
  const hq = q.hq_only, net = q.network;
  const divs = Object.keys((q.units_config[0] || {}).examiners || {});
  const card = (name, p, rec) => `<div class="policy ${rec ? "rec sel" : ""}"><div class="pn">${name}</div><div class="metrics">
    <span>exhibits</span><b>${p.exhibits}</b><span>P1 mean (days)</span><b>${p.p1_mean_days ?? "–"}</b><span>queue clears (days)</span><b>${p.makespan_days}</b>
    <span>late exhibits</span><b>${p.late}</b><span>plan time</span><b>${(p.plan_seconds * 1000).toFixed(0)} ms</b></div></div>`;
  $("#main").innerHTML = `<div class="eyebrow">Scalability</div><h1>State forensic network — HQ, regional labs and CFSL referral</h1>
  <div class="card"><p style="margin:0">${esc(q.summary)}</p></div>
  <div class="grid2" style="margin-bottom:14px">${card("Pramaan network plan", net, true)}${card("Everything to State FSL HQ", hq, false)}</div>
  <div class="card" style="padding:0"><table class="tbl"><thead><tr><th>Unit</th><th>Kind</th><th class="right">Transport h</th><th class="right">Exhibits</th><th class="right">P1</th><th class="right">Busy days</th><th>Bottleneck division</th><th>Bottleneck load</th></tr></thead><tbody>
  ${net.units.map((u) => `<tr><td><b>${esc(u.name)}</b> <span class="muted mono">${esc(u.id)}</span></td><td>${esc(u.kind)}</td><td class="right mono">${u.transport_h}</td><td class="right mono">${u.exhibits}</td><td class="right mono">${u.p1}</td><td class="right mono">${u.busy_days}</td>
    <td class="mono">${esc(u.bottleneck || "–")}</td><td><div class="ubar"><span style="width:${Math.min(100, u.bottleneck_utilisation * 100).toFixed(0)}%"></span></div></td></tr>`).join("")}</tbody></table></div>
  <div class="grid2"><div class="card"><h2>Capacity what-if (HQ)</h2><div class="inline"><select id="wd">${divs.map((d) => `<option>${d}</option>`).join("")}</select>
    <span class="note">+</span><input id="wn" type="number" min="1" max="20" value="2" style="width:70px"><span class="note">examiners</span><button class="btn sm" id="wgo">Re-plan</button></div>
    <p class="note">Answers "how many DNA examiners would clear this backlog?" for budgeting and recruitment. ${Object.keys(q.network.add_examiners).length ? "Showing: +" + esc(JSON.stringify(q.network.add_examiners)) : ""}</p></div>
  <div class="card"><h2>Load test</h2><div class="inline"><button class="btn sm" id="sgo">Run 10 cases × 200 exhibits</button></div><div id="sres" class="note" style="margin-top:8px">Synthetic Hyderabad-scale cases triaged and planned together.</div></div></div>`;
  $("#wgo").addEventListener("click", () => showNetwork(`?add_division=${$("#wd").value}&add_examiners=${$("#wn").value}`));
  $("#sgo").addEventListener("click", async () => {
    $("#sres").textContent = "Running…";
    const s = await api("/api/scale-benchmark?cases=10&items=200");
    $("#sres").innerHTML = `<b>${s.exhibits}</b> exhibits across ${s.cases} cases triaged in <b>${s.triage_seconds} s</b> (${s.exhibits_per_second}/s). ${esc(s.summary)}`;
  });
}

// ------------------------------------------------------------ lab queue
async function showLab() {
  setNav("lab"); state.caseId = null; loadCases();
  $("#main").innerHTML = `<div class="loading">Planning one queue across all cases…</div>`;
  const q = await api("/api/lab-queue"), bph = state.health?.bench_hours_per_day || 8;
  const tierOf = Object.fromEntries(q.recommended.items.map((i) => [i.item_id, i.tier]));
  const b = q.baselines;
  $("#main").innerHTML = `<div class="eyebrow">FSL view</div><h1>One queue for every open case</h1>
  <div class="card"><p style="margin:0">${esc(q.summary)}</p></div>
  <div class="grid3" style="margin-bottom:14px">${[["recommended", q.recommended], ...Object.entries(b)].map(([k, p]) => `<div class="policy ${k === "recommended" ? "rec sel" : ""}">
    <div class="pn">${esc(k === "fifo" ? "Cases in arrival order" : POLICY_NAME[k] || k)} <span class="muted" style="text-transform:none">${esc(p.policy)}</span></div>
    <div class="metrics"><span>value retained</span><b>${pct(p.value_retained)}</b><span>late exhibits</span><b>${p.late_count}</b><span>P1 mean (days)</span><b>${p.p1_mean_completion_days ?? "–"}</b><span>queue clears (days)</span><b>${p.makespan_days}</b></div></div>`).join("")}</div>
  <div class="gantt-wrap">${gantt(q.recommended, tierOf, bph)}</div>`;
}

// ------------------------------------------------------------ benchmark
async function showBenchmark() {
  setNav("benchmark"); state.caseId = null; loadCases();
  $("#main").innerHTML = `<div class="eyebrow">Evaluation</div><h1>Hyderabad-scale benchmark</h1>
  <p class="note">A synthetic scene with the shape of the 2019 case — hundreds of near-duplicate litter items, a few decisive traces, perishable toxicology, CCTV that overwrites — generated from a fixed seed. Five "needle" exhibits are hidden at random positions in the list.</p>
  <div class="filters"><select id="bn" class="chip"><option>100</option><option selected>200</option><option>400</option></select><button class="btn sm" id="brun">Run benchmark</button></div><div id="bres"></div>`;
  $("#brun").addEventListener("click", runBenchmark);
  runBenchmark();
}

async function runBenchmark() {
  $("#bres").innerHTML = `<div class="loading">Triaging…</div>`;
  const b = await api(`/api/benchmark?n=${$("#bn").value}`);
  const P = b.policies, pr = P.pramaan, sq = P.status_quo || P.fifo;
  $("#bres").innerHTML = `
  <div class="grid3" style="grid-template-columns:repeat(4,1fr);margin-bottom:14px">
    <div class="card kpi"><span class="l">Exhibits triaged</span><span class="big">${b.n_items}</span><span class="l">in ${b.seconds}s (${b.items_per_second}/s)</span></div>
    <div class="card kpi"><span class="l">Needles surfaced as P1</span><span class="big">${b.needles.filter((n) => n.tier === "P1").length}/${b.needles.length}</span><span class="l">worst rank ${Math.max(...b.needles.map((n) => n.rank))}</span></div>
    <div class="card kpi"><span class="l">P1 results (working days)</span><span class="big">${pr.p1_mean_days}</span><span class="l">vs ${sq.p1_mean_days} status quo</span></div>
    <div class="card kpi"><span class="l">Evidential value retained</span><span class="big">${pct(pr.value_retained)}</span><span class="l">vs ${pct(sq.value_retained)} status quo · late ${pr.late} vs ${sq.late}</span></div></div>
  <div class="grid2"><div class="card"><h2>Scheduling policies</h2><table class="tbl"><thead><tr><th>Policy</th><th class="right">Value</th><th class="right">Perishable</th><th class="right">Late</th><th class="right">P1 days</th><th class="right">Makespan</th></tr></thead><tbody>
    ${Object.entries(P).map(([k, p]) => `<tr><td><b>${esc(k === "pramaan" ? "Pramaan" : POLICY_NAME[k] || k)}</b> <span class="muted mono">${esc(p.policy)}</span></td><td class="right mono">${pct(p.value_retained)}</td><td class="right mono">${pct(p.perishable_value_retained)}</td><td class="right mono">${p.late}</td><td class="right mono">${p.p1_mean_days ?? "–"}</td><td class="right mono">${p.makespan_days}</td></tr>`).join("")}</tbody></table>
    <p class="note">Status quo = every exhibit examined in listing order. FIFO / static sort use Pramaan's staged stage-1 set, so ordering and staging effects are reported separately.</p></div>
  <div class="card"><h2>Needles</h2><table class="tbl"><thead><tr><th>Needle</th><th>Exhibit</th><th class="right">Listed at</th><th class="right">Ranked</th><th>Tier</th><th>Type</th></tr></thead><tbody>
    ${b.needles.map((n) => `<tr><td class="mono">${esc(n.needle)}</td><td><span class="exh">${esc(n.label)}</span></td><td class="right mono">#${n.listed_at}</td><td class="right mono"><b>#${n.rank}</b></td><td>${tierChip(n.tier)}</td><td>${esc(n.type)}</td></tr>`).join("")}</tbody></table>
    <p class="note">Counts: ${esc(JSON.stringify(b.counts))}</p></div></div>`;
}

// ------------------------------------------------------------------- AI
async function showAI() {
  setNav("ai"); state.caseId = null; loadCases();
  const s = await api("/api/ai/status");
  const rows = ["m1","m2","m3","m4","m5"].map((k) => { const x = s.models[k] || {}; return `<tr><td class="mono"><b>${k.toUpperCase()}</b></td><td>${esc(x.name)}</td><td>${esc(x.role)}</td><td class="mono model-id">${esc(x.model)}</td><td>${modelStatusChip(x)}</td><td class="mono inference-time">${x.last_inference_at ? esc(x.last_inference_at) : "—"}</td><td class="note error-cell">${esc(x.error || "")}</td></tr>`; }).join("");
  const review = state.lastAIReview;
  const reviewRuntime = review?.ai?.model_runtime || {};
  const reviewRan = Object.values(reviewRuntime).filter((m) => m.last_inference_at).length;
  const reviewCard = review ? `<div class="ai-gate ${esc(review.final_gate?.state || review.status || "NEEDS_REVIEW")}">
      <div><div class="eyebrow">Latest gated run</div><h2>${esc(review.final_gate?.state || review.status || "NEEDS_REVIEW")}</h2></div>
      <div class="note">${esc(review.message || "Investigator review required before deterministic triage.")}</div>
      <div class="inline"><span class="pill">${reviewRan}/5 models ran</span><span class="pill">images ${review.ai?.summary?.images_received ?? 0}</span><span class="pill">M5 ${review.ai?.summary?.m5_requested ? "requested" : "not requested"}</span></div>
    </div>
    ${(review.final_gate?.issues || []).length ? `<details class="card review-details"><summary><b>GuardRail review items (${review.final_gate.issues.length})</b></summary>${review.final_gate.issues.map((i) => `<div class="gap ${esc(i.severity)}"><div class="sev">${esc(i.code)} · ${esc(i.severity)}</div><div>${esc(i.message)}</div></div>`).join("")}</details>` : ""}` : "";
  $("#main").innerHTML = `<div class="eyebrow">PRAMAAN-X neuro-symbolic control layer</div><h1>AI Control — M1 to M5</h1>
    <p class="note">This page shows the live backend process state. A model is not labelled as having run merely because its source file exists: <b>INFERENCE_OK</b> is recorded only after an inference call completes.</p>
    ${reviewCard}
    <div class="card ai-model-card"><div class="table-scroll"><table class="tbl ai-model-table"><thead><tr><th>Module</th><th>Model</th><th>Role</th><th>Identifier</th><th>Live status</th><th>Last inference UTC</th><th>Error</th></tr></thead><tbody>${rows}</tbody></table></div></div>
    <div class="grid2"><div class="card"><h2>Text path</h2><code class="snip">Scene notes
  → M1 Granite extraction
  → deterministic parser
  → reconciliation + GuardRail
  → M3 MiniLM semantic checks
  → M4 DeBERTa contradiction checks
  → deterministic EPI / degradation / sequencing / FSL</code></div>
    <div class="card"><h2>Visual path</h2><code class="snip">Uploaded JPG / PNG
  → M2 YOLO-World candidate detection
  → optional M5 Granite Vision shadow scan
  → link to Digital Twins where possible
  → investigator confirmation
  → GuardRail submission gate</code><p class="note">M2/M5 run even when text reconciliation needs review; they never auto-confirm evidence or set the EPI.</p></div></div>
    <div class="card"><h2>IBM Bob connection</h2><p>Bob calls <span class="mono">analyze_scene_ai</span> through the same MCP server. Cases created by Bob persist the same AI-control snapshot and therefore appear with an <b>AI Control · M1–M5</b> tab in this dashboard.</p></div>`;
}

// ------------------------------------------------------------------ MCP
async function showMcp() {
  setNav("mcp"); state.caseId = null; loadCases();
  const m = await api("/api/mcp/tools");
  const host = location.host;
  $("#main").innerHTML = `<div class="eyebrow">Model Context Protocol</div><h1>Pramaan MCP server — ${m.tools.length} tools</h1>
  <p class="note">The same deterministic engine, exposed as typed tools to IBM Bob or any other MCP client. Cases created over MCP appear in this dashboard immediately.</p>
  <div class="grid2"><div class="card"><h2>Connect</h2>
    <div class="kv"><div>Streamable HTTP</div><div class="mono">http://${esc(host)}${esc(m.endpoint)}</div><div>stdio</div><div class="mono">${esc(m.stdio)}</div></div>
    <h3>Client config (stdio)</h3><code class="snip">{
  "mcpServers": {
    "pramaan": {
      "command": "python",
      "args": ["-m", "pramaan.mcp_server"],
      "env": { "PYTHONPATH": "src" }
    }
  }
}</code><p class="note">Run <span class="mono">python -m pramaan mcp-config</span> to print it with absolute paths.</p>
    <h3>IBM Bob — <span class="mono">.bob/mcp.json</span> (shipped in the repo)</h3><code class="snip">{
  "mcpServers": {
    "pramaan": {
      "type": "streamable-http",
      "url": "http://${esc(host)}${esc(m.endpoint)}"
    }
  }
}</code><p class="note">Open the repo in IBM Bob, pick the <b>🔬 Forensic Triage Officer</b> mode and ask it to triage a scene. Bob's calls are ledgered as <span class="mono">ibm-bob</span> and cases appear here live. Guide: <span class="mono">docs/bob-integration.md</span>.</p></div>
  <div class="card" style="padding:0"><table class="tbl"><thead><tr><th>Tool</th><th>What it does</th></tr></thead><tbody>
    ${m.tools.map((t) => `<tr><td class="mono"><b>${esc(t.name)}</b></td><td>${esc(t.summary)}</td></tr>`).join("")}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- router
async function route() {
  closeDrawer();
  const h = location.hash || "#/";
  const m = h.match(/^#\/case\/([^/]+)(?:\/(\w+))?/);
  try {
    if (m) return await showCase(decodeURIComponent(m[1]), m[2]);
    if (h.startsWith("#/new")) return await showNew();
    if (h.startsWith("#/lab")) return await showLab();
    if (h.startsWith("#/network")) return await showNetwork();
    if (h.startsWith("#/benchmark")) return await showBenchmark();
    if (h.startsWith("#/ai")) return await showAI();
    if (h.startsWith("#/mcp")) return await showMcp();
    await loadCases();
    location.hash = state.cases.length ? `#/case/${encodeURIComponent(state.cases[0].case_id)}` : "#/new";
  } catch (e) { toast(e.message, true); }
}

window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
$("#scrim").addEventListener("click", closeDrawer);
(async () => {
  await loadHealth();
  await loadCases();
  route();
  setInterval(() => { loadCases(); loadHealth(); }, 8000); // cases triaged over MCP appear live
})();
