"use strict";
/* UDS Assistant front end. Vanilla JS, no dependencies. All data comes from the FastAPI backend. */

/* ---------- helpers ---------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** el("div", {class:"x", onclick:fn, "aria-label":"y"}, child, "text", [more]) -- text is always a text node (never HTML). */
function el(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "value") n.value = v;
    else if (k === "checked" || k === "disabled" || k === "selected") n[k] = !!v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  const add = (c) => {
    if (Array.isArray(c)) c.forEach(add);
    else if (c === null || c === undefined || c === false) return;
    else n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  };
  kids.forEach(add);
  return n;
}
const clear = (n) => { n.replaceChildren(); return n; };
const $ = (sel, root = document) => root.querySelector(sel);
const pct = (x, d = 1) => (x === null || x === undefined ? "n/a" : (x * 100).toFixed(d) + "%");
const hexSpaced = (h) => (h || "").replace(/\s+/g, "").replace(/(..)(?=.)/g, "$1 ").toUpperCase();
const sget = (k) => { try { return sessionStorage.getItem(k); } catch { return null; } };
const sset = (k, v) => { try { v === null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch { /* ignore */ } };

class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function api(path, body) {
  let res;
  try {
    res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is it running?");
  }
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { data = null; }
  if (!res.ok) {
    let d = data && data.detail !== undefined ? data.detail : text || res.statusText;
    if (typeof d !== "string") d = JSON.stringify(d);
    throw new ApiError(res.status, d);
  }
  return data !== null ? data : text;
}

function toast(msg, kind = "info", ms = 5000) {
  const t = el("div", { class: "toast " + kind, role: kind === "error" ? "alert" : "status" }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? Math.max(ms, 8000) : ms);
}
const failToast = (e) => toast(e.message || String(e), "error");

const spinner = () => el("span", { class: "spin", "aria-hidden": "true" });
const loadingBox = (text) => el("div", { class: "loading", role: "status" }, spinner(), text);
function skeleton(n = 4) { return el("div", { "aria-busy": "true" }, Array.from({ length: n }, () => el("div", { class: "skel" }))); }

/** Run an async action with the button disabled and a spinner; always restore it. */
async function busy(btn, fn) {
  if (btn.disabled) return;
  const label = btn.textContent;
  btn.disabled = true; btn.classList.add("busy");
  btn.prepend(spinner());
  try { return await fn(); }
  catch (e) { failToast(e); }
  finally {
    btn.classList.remove("busy");
    btn.querySelector(".spin")?.remove();
    btn.textContent = label;
    btn.disabled = !!(btn.dataset.llm && !S.llmUp);
  }
}

function download(filename, content, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type: type + ";charset=utf-8" }));
  const a = el("a", { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function field(label, control, id, cls = "") {
  return el("div", { class: "field " + cls }, el("label", { for: id }, label), control);
}
function select(id, options, onchange) {
  const s = el("select", { id, onchange });
  options.forEach((o) => s.append(el("option", { value: o.value }, o.label)));
  return s;
}
function badge(text, tone = "") { return el("span", { class: "badge " + tone }, text); }
function note(tone, ...kids) { return el("div", { class: "note " + tone, role: tone === "err" ? "alert" : null }, ...kids); }
function sectionLabel(text) { return el("span", { class: "lbl" }, text); }

function confTone(c) { return { high: "green", medium: "amber", low: "red" }[c] || ""; }
function layerChip(layer) { return el("span", { class: "layer " + (layer || "") }, layer || "source"); }

function citationCards(cites) {
  if (!cites || !cites.length) return el("div", { class: "kv" }, "No citations.");
  return el("div", {}, cites.map((c) => el("details", { class: "cite" },
    el("summary", {}, c.layer ? layerChip(c.layer) : null, el("span", { class: "src" }, c.source + (c.ref ? "  #" + c.ref : ""))),
    el("blockquote", {}, c.quote || ""))));
}

/* ---------- global state ---------- */
const S = {
  config: null, examples: null, llmUp: true,
  runId: sget("uds_run_id") ? Number(sget("uds_run_id")) : null,
  gen: null,          // last /generate response (notes, dropped_count, provenance)
  views: [],          // test views from /runs/{id}/tests
  sel: null, filter: "all",
  lastRun: null, coverage: null, report: null,
};
function setRunId(id) { S.runId = id; sset("uds_run_id", id === null ? null : String(id)); }
const approvedCount = () => S.views.filter((v) => v.test.review_status === "human_reviewed").length;

/* ---------- header ---------- */
function renderHeader() {
  const c = S.config;
  $("#banner-text").textContent = c.banner;
  const chips = clear($("#chips"));
  chips.append(
    el("span", { class: "chip " + (c.ollama_reachable ? "green" : "red") }, el("span", { class: "dot " + (c.ollama_reachable ? "green" : "red") }),
      c.ollama_reachable ? "Ollama reachable" : "Ollama unreachable"),
    el("span", { class: "chip" }, "Model ", el("b", {}, c.model)),
    el("span", { class: "chip" }, "num_ctx ", el("b", {}, c.num_ctx)),
    el("span", { class: "chip" }, "Retriever ", el("b", {}, c.retriever)),
    el("span", { class: "chip" }, "ECU ", el("b", {}, c.ecu_name)));
  const rb = $("#remote-bar");
  rb.classList.toggle("hidden", !c.remote_warning);
  $(".wrap", rb).textContent = c.remote_warning || "";
  const ob = $("#ollama-bar");
  ob.classList.toggle("hidden", c.ollama_reachable);
  $(".wrap", ob).textContent = "Ollama is not reachable at " + c.ollama_url + ". Start Ollama and pull " + c.model + " (ollama pull " + c.model + "). Ask and Generate are disabled; checking a request, running and exporting existing tests still work.";
  S.llmUp = !!c.ollama_reachable;
  document.querySelectorAll("[data-llm]").forEach((b) => { if (!b.classList.contains("busy")) b.disabled = !S.llmUp; });
}

/* ---------- ASK tab ---------- */
const A = {};
function buildAsk() {
  const root = clear($("#tab-ask"));
  const ex = S.examples;
  A.q = el("textarea", { id: "ask-q", rows: 2, placeholder: "e.g. What is the length of DID 0xF190?" });
  A.q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); A.btn.click(); } });
  const exSel = select("ask-ex", [{ value: "", label: "Example questions..." }, ...ex.questions.map((q) => ({ value: q, label: q }))],
    (e) => { if (e.target.value) A.q.value = e.target.value; });
  A.btn = el("button", { class: "btn primary", "data-llm": "1", onclick: () => busy(A.btn, doAsk) }, "Ask");
  A.btn.disabled = !S.llmUp;
  A.out = el("div", { "aria-live": "polite" });
  root.append(el("div", { class: "card" },
    el("h2", {}, "Ask a question"),
    el("p", { class: "hint" }, "Answers are drawn only from the approved sources (standard, OEM, ECU spec, project) and always cite them."),
    el("div", { class: "row", style: "align-items:flex-start" }, el("div", { class: "grow" }, field("Question", A.q, "ask-q")), field("Examples", exSel, "ask-ex", "grow")),
    el("div", { class: "row", style: "margin-top:10px" }, A.btn), A.out));
  root.append(buildValidate());
}

async function doAsk() {
  const q = A.q.value.trim();
  if (!q) { toast("Type a question first.", "error"); return; }
  clear(A.out).append(loadingBox("Searching the approved sources (about 5 s)..."));
  try {
    const r = await api("/ask", { question: q });
    renderAnswer(r);
  } catch (e) { clear(A.out); throw e; }
}

function renderAnswer(r) {
  const out = clear(A.out);
  if (r.status === "not_found") out.append(note("warn", el("b", {}, "Not found in the approved sources."), " The assistant will not guess."));
  else out.append(el("div", { class: "answer" }, r.answer));
  out.append(el("div", { class: "row", style: "align-items:center" },
    r.confidence ? badge("Confidence: " + r.confidence, confTone(r.confidence)) : null,
    r.confidence_reason ? el("span", { class: "kv" }, r.confidence_reason) : null));
  if (r.fallback_events && r.fallback_events.length) out.append(note("info", "Fallbacks: " + r.fallback_events.map((x) => typeof x === "string" ? x : JSON.stringify(x)).join("; ")));
  if (r.status !== "not_found") out.append(el("div", { class: "sect" }, sectionLabel("Citations"), citationCards(r.citations)));
}

/* check a raw request */
const V = {};
function buildValidate() {
  const ex = S.examples;
  V.hex = el("input", { type: "text", id: "v-hex", class: "mono", value: "2E 01 00 11", autocomplete: "off", spellcheck: "false" });
  V.session = select("v-session", ex.sessions.map((s) => ({ value: s.id, label: s.name + " (0x" + s.id.toString(16).toUpperCase().padStart(2, "0") + ")" })));
  V.level = select("v-level", [{ value: "", label: "none (locked)" }, ...ex.security_levels.map((l) => ({ value: l.level, label: "level 0x" + l.level.toString(16).toUpperCase().padStart(2, "0") + " " + l.name }))]);
  V.speed = el("input", { type: "number", id: "v-speed", min: 0, value: 0 });
  V.actual = el("input", { type: "text", id: "v-actual", class: "mono", placeholder: "optional, e.g. 7F 2E 33 (separate several frames with |)", autocomplete: "off", spellcheck: "false" });
  const exSel = select("v-ex", [{ value: "", label: "Example requests..." }, ...ex.raw_requests.map((r, i) => ({ value: i, label: r.label }))], (e) => {
    const r = ex.raw_requests[e.target.value]; if (!r) return;
    V.hex.value = r.hex; V.session.value = r.session; V.level.value = r.unlocked_level === null ? "" : r.unlocked_level;
  });
  V.session.value = 3;
  V.btn = el("button", { class: "btn primary", onclick: () => busy(V.btn, doValidate) }, "Check");
  [V.hex, V.speed, V.actual].forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") V.btn.click(); }));
  V.out = el("div", { "aria-live": "polite" });
  return el("div", { class: "card" },
    el("h2", {}, "Check a raw request"),
    el("p", { class: "hint" }, "Deterministic rules engine, no model involved: what must a compliant ECU answer to these bytes in this state?"),
    el("div", { class: "row" },
      field("Request hex", V.hex, "v-hex", "grow"), field("Session", V.session, "v-session"),
      field("Unlocked level", V.level, "v-level"), field("Speed (km/h)", V.speed, "v-speed", ""), field("Example", exSel, "v-ex", "grow")),
    el("div", { class: "row", style: "margin-top:10px" }, field("Observed ECU response (optional: compare it with the prediction)", V.actual, "v-actual", "grow")),
    el("div", { class: "row", style: "margin-top:10px" }, V.btn), V.out);
}

async function doValidate() {
  const hex = V.hex.value.trim();
  if (!hex) { toast("Enter request bytes, e.g. 22 F1 90.", "error"); return; }
  clear(V.out).append(loadingBox("Evaluating..."));
  try {
    const r = await api("/validate", {
      request_hex: hex, session: Number(V.session.value),
      unlocked_level: V.level.value === "" ? null : Number(V.level.value),
      vehicle_speed_kph: Math.max(0, parseInt(V.speed.value || "0", 10) || 0),
      actual_response_hex: V.actual.value.trim() || null,
    });
    renderValidate(r);
  } catch (e) { clear(V.out); throw e; }
}

function renderValidate(r) {
  const out = clear(V.out);
  out.append(el("div", { class: "row", style: "align-items:center; margin-top:12px" },
    badge(r.structurally_valid ? "valid structure" : "invalid structure", r.structurally_valid ? "green" : "red"),
    badge("outcome: " + r.outcome.replace("_", " "), { positive: "green", negative: "red" }[r.outcome] || "amber"),
    el("span", { class: "kv" }, r.decoded || "")));
  if (r.parse_error) out.append(note("err", r.parse_error));
  const bytes = r.expected_responses_hex && r.expected_responses_hex.length ? r.expected_responses_hex.map(hexSpaced).join("  |  ") : "(no response)";
  out.append(el("div", { class: "sect" }, sectionLabel("Expected response"),
    el("div", { class: "expected " + r.outcome }, bytes),
    r.expected_text ? el("div", { class: "kv" }, r.expected_text) : null));
  if (r.comparison) out.append(el("div", { class: "sect" }, sectionLabel("Comparison with the observed response"),
    badge(r.comparison === "match" ? "MATCH" : "MISMATCH", r.comparison === "match" ? "green" : "red"),
    el("div", { class: "kv", style: "margin-top:6px" }, r.comparison_detail)));
  if (r.reason) out.append(el("div", { class: "sect" }, sectionLabel("Reason"), el("div", {}, r.reason)));
  if (r.trace && r.trace.length) out.append(el("details", { class: "plain sect" }, el("summary", {}, "Rules-engine trace (" + r.trace.length + " steps)"), el("pre", { class: "trace" }, r.trace.join("\n"))));
  if (r.citations && r.citations.length) out.append(el("div", { class: "sect" }, sectionLabel("Citations"), citationCards(r.citations)));
}

/* ---------- GENERATE tab ---------- */
const G = {};
function buildGenerate() {
  const root = clear($("#tab-generate"));
  const ex = S.examples;
  G.text = el("textarea", { id: "g-text", rows: 3, placeholder: "Describe a requirement in natural language, e.g. The tester shall be able to read the VIN (DID 0xF190) in any diagnostic session." });
  G.id = el("input", { type: "text", id: "g-id", placeholder: "REQ-001", autocomplete: "off" });
  const exSel = select("g-ex", [{ value: "", label: "Example requirements..." }, ...ex.requirements.map((r, i) => ({ value: i, label: r.label }))], (e) => {
    const r = ex.requirements[e.target.value]; if (!r) return; G.text.value = r.text; G.id.value = r.id;
  });
  G.btn = el("button", { class: "btn primary", "data-llm": "1", onclick: () => busy(G.btn, doGenerate) }, "Generate tests");
  G.btn.disabled = !S.llmUp;
  G.meta = el("div");
  G.main = el("div");
  root.append(el("div", { class: "card" },
    el("h2", {}, "Generate tests from a requirement"),
    el("p", { class: "hint" }, "The model only selects and parameterises vetted templates; the rules engine computes every expected byte. Generation takes about 20 s."),
    el("div", { class: "row" }, field("Example", exSel, "g-ex", "grow"), field("Requirement ID", G.id, "g-id")),
    el("div", { style: "margin-top:10px" }, field("Requirement text", G.text, "g-text")),
    el("div", { class: "row", style: "margin-top:10px" }, G.btn)), G.meta, G.main);
  if (S.runId !== null) loadViews();
}

async function doGenerate() {
  const text = G.text.value.trim();
  if (!text) { toast("Enter a requirement first.", "error"); return; }
  clear(G.meta); clear(G.main).append(el("div", { class: "card" }, loadingBox("Generating and validating tests (about 20 s)..."), skeleton(5)));
  try {
    const r = await api("/generate", { requirement_text: text, requirement_id: G.id.value.trim() || null });
    S.gen = r; S.lastRun = null; S.coverage = null;
    if (r.run_id === null || r.run_id === undefined) { throw new Error("The server did not store this run, so tests cannot be reviewed."); }
    setRunId(r.run_id);
    await loadViews(true);
    toast("Generated " + r.tests.length + " test(s) for " + r.requirement_id + ".", "success");
  } catch (e) { clear(G.main); throw e; }
}

async function loadViews(select0) {
  try {
    const r = await api("/runs/" + S.runId + "/tests");
    S.views = r.tests;
    if (select0 || !S.views.some((v) => v.test.id === S.sel)) S.sel = S.views.length ? S.views[0].test.id : null;
    if (select0) S.filter = "all";
    renderGenerate();
  } catch (e) {
    if (e.status === 404) { setRunId(null); S.views = []; S.gen = null; clear(G.main); clear(G.meta); }
    else { clear(G.main); throw e; }
  }
}

function renderGenerate() {
  const meta = clear(G.meta);
  if (S.gen) {
    meta.append(el("div", { class: "note info" }, S.gen.governance_banner || "", " (run ", el("b", {}, "#" + S.runId), ", requirement ", el("b", {}, S.gen.requirement_id), ")"));
    (S.gen.notes || []).forEach((n) => meta.append(note("info", n)));
    if (S.gen.dropped_count > 0) meta.append(note("warn", el("b", {}, S.gen.dropped_count + " candidate test(s) dropped"), " because they failed validation."));
  } else if (S.views.length && S.views.every((v) => v.test.origin === "imported")) {
    meta.append(el("div", { class: "note info" }, "Imported tests of run ", el("b", {}, "#" + S.runId), ". They matched the rules engine but are only 'validated': approve the ones you trust before running or exporting."));
  } else meta.append(el("div", { class: "note info" }, "Showing the tests of run ", el("b", {}, "#" + S.runId), " restored from this browser session."));
  const main = clear(G.main);
  if (!S.views.length) { main.append(el("div", { class: "card empty" }, el("h3", {}, "No tests in this run"), "The generator produced no valid test cases for this requirement.")); return; }
  const cats = {};
  S.views.forEach((v) => { cats[v.test.category] = (cats[v.test.category] || 0) + 1; });
  const list = el("div", { role: "listbox", "aria-label": "Tests" });
  const visible = S.views.filter((v) => S.filter === "all" || v.test.category === S.filter);
  const chip = (key, label, n) => el("button", { class: "fchip", "aria-pressed": String(S.filter === key), onclick: () => { S.filter = key; renderGenerate(); } }, label, el("span", { class: "n" }, n));
  visible.forEach((v) => list.append(testItem(v)));
  if (!visible.length) list.append(el("div", { class: "kv" }, "No tests in this category."));
  const listCol = el("div", { class: "card listcol" },
    el("h2", {}, S.views.length + " tests", " ", el("span", { class: "kv" }, approvedCount() + " approved")),
    el("div", { class: "filters" }, chip("all", "all", S.views.length), Object.keys(cats).sort().map((c) => chip(c, c, cats[c]))), list);
  const detail = el("div", { id: "detail" });
  main.append(el("div", { class: "md" }, listCol, detail));
  renderDetail(detail);
}

function reviewTone(label) {
  const l = (label || "").toLowerCase();
  if (l.includes("reject")) return "red";
  if (l.includes("human") || l.includes("approv")) return "green";
  if (l.includes("valid")) return "blue";
  return "amber";
}
const ORIGIN = { imported: ["imported", "blue"], generated: ["AI-generated", ""], gold: ["gold", ""] };
function originBadge(t) { const [label, tone] = ORIGIN[t.origin] || [t.origin, ""]; return badge(label, tone); }
function confDot(c) { return el("span", { class: "dot " + confTone(c), title: "confidence: " + (c || "unknown"), style: "margin-top:7px" }); }

function testItem(v) {
  const t = v.test;
  const b = el("button", { class: "titem", role: "option", "aria-selected": String(t.id === S.sel), onclick: () => { S.sel = t.id; renderGenerate(); } },
    el("div", { class: "tt" }, confDot(t.confidence), el("span", {}, t.title)),
    el("div", { class: "meta" }, el("span", { class: "cat" }, t.category), originBadge(t), badge(v.review_label || t.review_status, reviewTone(v.review_label || t.review_status))));
  return b;
}

function stepNode(s) {
  if (s.kind === "send") {
    return el("li", {},
      el("div", { class: "line" }, s.line),
      el("div", { class: "sub" }, s.request_text, s.response_texts && s.response_texts.length ? " -> " + s.response_texts.join("; ") : ""),
      s.max_response_time_ms ? el("div", { class: "sub" }, "within " + s.max_response_time_ms + " ms") : null);
  }
  const detail = s.detail && Object.keys(s.detail).length ? Object.entries(s.detail).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length)).map(([k, v]) => k + ": " + (typeof v === "object" ? JSON.stringify(v) : v)).join(", ") : "";
  return el("li", {}, el("div", {}, badge(s.kind), " ", s.description || ""), detail ? el("div", { class: "sub" }, detail) : null);
}

function renderDetail(host) {
  clear(host);
  const v = S.views.find((x) => x.test.id === S.sel);
  if (!v) return;
  const t = v.test;
  const prov = (S.gen && S.gen.target_provenance && S.gen.target_provenance[t.id]) || [];
  const card = el("div", { class: "card" });
  card.append(
    el("div", { class: "row", style: "align-items:center; margin-bottom:6px" }, el("span", { class: "cat" }, t.category), badge(v.review_label || t.review_status, reviewTone(v.review_label || t.review_status)),
      originBadge(t), t.confidence ? badge("confidence: " + t.confidence, confTone(t.confidence)) : null, el("span", { class: "kv mono" }, t.id)),
    el("h2", { style: "font-size:18px" }, t.title),
    t.confidence_reason ? el("div", { class: "kv" }, t.confidence_reason) : null,
    el("div", { class: "sect" }, sectionLabel("Preconditions"), t.preconditions.length ? el("ul", { class: "bul" }, t.preconditions.map((p) => el("li", {}, p))) : el("div", { class: "kv" }, "None.")),
    el("div", { class: "sect" }, sectionLabel("Pass criteria"), el("div", { class: "callout" }, t.pass_criteria)),
    el("div", { class: "sect" }, sectionLabel("Steps"), el("ol", { class: "timeline" }, v.steps.map(stepNode))));
  if (prov.length) card.append(el("div", { class: "sect" }, sectionLabel("Targets"), el("div", { class: "tchips" }, prov.map((p) =>
    el("span", { class: "badge " + (p.written ? "green" : "amber"), title: p.written ? "named in the requirement text" : "inferred from the requirement" },
      p.kind + " " + p.id + (p.name ? " " + p.name : ""), " · ", p.written ? "written" : "inferred")))));
  if (t.provenance) card.append(el("div", { class: "sect" }, sectionLabel("Import provenance"),
    el("div", { class: "kv" }, "Not AI-generated. Suite ", el("b", {}, t.provenance.suite), ", file ", el("b", {}, t.provenance.source_file), ", id ", el("b", {}, t.provenance.source_id),
      t.provenance.source_template ? ", your template " : "", t.provenance.source_template ? el("b", {}, t.provenance.source_template) : null, ". SHA-256 ", el("span", { class: "mono" }, t.provenance.source_sha256.slice(0, 16) + "..."))));
  if (t.explanation) card.append(el("div", { class: "sect" }, sectionLabel("Explanation"), el("div", {}, t.explanation)));
  card.append(el("div", { class: "sect" }, sectionLabel("Citations (" + t.citations.length + ")"), citationCards(t.citations)));
  card.append(el("div", { class: "sect" }, sectionLabel("Review"), reviewPanel(v)));
  card.append(bulkPanel());
  host.append(card);
}

function reviewPanel(v) {
  const t = v.test;
  const comment = el("textarea", { id: "rv-comment", rows: 2, placeholder: "Optional comment (required for 'Add comment')" });
  const send = async (action, btn) => {
    const text = comment.value.trim();
    if (action === "comment" && !text) { toast("Write a comment first.", "error"); return; }
    const nv = await api("/runs/" + S.runId + "/tests/" + encodeURIComponent(t.id) + "/review", { action, comment: text });
    const i = S.views.findIndex((x) => x.test.id === t.id);
    if (i >= 0) S.views[i] = nv;
    renderGenerate();
    toast({ approve: "Approved", reject: "Rejected", comment: "Comment added" }[action] + ": " + t.id, "success");
  };
  const mk = (cls, label, action) => { const b = el("button", { class: "btn " + cls, onclick: () => busy(b, () => send(action, b)) }, label); return b; };
  const log = v.review_log || [];
  return el("div", { class: "review" },
    el("label", { class: "lbl", for: "rv-comment" }, "Reviewer comment"), comment,
    el("div", { class: "row" }, mk("good", "Approve", "approve"), mk("bad", "Reject", "reject"), mk("", "Add comment", "comment")),
    log.length ? el("ul", { class: "log" }, log.map((l) => el("li", {}, el("b", {}, l.action), l.comment ? ": " + l.comment : ""))) : el("div", { class: "kv", style: "margin-top:8px" }, "No review entries yet."));
}

function bulkPanel() {
  const b = el("button", { class: "btn warn", onclick: () => busy(b, async () => {
    if (!confirm("Approve ALL tests with status 'validated' in this run?\n\nThis records a review entry for each, without you reading them one by one. Use only if you have reviewed the list.")) return;
    const r = await api("/runs/" + S.runId + "/approve-validated", {});
    await loadViews();
    toast("Bulk approved " + r.approved.length + " test(s).", "success");
  }) }, "Bulk approve all validated tests");
  return el("div", { class: "bulk" }, el("div", { class: "lbl" }, "Bulk action (whole run, not just this test)"), el("div", { class: "kv", style: "margin:4px 0 8px" }, "Approves every test currently marked validated. Per-test review above is the preferred path."), b);
}

/* ---------- RUN & EXPORT tab ---------- */
const R = {};
function emptyRun(msg) {
  return el("div", { class: "card empty" }, el("h3", {}, "Nothing to run yet"), msg,
    el("div", {}, el("a", { class: "btn primary", href: "#generate", style: "text-decoration:none; display:inline-flex" }, "Go to Generate & Review")));
}

function buildRun() {
  const root = clear($("#tab-run"));
  R.empty = el("div"); R.body = el("div");
  const bugs = S.examples.bugs; const groups = {};
  bugs.forEach((b) => { (groups[b.group] = groups[b.group] || []).push(b); });
  R.bug = el("select", { id: "r-bug", onchange: updateBugDesc }, el("option", { value: "" }, "No bug (clean simulator)"),
    Object.keys(groups).map((g) => el("optgroup", { label: g }, groups[g].map((b) => el("option", { value: b.id }, b.title)))));
  R.bugDesc = el("div", { class: "kv" });
  R.incl = el("input", { type: "checkbox", id: "r-incl", onchange: () => { R.warn.classList.toggle("hidden", !R.incl.checked); updateCounts(); } });
  R.warn = el("div", { class: "note warn hidden" }, el("b", {}, "Demo only: "), "unreviewed tests bypass expert review. Do not use results from this mode as evidence.");
  R.counts = el("div", { class: "kv", style: "margin-top:6px" });
  R.runBtn = el("button", { class: "btn primary", onclick: () => busy(R.runBtn, doRun) }, "Run on simulator");
  R.pyBtn = el("button", { class: "btn", onclick: () => busy(R.pyBtn, () => doExport("pytest")) }, "Download pytest file");
  R.caplBtn = el("button", { class: "btn", onclick: () => busy(R.caplBtn, () => doExport("capl")) }, "Download CAPL template (unverified, never run in CANoe)");
  R.out = el("div", { "aria-live": "polite" });
  R.cov = el("div");
  R.body.append(
    el("div", { class: "card" }, el("h2", {}, "Run on the simulator"),
      el("p", { class: "hint" }, "Runs the approved tests against the simulated ECU, optionally with one injected bug, and reports which tests catch it."),
      R.counts,
      el("div", { class: "sect" }, el("label", { class: "check" }, R.incl, "Include unreviewed tests (demo only, bypasses expert review)"), R.warn),
      el("div", { class: "row", style: "margin-top:10px" }, field("Injected bug", R.bug, "r-bug", "grow"), R.runBtn),
      R.bugDesc, R.out),
    el("div", { class: "card" }, el("h2", {}, "Export"),
      el("p", { class: "hint" }, "Exports use the same scope as the run (approved tests unless the demo override is on)."),
      el("div", { class: "row" }, R.pyBtn, R.caplBtn),
      note("warn", "Safety: FOR SIMULATOR OR APPROVED LAB BENCH ONLY. NEVER RUN AGAINST A PRODUCTION VEHICLE. The CAPL file is an unverified template and has never been compiled or run in CANoe.")),
    R.cov);
  root.append(R.empty, R.body);
  updateBugDesc();
}
function updateBugDesc() {
  const b = S.examples.bugs.find((x) => x.id === R.bug.value);
  R.bugDesc.textContent = b ? b.description : "The clean simulator follows the specification exactly; every approved test should pass.";
}
function updateCounts() {
  const total = S.views.length, ap = approvedCount();
  clear(R.counts).append(el("b", {}, ap + " of " + total + " tests approved"), " (run #" + S.runId + "). ",
    R.incl.checked ? "All " + total + " will be used." : ap === 0 ? "None are approved yet, so a run or export will be refused." : "Only the approved ones will be used.");
}

async function refreshRun() {
  if (!R.body) buildRun();
  if (S.runId === null) { clear(R.empty).append(emptyRun("Generate tests for a requirement and approve them first.")); R.body.classList.add("hidden"); return; }
  clear(R.empty).append(loadingBox("Loading run #" + S.runId + "..."));
  R.body.classList.add("hidden");
  try {
    const r = await api("/runs/" + S.runId + "/tests");
    S.views = r.tests; clear(R.empty); R.body.classList.remove("hidden"); updateCounts();
    if (S.coverage && S.coverage.run_id === S.runId) renderCoverage(); else loadCoverage();
  } catch (e) {
    if (e.status === 404) { setRunId(null); S.views = []; clear(R.empty).append(emptyRun("The remembered run no longer exists.")); }
    else { clear(R.empty).append(note("err", e.message)); }
  }
}

function noApproved(e, host) {
  clear(host).append(el("div", { class: "card empty" }, el("h3", {}, "No approved tests"), e.message,
    el("div", {}, el("a", { class: "btn primary", href: "#generate", style: "text-decoration:none; display:inline-flex" }, "Go to Generate & Review"))));
}

async function doRun() {
  const bug = R.bug.value;
  clear(R.out).append(loadingBox("Running tests on the simulator..."));
  try {
    const r = await api("/run", { run_id: S.runId, bugs: bug ? [bug] : [], include_unreviewed: R.incl.checked });
    S.lastRun = r; renderRunResult(r);
  } catch (e) { if (e.status === 409) { noApproved(e, R.out); return; } clear(R.out); throw e; }
}

function renderRunResult(r) {
  const v = r.view; const out = clear(R.out);
  const bugged = v.bugs && v.bugs.length;
  let tone, headline, sub = "";
  if (!bugged) { tone = v.passed === v.total ? "green" : "red"; headline = v.passed === v.total ? "All tests pass on the clean simulator" : (v.total - v.passed) + " test(s) fail on the clean simulator"; }
  else if (v.caught_ids.length) { tone = "green"; headline = "Bug caught by " + v.caught_ids.length + " test(s)"; }
  else { tone = "amber"; headline = "Bug not caught"; sub = "No test that passes on the clean simulator fails with " + v.bugs.join(", ") + "."; }
  if (v.invalid_ids.length) sub += (sub ? " " : "") + v.invalid_ids.length + " test(s) fail even on the clean simulator and get no credit for catching the bug.";
  out.append(el("div", { class: "verdict " + tone }, el("div", {}, el("div", { class: "big" }, headline), sub ? el("div", {}, sub) : null),
    el("div", { style: "margin-left:auto; text-align:right" }, el("div", { class: "metric" }, v.passed + "/" + v.total), el("div", {}, "passed"))));
  if (v.clean_passed !== null && v.clean_passed !== undefined && bugged) out.append(el("div", { class: "kv" }, "Clean simulator baseline: " + v.clean_passed + "/" + v.total + " passed."));
  const rows = v.results.map((x) => el("tr", {},
    el("td", {}, x.title, el("div", { class: "kv mono" }, x.test_id)), el("td", {}, x.category),
    el("td", {}, badge(x.passed ? "PASS" : "FAIL", x.passed ? "green" : "red"), x.caught ? [" ", badge("caught bug", "blue")] : null),
    el("td", {}, x.failure_detail || "")));
  out.append(el("div", { class: "tbl-wrap sect" }, el("table", {}, el("thead", {}, el("tr", {}, ["Test", "Category", "Result", "Failure"].map((h) => el("th", {}, h)))), el("tbody", {}, rows))));
  const fails = v.results.filter((x) => !x.passed && x.failure).slice(0, 10);
  if (fails.length) {
    out.append(el("div", { class: "sect" }, sectionLabel("Failing steps (first " + fails.length + ")"), fails.map((x) => el("details", { class: "cite" },
      el("summary", {}, badge("FAIL", "red"), el("span", {}, x.title), el("span", { class: "src" }, "step " + x.failure.index)),
      el("div", { class: "fail-panel", style: "padding:8px 14px 12px; border-top:1px solid var(--border)" },
        el("div", {}, "Request: " + hexSpaced(x.failure.request_hex), x.failure.request_text ? "  (" + x.failure.request_text + ")" : ""),
        el("div", {}, "Expected: " + x.failure.expected), el("div", {}, "Actual: " + x.failure.actual),
        x.failure.detail ? el("div", { class: "kv" }, x.failure.detail) : null)))));
  }
}

async function doExport(format) {
  const r = await api("/export", { run_id: S.runId, format, include_unreviewed: R.incl.checked }).catch((e) => {
    if (e.status === 409) { noApproved(e, R.out); toast(e.message, "error"); return null; }
    throw e;
  });
  if (!r) return;
  download(r.filename, r.content);
  toast("Downloaded " + r.filename, "success");
}

/* coverage */
const KINDS = [["service", "Services"], ["did", "DIDs"], ["routine", "Routines"], ["nrc", "NRCs"], ["session", "Sessions"], ["security_level", "Security levels"]];
async function loadCoverage() {
  clear(R.cov).append(el("div", { class: "card" }, loadingBox("Computing coverage..."), skeleton(3)));
  try {
    const c = await api("/coverage", { run_id: S.runId });
    S.coverage = { run_id: S.runId, ...c }; renderCoverage();
  } catch (e) { clear(R.cov).append(note("err", "Coverage failed: " + e.message)); }
}
function renderCoverage() {
  const { report, markdown } = S.coverage; const card = el("div", { class: "card" });
  const totalUnc = Object.values(report.uncovered || {}).reduce((a, l) => a + l.length, 0);
  const dl = el("button", { class: "btn", onclick: () => download("coverage_report.md", markdown, "text/markdown") }, "Download coverage report (Markdown)");
  card.append(el("h2", {}, "Coverage of this run's tests against the spec"),
    el("p", { class: "hint" }, "Covers all " + report.tests + " tests of the run (approved or not), not only the approved subset."),
    el("div", { class: "metrics" }, m(report.tests, "tests", ""), m(totalUnc, "uncovered spec items", totalUnc ? "mid" : "good"),
      KINDS.map(([k, lab]) => { const it = (report.items[k] || []); const z = it.filter((x) => x.tests === 0).length; return m((it.length - z) + "/" + it.length, lab + " touched", z ? "mid" : "good"); })),
    el("div", { class: "sect" }, sectionLabel("Tests by category"), bars(report.by_category)), el("div", { class: "sect" }, dl));
  KINDS.forEach(([k, lab]) => {
    const items = report.items[k] || []; if (!items.length) return;
    const withPN = ["service", "did", "routine"].includes(k); const zero = items.filter((x) => x.tests === 0).length;
    card.append(el("div", { class: "sect" }, el("h3", {}, lab, " ", el("span", { class: "kv" }, zero + " uncovered of " + items.length)),
      el("div", { class: "tbl-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Item"), el("th", { class: "num" }, "Tests"), withPN ? [el("th", { class: "num" }, "Positive"), el("th", { class: "num" }, "Negative")] : null)),
        el("tbody", {}, items.map((x) => el("tr", { class: x.tests === 0 ? "zero" : "" },
          el("td", { class: "mono" }, x.item, x.tests === 0 ? el("span", { class: "tag-un" }, "UNCOVERED") : null), el("td", { class: "num" }, x.tests),
          withPN ? [el("td", { class: "num" }, x.positive), el("td", { class: "num" }, x.negative)] : null)))))));
  });
  clear(R.cov).append(card);
}
function m(v, k, tone) { return el("div", { class: "m " + tone }, el("div", { class: "v" }, v), el("div", { class: "k" }, k)); }
function bars(obj) {
  const max = Math.max(1, ...Object.values(obj));
  return el("div", { class: "bars" }, Object.entries(obj).map(([k, n]) => el("div", { class: "b" }, el("span", {}, k),
    el("div", { class: "track" }, el("div", { class: "fill", style: "width:" + (n / max * 100) + "%" })), el("span", { class: "mono" }, n))));
}

/* ---------- IMPORT & COMPARE tab ---------- */
const I = {};
const CMP_KINDS = [["service", "Services"], ["did", "DIDs"], ["routine", "Routines"], ["nrc", "NRCs"], ["session", "Sessions"], ["security_level", "Security levels"], ["timing", "Timing cases"]];
const STATUS_TONE = { accepted: "green", oracle_mismatch: "amber", invalid: "red" };
const STATUS_TEXT = { accepted: "accepted", oracle_mismatch: "rules-engine mismatch", invalid: "invalid" };

function buildImport() {
  const root = clear($("#tab-import"));
  I.file = el("input", { type: "file", id: "i-file", accept: ".yaml,.yml,text/yaml,text/plain" });
  I.text = null; I.name = "upload.yaml";
  I.fileInfo = el("div", { class: "kv" }, "No file chosen.");
  I.file.addEventListener("change", async () => {
    const f = I.file.files[0]; if (!f) return;
    if (f.size > 512 * 1024) { toast("The file is larger than 512 KB.", "error"); I.file.value = ""; return; }
    I.text = await f.text(); I.name = f.name; I.fileInfo.textContent = f.name + " (" + f.size + " bytes)";
  });
  I.example = el("button", { class: "btn", onclick: () => busy(I.example, async () => {
    const f = await api("/import/format");
    I.text = f.example; I.name = f.example_filename; I.file.value = ""; I.fileInfo.textContent = "Example loaded: " + f.example_filename;
  }) }, "Use the example suite");
  I.btn = el("button", { class: "btn primary", onclick: () => busy(I.btn, doImport) }, "Import and validate");
  I.fmt = el("details", { class: "cite" }, el("summary", {}, "Import format (YAML, version 1)"), el("pre", { class: "trace", id: "i-fmt" }, "Loading..."));
  I.result = el("div", { "aria-live": "polite" });
  I.cmp = el("div");
  I.sel = el("select", { id: "i-run" });
  I.gsel = el("select", { id: "i-gen" });
  I.cmpBtn = el("button", { class: "btn primary", onclick: () => busy(I.cmpBtn, doCompare) }, "Compare coverage");
  root.append(
    el("div", { class: "card" }, el("h2", {}, "Import an existing UDS test suite"),
      el("p", { class: "hint" }, "Upload a YAML file of tests you already have. Each test is checked against the rules engine for the synthetic spec; nothing is rewritten and no model is used. Imported tests are never auto-approved: review them on Generate & Review before running or exporting."),
      el("div", { class: "row" }, field("YAML file", I.file, "i-file", "grow"), I.example, I.btn), I.fileInfo, I.fmt),
    I.result,
    el("div", { class: "card" }, el("h2", {}, "Baseline coverage and comparison"),
      el("p", { class: "hint" }, "Static coverage of the accepted imported tests against the spec, compared with the assistant's generated tests and with both together. Nothing is executed. Review status does not matter here."),
      el("div", { class: "row" }, field("Imported suite", I.sel, "i-run", "grow"), field("Compare with", I.gsel, "i-gen", "grow"), I.cmpBtn)),
    I.cmp);
  api("/import/format").then((f) => { $("#i-fmt").textContent = f.documentation || f.example; }).catch(() => { $("#i-fmt").textContent = "Could not load the format description."; });
}

async function refreshImport() {
  try {
    const [imps, runs] = await Promise.all([api("/imports"), api("/runs")]);
    const keep = I.sel.value, keepG = I.gsel.value;
    I.sel.replaceChildren(...(imps.length ? imps.map((r) => el("option", { value: r.run_id }, "#" + r.run_id + " " + r.suite + " (" + r.accepted + " accepted of " + r.total + ")")) : [el("option", { value: "" }, "Import a file first")]));
    const gens = runs.filter((r) => r.llm_mode !== "import");
    I.gsel.replaceChildren(el("option", { value: "" }, "All generated runs (" + gens.length + ")"), ...gens.map((r) => el("option", { value: r.id }, "Generated run #" + r.id + " " + r.requirement_id)));
    if (keep && [...I.sel.options].some((o) => o.value === keep)) I.sel.value = keep;
    else if (S.runId !== null && [...I.sel.options].some((o) => o.value === String(S.runId))) I.sel.value = String(S.runId);
    if (keepG) I.gsel.value = keepG;
  } catch (e) { failToast(e); }
}

async function doImport() {
  if (!I.text) { toast("Choose a YAML file or load the example first.", "error"); return; }
  clear(I.result).append(el("div", { class: "card" }, loadingBox("Validating against the rules engine..."), skeleton(3)));
  try {
    const r = await api("/import", { filename: I.name, content: I.text });
    setRunId(r.run_id); S.gen = null; S.lastRun = null; S.coverage = null; S.views = [];
    renderImportResult(r);
    await refreshImport();
    toast("Imported " + r.accepted + " of " + r.total + " test(s).", r.accepted ? "success" : "info");
  } catch (e) { clear(I.result); throw e; }
}

function renderImportResult(r) {
  const card = el("div", { class: "card" });
  card.append(el("h2", {}, "Import result: " + r.suite),
    el("div", { class: "note info" }, r.governance_banner, " (run ", el("b", {}, "#" + r.run_id), ", file ", el("b", {}, r.source_file), ", SHA-256 ", el("span", { class: "mono" }, r.sha256.slice(0, 16) + "..."), ")"),
    el("div", { class: "metrics" }, m(r.total, "tests in file", ""), m(r.accepted, "accepted (validated, awaiting review)", r.accepted ? "good" : "mid"),
      m(r.oracle_mismatch, "rules-engine mismatch", r.oracle_mismatch ? "mid" : "good"), m(r.invalid, "invalid", r.invalid ? "mid" : "good")),
    el("div", { class: "tbl-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Id"), el("th", {}, "Title"), el("th", {}, "Category"), el("th", {}, "Outcome"), el("th", {}, "Why"))),
      el("tbody", {}, r.outcomes.map((o) => el("tr", {}, el("td", { class: "mono" }, o.source_id), el("td", {}, o.title), el("td", {}, o.category || "-"),
        el("td", {}, badge(STATUS_TEXT[o.status], STATUS_TONE[o.status])), el("td", { class: "mono" }, o.errors.join(" | ") || "matches the rules engine")))))),
    el("div", { class: "row", style: "margin-top:12px" },
      r.accepted ? el("a", { class: "btn primary", href: "#generate", style: "text-decoration:none; display:inline-flex", onclick: () => { loadViews(true).catch(failToast); } }, "Review the " + r.accepted + " accepted test(s)") : null));
  clear(I.result).append(card);
}

async function doCompare() {
  if (!I.sel.value) { toast("Import a file first.", "error"); return; }
  clear(I.cmp).append(el("div", { class: "card" }, loadingBox("Computing coverage..."), skeleton(3)));
  try {
    const r = await api("/import/" + I.sel.value + "/compare", { generated_run_id: I.gsel.value ? Number(I.gsel.value) : null });
    renderCompare(r);
  } catch (e) { clear(I.cmp); throw e; }
}

function renderCompare(r) {
  const c = r.comparison, card = el("div", { class: "card" });
  const dl = el("button", { class: "btn", onclick: () => download("import_coverage_" + r.import_run_id + ".md", r.markdown, "text/markdown") }, "Download comparison report (Markdown)");
  const lists = (title, obj, empty) => {
    const rows = CMP_KINDS.filter(([k]) => obj[k].length);
    return el("div", { class: "sect" }, el("h3", {}, title),
      rows.length ? el("ul", { class: "bul" }, rows.map(([k, lab]) => el("li", {}, el("b", {}, lab + " (" + obj[k].length + "): "), obj[k].join("; ")))) : el("div", { class: "kv" }, empty));
  };
  card.append(el("h2", {}, "Imported baseline vs " + r.generated_source),
    el("p", { class: "hint" }, c.tests.imported + " imported tests, " + c.tests.generated + " generated tests, " + c.tests.combined + " combined. Items touched / items in the spec."),
    el("div", { class: "tbl-wrap" }, el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Kind"), el("th", { class: "num" }, "Imported (baseline)"), el("th", { class: "num" }, "Generated"), el("th", { class: "num" }, "Combined"), el("th", { class: "num" }, "Newly covered"))),
      el("tbody", {}, CMP_KINDS.map(([k, lab]) => { const s = c.summary[k]; return el("tr", {}, el("td", {}, lab), el("td", { class: "num" }, s.imported + "/" + s.items), el("td", { class: "num" }, s.generated + "/" + s.items), el("td", { class: "num" }, s.combined + "/" + s.items), el("td", { class: "num" }, c.newly_covered[k].length)); })))),
    lists("Newly covered (no imported test, at least one generated test)", c.newly_covered, "Nothing: the imported suite already covers everything the generated tests cover."),
    lists("Covered only by imported tests", c.imported_only, "None."),
    lists("Still uncovered by the combined suite", c.still_uncovered, "None."),
    el("div", { class: "sect" }, dl));
  clear(I.cmp).append(card);
}

/* ---------- routing & boot ---------- */
const TABS = ["ask", "generate", "import", "run"];
function route() {
  const name = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "ask";
  document.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== name));
  document.querySelectorAll("nav.tabs a").forEach((a) => { if (a.dataset.tab === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  if (!S.examples) return;
  if (name === "run") refreshRun();
  if (name === "import") refreshImport();
  if (name === "generate" && S.runId !== null && !S.views.length) loadViews();
}

async function boot() {
  window.addEventListener("hashchange", route);
  document.querySelectorAll("#tab-ask,#tab-generate,#tab-import,#tab-run").forEach((p) => p.append(skeleton(4)));
  try {
    [S.config, S.examples] = await Promise.all([api("/config"), api("/examples")]);
  } catch (e) {
    $("#banner-text").textContent = "Could not load configuration.";
    document.querySelectorAll("[data-panel]").forEach((p) => clear(p).append(note("err", e.message)));
    failToast(e); return;
  }
  renderHeader(); buildAsk(); buildGenerate(); buildImport();
  route();
  setInterval(async () => { try { S.config = await api("/config"); renderHeader(); } catch { /* server may be restarting */ } }, 30000);
}
boot();
