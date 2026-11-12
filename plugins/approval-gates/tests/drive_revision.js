/* Drive the pages' revision diff under jsdom and print a JSON report of what they show.

     node drive_revision.js gate <approval-gate.html> <sample.json> <scenario>
     node drive_revision.js unit <unit-gate.html> <sample.json>

   gate: sample.json is {id, row, documents, others: [{id, row, documents}]}, what gate_page_env.js serves; the page
   compares the gate with the newest of `others`. Scenarios: page (what the page marks and lists), interact (Clean,
   next / previous, the Changed filter, the base picker, a place the agent named), reads (the read mark of an element).
   unit: sample.json is {id, row, others: [{id, row}]}, rows of the bundles collection. */
const fs = require("fs");
const { JSDOM } = require("jsdom");
const { boot } = require("./gate_page_env");
const [kind, pagePath, samplePath, scenario] = process.argv.slice(2);
const sample = JSON.parse(fs.readFileSync(samplePath, "utf8"));
/* The viewer's stored view: RV_PREF=show (the default here, the Changes view the older tests read) or "none" for a reader
   who never chose, which is the Clean view with each round's colour. */
const PREF = process.env.RV_PREF || "show";
const seed = (w) => { if (PREF !== "none") w.localStorage.setItem("aidlc-rev:view", PREF); };
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");

function gate() {
  const t0 = Date.now();
  const { w } = boot(pagePath, sample, seed);
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  const shown = (n) => !!n && !n.hidden && !n.closest("[hidden]");
  const filter = (name) => all("#bar .fpill").find((b) => b.firstChild.textContent === name).click();
  /* what the Clean view tinted: [round, text] per <ins class="rv-r">, the blocks that carry a round's edge, the legend */
  const colours = () => ({
    ins: all("ins.rv-r").map((n) => [+(n.className.match(/rv-r(\d+)/) || [])[1], n.textContent]),
    blocks: all(".rv-rb").map((n) => [+(n.className.match(/rv-r(\d+)/) || [])[1], n.id || n.dataset.ekey || n.className]),
    legend: all(".rv-chip").map((b) => b.dataset.rvonly + ":" + b.getAttribute("aria-pressed")),
    changesMarks: all("ins.rv-ins, del.rv-del").filter((n) => !n.closest(".rv-gone, .rv-removed")).length,  /* a ghost keeps its struck text, hidden in Clean */
  });
  const page = () => ({
    blocks: all("#col > details.block").map((b) => b.id),
    chips: all("#bar .jchip").map(text),
    groups: all("#rv-list li.rvg").map((li) => text(li)),
    entries: all("#rv-list li.rvsub li").map((li) => text(li)),
    total: text($("#rv-total")),
    ins: all("ins.rv-ins").map((n) => n.textContent),
    del: all("del.rv-del").map((n) => n.textContent),
    gone: all(".rv-gone").map(text),
    removed: all(".rv-removed").map(text),
    newParts: all(".rv-new").map((n) => n.id || n.dataset.ekey || n.className),
    changedSecs: all("details.sec.rv-chg").map((n) => n.dataset.title),
    newSecs: all("details.sec.rv-new").map((n) => n.dataset.title),
    goneSecs: all("details.sec.rv-removed").map((n) => n.dataset.title),
    sameSecs: all("details.sec.rv-same").map((n) => ({ title: n.dataset.title, open: n.open })),
    changedElems: all("[data-ekey].rv-chg").map((n) => n.dataset.ekey),
    newElems: all("[data-ekey].rv-new").map((n) => n.dataset.ekey),
    items: all(".irow[data-item].rv-chg, .irow[data-item].rv-new").map((n) => n.dataset.aidlcId + ":" + (n.classList.contains("rv-new") ? "new" : "changed")),
    itemsGone: all(".rvgone .irow").map(text),
    evalTags: all("#b-eval .rv-tags").map(text),
    done: all("#b-revision ol.rvdone > li").map((li) => ({ what: text(li.querySelector(".what")), where: [...li.querySelectorAll("[data-rvgo]")].map(text) })),
    feedback: text($("#b-revision .rvfb")),
    picker: all("#b-revision select[data-rvbase] option").map(text),
    rv: $("#col").dataset.rv,
    colours: colours(),
    pos: text($("#rvpos")),
    ms: Date.now() - t0,
  });
  const scenarios = {
    page,
    interact() {
      const r = {};
      r.before = { pos: text($("#rvpos")), marks: all("ins.rv-ins, del.rv-del").length };
      $("[data-rvstep='1']").click(); $("[data-rvstep='1']").click();
      r.next = text($("#rvpos"));
      $("[data-rvstep='-1']").click();
      r.prev = text($("#rvpos"));
      w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "j", bubbles: true }));
      r.key = text($("#rvpos"));
      filter("Changed");
      r.changed = { items: all("#b-items .irow[data-item]").filter(shown).length, of: all("#b-items .irow[data-item]").length,
        blocks: all("#col > details.block").filter(shown).map((b) => b.id) };
      filter("All");
      $("[data-rvview='clean']").click();
      r.clean = { rv: $("#col").dataset.rv, pref: w.localStorage.getItem("aidlc-rev:view"), pos: !!$("#rvpos"), marks: all("ins.rv-ins, del.rv-del").length,
        sameFolded: all("details.sec.rv-same").filter((s) => !s.open).length };
      $("[data-rvview='show']").click();
      r.show = { rv: $("#col").dataset.rv, pref: w.localStorage.getItem("aidlc-rev:view") };
      const go = $("#b-revision ol.rvdone [data-rvgo]");
      if (go) { const where = go.dataset.rvgo; go.click(); r.went = where; const sec = all("details.sec").find((s) => s.classList.contains("rv-flash")) || $(".rv-flash"); r.landed = sec ? (sec.dataset.title || sec.id || sec.className) : ""; r.landedOpen = sec ? !sec.closest("details:not([open])") : false; }
      const link = all("#rv-list li.rvsub [data-rvgo]").find((b) => b.dataset.rvgo.startsWith("i:"));
      if (link) { link.click(); const key = link.dataset.rvgo.slice(2); const row = d.getElementById("item-" + key); r.itemOpened = !!(row && row.querySelector(".ib")); r.itemMarks = row ? row.querySelectorAll("ins.rv-ins, del.rv-del").length : 0; }
      return r;
    },
    html() { return { html: $("#col").innerHTML.replace(/ data-rv="[a-z]+"/g, ""), rv: $("#col").dataset.rv, ins: all("ins").length, legend: all(".rv-chip").length, edges: all(".rv-rb").length }; },
    colours() {
      const r = { colours: colours() };
      const chip = all(".rv-chip")[0];
      if (chip) { chip.click(); r.pressed = all(".rv-chip").map((b) => b.getAttribute("aria-pressed")); r.dimmed = all("ins.rv-r.rv-dim").map((n) => +(n.className.match(/rv-r(\d+)/) || [])[1]); chip.click(); r.undimmed = all(".rv-dim").length; }
      $("[data-rvview='show']").click();
      r.show = { rv: $("#col").dataset.rv, pref: w.localStorage.getItem("aidlc-rev:view"), marks: all("ins.rv-ins").length, tinted: all("ins.rv-r").length, legend: all(".rv-chip").length };
      return r;
    },
    reads() {
      const dot = $(sample.dotSelector || "#d-requirements [data-eread]");
      if (!dot) return { error: "no element dot" };
      const key = dot.dataset.eread; dot.click();
      const marks = JSON.parse(w.localStorage.getItem([...Array(w.localStorage.length).keys()].map((i) => w.localStorage.key(i)).find((k) => k.startsWith("approval-gates:reads:"))) || "{}");
      return { key, mark: marks[key] };
    },
  };
  return new Promise((done) => setTimeout(() => {
    let out; try { out = scenarios[scenario](); } catch (e) { out = { error: String(e && e.stack || e) }; }
    done(out);
  }, 900));
}

function unit() {
  const html = fs.readFileSync(pagePath, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
  const dom = new JSDOM("<!doctype html><html><head></head><body>" + html + "</body></html>", { runScripts: "outside-only", pretendToBeVisual: true, url: "https://claude.ai/artifact/x#" + sample.id });
  const w = dom.window;
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = function () {};
  w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
  const rows = [[sample.id, sample.row]].concat((sample.others || []).map((o) => [o.id, o.row]));
  const snap = (id, data) => ({ id, exists: data !== undefined, data: () => data });
  const q = { orderBy: () => q, limit: () => q, where: () => q, get: async () => ({ docs: rows.map(([i, r]) => snap(i, r)) }),
    onSnapshot: (cb) => { setTimeout(() => cb({ docs: rows.map(([i, r]) => snap(i, r)) })); return () => {}; },
    doc: () => ({ get: async () => snap("x", undefined), set: async () => {} }) };
  const db = { collection: () => q, doc: () => ({ onSnapshot: (cb) => { setTimeout(() => cb(snap(sample.id, sample.row))); return () => {}; }, update: async () => {} }) };
  w.claude = { use: async (what) => (what === "db" ? db : { id: async () => "viewer" }) };
  seed(w);
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) w.eval(m[1]);
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  return new Promise((done) => setTimeout(() => {
    const r = {};
    try {
      r.colours = { ins: all("ins.rv-r").map((n) => [+(n.className.match(/rv-r(\d+)/) || [])[1], n.textContent]), blocks: all(".rv-rb").map((n) => [+(n.className.match(/rv-r(\d+)/) || [])[1], n.id]),
        legend: all(".rv-chip").map((b) => b.dataset.rvonly + ":" + text(b)), marks: all("ins.rv-ins, del.rv-del").length, rv: $("#app").dataset.rv, strip: text($("#rvstrip h2")) };
      if (PREF === "none") { const c = all(".rv-chip")[0]; if (!c) return done(r); c.click(); r.dim = all(".rv-dim").map((n) => n.className); r.pressed = all(".rv-chip").map((b) => b.getAttribute("aria-pressed")); return done(r); }
      r.strip = text($("#rvstrip h2")); r.hint = text($("#rvstrip .hint"));
      r.list = all("#rvstrip ul.rvlist li").map(text);
      r.rows = all(".row.rv-chg, .row.rv-new").map((n) => n.id + ":" + (n.classList.contains("rv-new") ? "new" : "changed"));
      r.ins = all("ins.rv-ins").map((n) => n.textContent); r.del = all("del.rv-del").map((n) => n.textContent);
      r.picker = all("#rvstrip select option").map(text);
      r.filters = all("#bar .pill").map(text);
      all("#bar .pill").find((b) => text(b) === "Changed").click();
      r.changedOnly = all("main .row").map((n) => n.id);
      all("#bar .pill").find((b) => text(b) === "All").click();
      $("[data-rvstep='1']").click(); r.pos = text($("#rvpos"));
      $("[data-rvview='clean']").click(); r.clean = { rv: $("#app").dataset.rv, nav: !!$("#rvpos") };
    } catch (e) { r.error = String(e && e.stack || e); }
    done(r);
  }, 600));
}

(kind === "unit" ? unit() : gate()).then((out) => { process.stdout.write(JSON.stringify(out)); process.exit(0); });
