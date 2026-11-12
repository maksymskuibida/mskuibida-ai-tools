/* Drive the pages dev/preview.py wrote (the real templates with their rows) under jsdom and report what the batch-4 visuals do.

     node drive_batch4.js <scenario> <page.html> [<localStorage json>]      prints one JSON object

   scenarios: gate (a per-stage page: criteria dots, diagram switch, outline, inline diagrams, timeline, the read keys),
              heat (Build and Test: the heat grid and its filter), unit (a Unit page: funnel, lanes, timeline) */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const optional = (name) => { try { return require(name); } catch { return null; } };
const [scenario, file, storage] = process.argv.slice(2);

function boot(pre) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String((e && e.message) || e)));
  vc.on("error", (...a) => errors.push(a.map(String).join(" ")));
  const html = fs.readFileSync(file, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, url: "https://claude.ai/artifact/x", virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
      w.scrollTo = () => {};
      w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
      w.Element.prototype.scrollIntoView = function () {};
      const marked = optional("marked"), purify = optional("dompurify"), yaml = optional("js-yaml");
      if (marked && purify) { w.marked = marked.marked || marked; w.DOMPurify = (purify.default || purify)(w); }
      if (yaml) w.jsyaml = yaml;
      try { Object.entries(JSON.parse(pre || "{}")).forEach(([k, v]) => w.localStorage.setItem(k, v)); } catch (e) { /* none */ }
    },
  });
  return { w: dom.window, errors };
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const reads = (d) => [...d.querySelectorAll("[data-read], [data-iread]")].map((n) => n.dataset.read || n.dataset.iread).sort();
const click = (w, n) => n.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));

async function gate() {
  const { w, errors } = boot(storage);
  await wait(500);
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  const out = { errors };
  const crit = all("#b-eval details.crow");
  out.criteria = crit.length;
  out.dots = all(".vz-dots .vz-dot").map((n) => ({ cls: n.className, label: n.getAttribute("aria-label") }));
  out.dotsLabel = ($(".vz-dots") || { getAttribute: () => "" }).getAttribute("aria-label");
  if (out.dots.length) { const dot = $(".vz-dots .vz-dot"); const key = dot.dataset.vzGo; click(w, dot); out.dotOpened = !!($("#crit-" + key) || {}).open; }
  // the diagram switch on every document that offers one
  const dbtn = all("[data-mode=diagram]").filter((b) => !b.hidden);
  out.diagramDocs = dbtn.map((b) => b.dataset.key);
  out.hiddenDiagramButtons = all("[data-mode=diagram]").filter((b) => b.hidden).length;
  out.mermaidSourceShown = all(".diagram pre.src").length;
  out.inlineFlows = all(".diagram .vz-flow").length;
  out.readsBefore = reads(d);
  const key = out.diagramDocs.find((k) => /traceab/.test(k)) || out.diagramDocs[0];
  if (key) {
    $("#b-records").open = true;
    click(w, $(`#seg-${key} [data-mode=diagram]`));
    await wait(80);
    $("#b-records").open = true;
    const body = $("#db-" + key);
    out.diagramKey = key;
    out.figure = !!body.querySelector(".vz");
    out.figureLabel = (body.querySelector(".vz") || { getAttribute: () => "" }).getAttribute("aria-label");
    out.altItems = body.querySelectorAll("ul.vz-sr li").length;
    out.noReadKeysInside = !body.querySelector("[data-read], [data-iread], [data-item]");
    out.readsAfter = reads(d);
    out.saved = w.localStorage.getItem("approval-gates:viz:" + key);
    out.newNodes = body.querySelectorAll(".vz-new").length;
    out.goneNote = (body.querySelector(".vz-gone") || {}).textContent || "";
    out.textPressed = $(`#seg-${key} [data-mode=text]`).getAttribute("aria-pressed");
    const node = body.querySelector("[data-vz-go]:not([data-vz-go=''])");
    if (node) { click(w, node); await wait(80); out.afterNode = { mode: $(`#seg-${key} [data-mode=diagram]`).getAttribute("aria-pressed"), toast: ($("#toast") || {}).textContent, flash: all(".flash").length }; }
  }
  // the outline of a long file
  const fo = all(".fo-side");
  out.outlines = fo.length;
  if (fo.length) { const b = fo[0].querySelector("[data-vz-jump]"); const target = d.getElementById(b.dataset.vzJump); click(w, b); out.outlineTarget = !!target; out.outlineStrip = all(".fo-strip").length; }
  // the round timeline: it replaces the legend chips and keeps their behaviour
  const tl = $(".vz-tl");
  if (tl) {
    out.timeline = [...tl.querySelectorAll("li")].map((li) => ({ text: li.textContent.replace(/\s+/g, " ").trim(), only: li.querySelector("[data-rvonly]") ? li.querySelector("[data-rvonly]").dataset.rvonly : null }));
    const chips = all(".vz-tl [data-rvonly]");
    out.legendChips = all(".rv-legend .rv-chip").length;
    if (chips.length) {
      click(w, chips[0]); out.pressedAfter = all(".vz-tl [data-rvonly]").map((c) => c.getAttribute("aria-pressed"));
      click(w, chips[0]); out.pressedAgain = all(".vz-tl [data-rvonly]").map((c) => c.getAttribute("aria-pressed"));
      if (chips.length > 1) { click(w, chips[1]); out.pressedOther = all(".vz-tl [data-rvonly]").map((c) => c.getAttribute("aria-pressed")); }
    }
  }
  out.errors = errors;
  return out;
}

async function heat() {
  const { w, errors } = boot(storage);
  await wait(500);
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  const out = { errors, heat: !!$(".vz-heat"), label: ($(".vz-heat") || { getAttribute: () => "" }).getAttribute("aria-label") };
  out.rowsAll = all("#bt-tm .tm-row").length;
  out.readsBefore = reads(d);
  const cell = all(".vz-cell").find((c) => +c.textContent >= 2);
  if (cell) {
    const n = +cell.textContent; click(w, cell); await wait(50);
    out.cell = { n, rows: all("#bt-tm .tm-row").length, pressed: ($(".vz-cell[aria-pressed=true]") || {}).textContent, clear: !!$(".vz-clear") };
    click(w, $(".vz-clear")); await wait(50);
    out.rowsCleared = all("#bt-tm .tm-row").length;
  }
  const col = $(".vz-hcol");
  if (col) { click(w, col); await wait(50); out.col = { name: col.textContent, rows: all("#bt-tm .tm-row").length, units: all("#bt-tm .tm-id .mono").every((m) => true) }; }
  out.readsAfter = reads(d);
  out.noReadKeysInside = !$(".vz-heat [data-read], .vz-heat [data-item]");
  out.errors = errors;
  return out;
}

async function unit() {
  const { w, errors } = boot(storage);
  await wait(600);
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  const out = { errors };
  const f = $(".vz-funnel");
  out.funnel = f ? { label: f.getAttribute("aria-label"), segs: all(".vz-seg").map((s) => ({ cls: s.className.replace("vz-seg ", ""), text: s.textContent.replace(/\s+/g, " ").trim(), tag: s.tagName })) } : null;
  if (f) {
    out.rowsAll = all("#verification .row").length;
    const failed = $(".vz-seg.failed");
    if (failed) {
      click(w, failed); await wait(50);
      out.failed = { rows: all("#verification .row").length, chip: ($(".vchip[data-val=failed]") || { getAttribute: () => "" }).getAttribute("aria-pressed"), seg: ($(".vz-seg.failed") || { getAttribute: () => "" }).getAttribute("aria-pressed") };
      click(w, $(".vz-seg.failed")); await wait(50);
      out.cleared = { rows: all("#verification .row").length };
      click(w, $(".vz-seg.verified")); await wait(50);
      out.verified = { rows: all("#verification .row").length, chips: all(".vchip[aria-pressed=true]").map((c) => c.dataset.val) };
    }
  }
  const lanes = $(".vz-lanes");
  out.lanes = lanes ? { label: lanes.getAttribute("aria-label"), names: all(".vz-lanes .vz-lname").map((n) => n.firstChild.textContent), steps: all(".vz-lstep").length, rowSteps: all("#plan .row[id^=step-]").length } : null;
  if (lanes) { const s = $(".vz-lstep"); const key = s.dataset.vzGo; click(w, s); await wait(50); out.laneJump = { key, open: !!$("#" + key) }; }
  const tl = $(".vz-tl");
  out.timeline = tl ? [...tl.querySelectorAll("li")].map((li) => li.textContent.replace(/\s+/g, " ").trim()) : null;
  if (tl) { const chip = $(".vz-tl [data-rvonly]"); if (chip) { click(w, chip); out.pressed = all(".vz-tl [data-rvonly]").map((c) => c.getAttribute("aria-pressed")); click(w, $(".vz-tl [data-rvonly]")); out.pressedAgain = all(".vz-tl [data-rvonly]").map((c) => c.getAttribute("aria-pressed")); } }
  out.errors = errors;
  return out;
}

({ gate, heat, unit })[scenario]().then((o) => { process.stdout.write(JSON.stringify(o)); process.exit(0); });
