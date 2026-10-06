const pptxgen = require("pptxgenjs");
const fs = require("fs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require("C:/Users/pasar/.claude/skills/synced/22367840-ff91-4821-9fde-cd891494bef7_c7866da3-7640-485c-a28e-2ea7e52d24fe/pptx/scripts/apply_theme.js");

const R = JSON.parse(fs.readFileSync("C:/Users/pasar/Desktop/tata_tech/outputs/eval_report.json", "utf8"));
const pct = (x) => Math.round(x * 100) + "%";
const OUT = "C:/Users/pasar/Desktop/ppt_build/UDS_Assistant_Deck.pptx";

const THEME = {
  name: "UDS Minimal", headFontFace: "Calibri", bodyFontFace: "Calibri",
  colors: { dk1: "1B2430", lt1: "FFFFFF", dk2: "5B6673", lt2: "F2F5F7", accent1: "0E7C86", accent2: "1B2430",
    accent3: "9AA5B1", accent4: "C2410C", accent5: "0E7C86", accent6: "5B6673", hlink: "0E7C86", folHlink: "5B6673" },
};

async function icon(name, color = "#FFFFFF") {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(fa[name], { color, size: 256 }));
  const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  pres.title = "UDS Diagnostics and Automated Test Generation Assistant";
  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "TITLE_ONLY", background: { color: "FFFFFF" },
    slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: "9AA5B1", align: "right" },
    objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.8, y: 0.55, w: 11.7, h: 0.9, fontSize: 36, bold: true, color: C.text1, margin: 0, valign: "top", align: "left" }, text: "" } }],
  });
  pres.defineSlideMaster({ title: "COVER", background: { color: "FFFFFF" } });

  const foot = (s, t) => s.addText(t, { x: 0.8, y: 6.95, w: 10.8, h: 0.3, fontSize: 10, color: C.text2, margin: 0, isTextBox: true, objectName: "Footnote" });
  const content = (title, section) => { const s = pres.addSlide({ masterName: "TITLE_ONLY", sectionTitle: section }); s.addText(title, { placeholder: "title" }); return s; };

  // card: tinted background, icon in a teal circle, bold head, body text
  async function card(s, { x, y, w, h, ic, head, body, n }) {
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.12, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: "Card " + n });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.3, y: y + 0.3, w: 0.62, h: 0.62, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "Icon circle " + n });
    s.addImage({ data: await icon(ic), x: x + 0.46, y: y + 0.46, w: 0.3, h: 0.3, objectName: "Icon " + n, altText: head });
    s.addText(head, { x: x + 0.3, y: y + 1.05, w: w - 0.6, h: 0.45, fontSize: 20, bold: true, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: "Card head " + n });
    s.addText(body, { x: x + 0.3, y: y + 1.55, w: w - 0.6, h: h - 1.7, fontSize: 15, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: "Card body " + n });
  }

  // 1 Title -------------------------------------------------------------------
  pres.addSection({ title: "Opening" });
  let s = pres.addSlide({ masterName: "COVER", sectionTitle: "Opening" });
  s.addShape(pres.ShapeType.ellipse, { x: 0.8, y: 2.25, w: 0.28, h: 0.28, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "Motif dot" });
  s.addText("UDS Diagnostics and Automated Test Generation Assistant", { x: 0.8, y: 2.7, w: 11.2, h: 1.7, fontSize: 44, bold: true, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: "Title" });
  s.addText("Cited diagnostic answers, validated requests and test cases for ECU testing, running fully on a local machine", { x: 0.8, y: 4.5, w: 10.4, h: 0.9, fontSize: 20, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: "Subtitle" });
  s.addText("Case Study 5  |  Automotive Engineering AI", { x: 0.8, y: 6.5, w: 8, h: 0.35, fontSize: 14, color: C.text2, margin: 0, isTextBox: true, objectName: "Meta" });
  s.addNotes("Case Study 5 from the Automotive Engineering AI case study document: a local assistant that helps test engineers interpret diagnostic specifications, construct valid requests, generate test cases and validate expected ECU responses.");

  // 2 Problem statement ---------------------------------------------------------
  pres.addSection({ title: "Context" });
  s = content("Problem statement", "Context");
  s.addText("Hand-writing UDS diagnostic tests is slow, inconsistent and thin on negative cases.", { x: 0.8, y: 1.9, w: 5.2, h: 2.8, fontSize: 30, bold: true, color: C.accent1, margin: 0, valign: "top", isTextBox: true, objectName: "Statement" });
  [["Interpret", "ISO 14229 together with OEM-specific and ECU-specific behaviour."],
   ["Construct", "Request bytes by hand, and work out the session and security prerequisites."],
   ["Predict", "Positive and negative responses, then translate the intent into automation scripts."]].forEach(([h, t], i) => {
    const y = 1.9 + i * 1.45;
    s.addShape(pres.ShapeType.ellipse, { x: 6.9, y: y + 0.02, w: 0.5, h: 0.5, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "Step chip " + (i + 1) });
    s.addText(String(i + 1), { x: 6.9, y: y + 0.02, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "Step number " + (i + 1) });
    s.addText(h, { x: 7.65, y, w: 4.9, h: 0.4, fontSize: 20, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: "Step head " + (i + 1) });
    s.addText(t, { x: 7.65, y: y + 0.42, w: 4.9, h: 0.8, fontSize: 16, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: "Step text " + (i + 1) });
  });
  foot(s, "Source: Case Study 5, section 1. More services, subfunctions, identifiers and variants mean more inconsistency and error risk.");
  s.addNotes("The business problem as the case study states it: engineers interpret ISO 14229 with OEM and ECU specifics, build request bytes by hand, work out session and security prerequisites, predict positive and negative responses and then script them.");

  // 3 Objective ---------------------------------------------------------------
  s = content("Objective", "Context");
  const objs = [
    ["FaClock", "Less interpretation effort", "Spend less time reading the diagnostic specification by hand."],
    ["FaBalanceScale", "Consistent test scenarios", "Positive and negative cases generated the same way every time."],
    ["FaCheckCircle", "Validated structures", "Check requests and expected responses against the rules, not by eye."],
    ["FaBolt", "Requirements to tests, faster", "Turn a plain-English requirement into an executable test template."],
  ];
  for (let i = 0; i < objs.length; i++) {
    const [ic, head, body] = objs[i];
    await card(s, { x: 0.8 + (i % 2) * 5.95, y: 1.75 + Math.floor(i / 2) * 2.45, w: 5.75, h: 2.25, ic, head, body, n: "obj" + (i + 1) });
  }
  foot(s, "Source: Case Study 5, section 2 (Project Objective).");
  s.addNotes("The four objectives of Case Study 5, in our wording. Each maps to a part of the system: Ask and the request checker (interpretation and validation), the template-based generator (consistency and speed).");

  // 4 Scope -------------------------------------------------------------------
  s = content("Scope", "Context");
  s.addImage({ path: "C:/Users/pasar/Desktop/ppt_build/scope_crop.png", x: 0.8, y: 1.8, w: 11.7, h: 11.7 * 288 / 1132, objectName: "Scope table from the case study", altText: "In scope and out of scope table from Case Study 5" });
  s.addText("Our boundary follows it: a synthetic ECU simulator only, human review before any run, no production vehicle.", { x: 0.8, y: 5.3, w: 11.7, h: 0.6, fontSize: 18, color: C.text1, margin: 0, isTextBox: true, objectName: "Takeaway" });
  foot(s, "Source: Case Study 5, section 3 (Scope).");
  s.addNotes("The scope table is copied from the case study. We stay inside it: nothing runs on a production vehicle, all knowledge is own-words or synthetic, and ECU behaviour is never accepted automatically without review.");

  // 5 Methodology -------------------------------------------------------------
  pres.addSection({ title: "Method" });
  s = content("Methodology", "Method");
  const cols = [
    ["FaBrain", "Language model", "Words only.\nParses the requirement.\nPicks approved templates.\nWrites the explanation."],
    ["FaCogs", "Rules engine", "Every byte.\nBuilds each request and response.\nOne cited order of negative responses.\nChecked against an independent simulator."],
    ["FaUserCheck", "Engineer", "Final say.\nReview gate before any run.\nApproved tests only by default.\nEvery decision in an audit trail."],
  ];
  for (let i = 0; i < cols.length; i++) {
    const [ic, head, body] = cols[i];
    await card(s, { x: 0.8 + i * 3.95, y: 1.75, w: 3.75, h: 3.55, ic, head, body, n: "m" + (i + 1) });
  }
  s.addShape(pres.ShapeType.ellipse, { x: 0.8, y: 5.72, w: 0.46, h: 0.46, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "Local icon circle" });
  s.addImage({ data: await icon("FaServer"), x: 0.93, y: 5.85, w: 0.2, h: 0.2, objectName: "Local icon", altText: "Local" });
  s.addText("Runs locally: Ollama (qwen2.5 3B) on the GPU, ChromaDB with BGE embeddings, FastAPI. Answers and tests carry citations.", { x: 1.5, y: 5.65, w: 11, h: 0.6, fontSize: 16, color: C.text1, margin: 0, valign: "middle", isTextBox: true, objectName: "Local line" });
  s.addNotes("The design principle: the language model handles language only, code handles correctness. That is why a small local 3B model is enough. The next slide shows the pipeline step by step.");

  // 6 Pipeline diagram --------------------------------------------------------
  s = content("Pipeline", "Method");
  const dw = 11.3, dh = dw * 1400 / 3180;
  s.addImage({ path: "C:/Users/pasar/Desktop/ppt_build/pipeline_crop.png", x: (13.333 - dw) / 2, y: 1.55, w: dw, h: dh, objectName: "Pipeline diagram", altText: "Pipeline from requirement through parse, retrieve, plan, instantiate, validate, explain, review, run and export" });
  s.addNotes("Walk through left to right: requirement, parse (language model), retrieve evidence from four local collections, plan (language model picks templates), instantiate (templates and the rules engine build every byte), validate, explain (prose only), engineer review, run on the simulator with an optional injected bug, then export pytest and CAPL, a coverage report and an audit trail.");

  // 7 Limitations -------------------------------------------------------------
  pres.addSection({ title: "Evidence" });
  s = content("Limitations", "Evidence");
  const lims = [
    ["FaFlask", "Synthetic data", "A fictional body control module and OEM guideline. No real ECU, CANoe or vehicle."],
    ["FaFileAlt", "No document ingestion", "The spec is hand-structured YAML. PDF, ODX and CDD files are not read."],
    ["FaUsers", "One author, one contract", "Rules engine, simulator and gold tests share a source, so agreement is not independent proof."],
    ["FaChartBar", "Small blind samples", "15 bugs, 25 questions, 16 requirements. One case moves a score by several points."],
    ["FaRobot", "Small model variance", "Which tests get planned varies between runs. Requirement parsing F1 is " + pct(R.understanding.target_f1) + "."],
    ["FaStopwatch", "Not yet measured", "Manual test-design time baseline. CAPL export never run in CANoe."],
  ];
  for (let i = 0; i < lims.length; i++) {
    const [ic, head, body] = lims[i];
    await card(s, { x: 0.8 + (i % 3) * 3.95, y: 1.7 + Math.floor(i / 3) * 2.6, w: 3.75, h: 2.4, ic, head, body, n: "lim" + (i + 1) });
  }
  s.addNotes("Be upfront: the numbers that follow are measured on synthetic data in one run with a small local model. Validity and clean-pass are high by construction because the rules engine builds the bytes; the independent evidence is the blind sets.");

  // 8 Results: tests generated ------------------------------------------------
  s = content("Results: tests generated", "Evidence");
  const g = R.generation_accuracy, cov = R.coverage, sc = R.spec_coverage;
  const sum = (k) => Object.values(sc[k].kinds).reduce((a, v) => [a[0] + v.touched, a[1] + v.items], [0, 0]);
  const gen = sum("generated"), swp = sum("sweep");
  [[String(g.tests), "tests generated from " + cov.requirements + " requirements"],
   [pct(g.valid_request_rate), "valid requests (" + g.well_formed_steps + "/" + g.send_steps + ")"],
   [pct(g.clean_pass_rate), "pass on the clean simulator (" + g.clean_pass + "/" + g.tests + ")"],
   [g.citations_valid + "/" + g.citations, "citations resolve to a real source"]].forEach(([n, l], i) => {
    const x = 0.8 + i * 2.95;
    s.addText(n, { x, y: 1.9, w: 2.7, h: 1.0, fontSize: 48, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "Stat " + (i + 1) });
    s.addText(l, { x, y: 2.95, w: 2.6, h: 0.9, fontSize: 16, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: "Stat label " + (i + 1) });
  });
  s.addText([{ text: "Test types: ", options: { bold: true } }, { text: Object.entries(cov.category_totals).map(([k, v]) => k + " " + v).join("  |  "), options: {} }], { x: 0.8, y: 4.4, w: 11.7, h: 0.5, fontSize: 18, color: C.text1, margin: 0, isTextBox: true, objectName: "Category line" });
  s.addText([{ text: "Spec items covered: ", options: { bold: true } }, { text: gen[0] + " of " + gen[1] + " by the generated tests, " + swp[0] + " of " + swp[1] + " by the " + R.defect_detection.sweep_tests_count + "-test conformance sweep.", options: {} }], { x: 0.8, y: 5.0, w: 11.7, h: 0.5, fontSize: 18, color: C.text1, margin: 0, isTextBox: true, objectName: "Coverage line" });
  s.addText([{ text: "Reuse: ", options: { bold: true } }, { text: R.reuse.from_templates + " of " + R.reuse.tests + " tests built from " + R.reuse.templates_registered + " approved templates; the language model never writes a byte.", options: {} }], { x: 0.8, y: 5.6, w: 11.7, h: 0.5, fontSize: 18, color: C.text1, margin: 0, isTextBox: true, objectName: "Reuse line" });
  foot(s, "Synthetic Body Control Module spec; one run on a local 3B model (git " + R.git + "). Validity and clean-pass are high by construction, because the rules engine builds the bytes.");
  s.addNotes("These come from the evaluation report of one run. The independent evidence is on the next slide: bugs injected into a simulator and caught or missed by the tests, and blind questions and requirements written without seeing the templates.");

  // 9 Results: defects, questions ---------------------------------------------
  s = content("Results: defects, questions and understanding", "Evidence");
  const d = R.defect_detection;
  s.addText("Blind bugs caught (of " + d.bugs + ")", { x: 0.8, y: 1.7, w: 6, h: 0.4, fontSize: 18, bold: true, color: C.text1, margin: 0, isTextBox: true, objectName: "Chart title" });
  s.addChart(pres.charts.BAR, [{ name: "Bugs caught", labels: ["Generated tests (" + d.generated_tests_count + ")", "Conformance sweep (" + d.sweep_tests_count + ")", "Both together"], values: [d.generated_tests.detected, d.sweep.detected, d.caught] }], {
    x: 0.7, y: 2.15, w: 6.3, h: 4.4, barDir: "bar", chartColors: ["0E7C86"], barGapWidthPct: 60,
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: "1B2430", dataLabelFontSize: 14, dataLabelFontFace: "+mn-lt",
    valAxisMaxVal: d.bugs, valAxisMinVal: 0, valAxisMajorUnit: 5, valAxisLabelColor: "5B6673", valAxisLabelFontSize: 12, valAxisLabelFontFace: "+mn-lt",
    catAxisLabelColor: "1B2430", catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
    valGridLine: { color: "E2E8EC", size: 0.75 }, catGridLine: { style: "none" }, showLegend: false });
  const q = R.qa, u = R.understanding;
  [[q.answer_accuracy_n + "/" + q.n_answerable, "questions answered correctly (" + pct(q.answer_accuracy) + "), with correct citations"],
   [q.correct_not_found_n + "/" + q.n_unanswerable, "unanswerable questions correctly refused"],
   [pct(u.target_f1), "F1 identifying the services, DIDs and routines in " + u.requirements + " plain-English requirements"]].forEach(([n, l], i) => {
    const y = 1.75 + i * 1.6;
    s.addText(n, { x: 7.6, y, w: 4.9, h: 0.8, fontSize: 40, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "Right stat " + (i + 1) });
    s.addText(l, { x: 7.6, y: y + 0.8, w: 4.9, h: 0.7, fontSize: 16, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: "Right label " + (i + 1) });
  });
  foot(s, "Blind sets written without seeing the templates: 15 bugs, 25 questions, 16 requirements. Tool time is about " + Math.round(R.test_design_time.tool_seconds_per_requirement_mean) + " s per requirement; the manual baseline is not yet measured.");
  s.addNotes("Figures from the run of 2026-10-05 (re-read them from the current outputs/eval_report.json before presenting): the sweep is a requirement-independent conformance suite of 1200 tests; together with the generated tests it caught 9 of 15 blind bugs, so six remained missed. Question answering: 19 of 21 correct with citations, 3 of 4 unanswerable questions refused. Requirement understanding was the weakest result.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("written");
})();
