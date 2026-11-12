/* Batch 2 on the Unit page's controller under jsdom: the Needs you filter keeps a settled row until the bar is pressed again,
   the readiness counter and the n / u keys go to the next row, and Your answer lists the picks.

     node drive_batch2_unit.js <unit-gate.html> <bundle.json>

   bundle.json: {id, bundle, createdAt, intent, unit}. Prints a JSON report. Needs the jsdom package. */
const fs = require("fs");
const { JSDOM } = require("jsdom");
const [pagePath, bundlePath] = process.argv.slice(2);
const row = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
const html = fs.readFileSync(pagePath, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
const dom = new JSDOM("<!doctype html><html><head></head><body>" + html + "</body></html>", { runScripts: "outside-only", pretendToBeVisual: true, url: "https://claude.ai/artifact/x#" + row.id });
const w = dom.window;
w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
w.scrollTo = () => {};
w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
w.Element.prototype.scrollIntoView = function () {};
const writes = [];
const snap = (id, data) => ({ id, exists: data !== undefined, data: () => data });
const q = (docs) => { const o = { orderBy: () => o, limit: () => o, where: () => o, get: async () => ({ docs: docs.map(([i, d]) => snap(i, d)) }), onSnapshot: (cb) => { setTimeout(() => cb({ docs: docs.map(([i, d]) => snap(i, d)) })); return () => {}; }, doc: () => ({ get: async () => snap("x", undefined), set: async () => {} }) }; return o; };
const db = { collection: () => q([]), doc: () => ({ onSnapshot: (cb) => { setTimeout(() => cb(snap(row.id, row))); return () => {}; }, update: async (v) => { writes.push(v); } }) };
w.claude = { use: async (what) => (what === "db" ? db : { id: async () => "viewer" }) };
for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) { if (/RENDER-START|"use strict"/.test(m[1]) || true) w.eval(m[1]); }
const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");
const ids = () => all("main .row[id]").filter((r) => !r.closest("#records, #answer")).map((r) => r.id);
const pill = (v) => $(`.pill[data-val="${v}"]`);
const press = (key, target) => (target || d).dispatchEvent(new w.KeyboardEvent("keydown", { key, bubbles: true }));
const clearFlash = () => all(".flash").forEach((n) => n.classList.remove("flash"));
(async () => {
  await wait(400);
  const out = { ready0: text($("#ready")), needsPill: text(pill("needs")) };
  pill("needs").click();
  out.needsRows = ids();
  /* a pick: the row stays, greyed, and the count drops */
  $('.row[id="A-2"] [data-act="pick"][data-val="do"]').click();
  out.afterPick = { rows: ids(), settled: $('.row[id="A-2"]').classList.contains("nsettled"), pill: text(pill("needs")) };
  pill("needs").click();
  out.afterBar = ids();
  pill("all").click();
  $('.row[id="A-2"] [data-act="pick"][data-val="do"]').click();  /* take the pick back: one decision waits again */
  /* the buttons and the keys walk the decisions */
  const hit = [];
  for (let i = 0; i < 3; i++) { clearFlash(); $('[data-act="next"][data-val="n"]').click(); hit.push(all(".flash").map((n) => n.id)[0]); }
  out.nextN = hit;
  clearFlash(); press("n"); out.keyN = all(".flash").map((n) => n.id)[0];
  clearFlash(); press("u"); out.keyU = all(".flash").map((n) => n.id)[0];
  clearFlash(); $('[data-act="row"][data-key="A-2"]'); $('.row[id="A-2"] textarea').focus(); press("n", $('.row[id="A-2"] textarea')); out.inField = all(".flash").length;
  /* read everything, pick the rest: ready, and the button goes to Your answer */
  const ta = $('textarea[data-note="A-1"]'); ta.value = "keep it short"; ta.dispatchEvent(new w.Event("input", { bubbles: true }));
  all('[data-act="pick"][data-val="leave"]').forEach((b) => b.click());
  $('[data-act="allread"]').click();
  out.afterRead = text($("#ready"));
  out.answer = all("#answer .ansg").map((g) => g.dataset.ans + ":" + [...g.querySelectorAll("li")].map(text).join("|"));
  await wait(900);
  out.writes = writes.map((x) => Object.keys(x).sort().join(","));
  process.stdout.write(JSON.stringify(out)); process.exit(0);
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); process.exit(0); });
