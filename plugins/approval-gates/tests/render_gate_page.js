/* Render skills/approval-gates/approval-gate.html under jsdom with a stand-in for the artifact's db, holding one gate.

     node render_gate_page.js <page.html> <sample.json> [<out.html>]

   sample.json: {id, row, documents: {<doc id>: <document row>}}, what gate_bundle.py finalize writes. The script opens the
   gate, opens the first item and presses the first source chip, then prints a JSON report of what the page shows; with
   <out.html> it also writes the page as rendered (styles kept, scripts removed) for a person to open.
   Needs the jsdom package (NODE_PATH or a local node_modules); marked, dompurify and js-yaml are used when found. */
const fs = require("fs");
const [pagePath, samplePath, outPath] = process.argv.slice(2);
const sample = JSON.parse(fs.readFileSync(samplePath, "utf8"));

const { boot } = require("./gate_page_env");
const { w, writes, html } = boot(pagePath, sample);

setTimeout(() => {
  const d = w.document, $ = (sel) => d.querySelector(sel), all = (sel) => [...d.querySelectorAll(sel)];
  const text = (sel) => ($(sel) || {}).textContent || "";
  const report = {
    title: text("#title"),
    blocks: all("#col > details.block, #col > section").map((b) => b.id),
    chips: all("#bar .jchip").map((c) => c.textContent.replace(/\s+/g, " ").trim()),
    verdict: text("#b-eval > summary .pill"),
    decides: text("#b-eval .decides"),
    lookFirst: all("#b-eval ol.lfl > li").map((li) => li.textContent.replace(/\s+/g, " ").trim()),
    columns: all("#b-eval .ecol h3").map((h) => h.textContent.replace(/\s+/g, " ").trim()),
    criteria: all("#b-eval details.crow").map((c) => ({ id: c.id, verdict: c.querySelector(".tag").textContent, title: c.querySelector(".ctitle").textContent })),
    tiers: all("#b-items .tier h3").map((h) => h.firstChild.textContent),
    items: all("#b-items .irow.j").map((r) => ({ id: r.querySelector(".iid").textContent, summary: r.querySelector(".isum").textContent,
      chips: [...r.querySelectorAll(".imeta .tag")].map((t) => t.textContent) })),
    folds: all("#b-items details.settled > summary").map((s) => s.textContent),
    records: all("#b-records details.doc").map((b) => b.id),
    recordsWhy: Object.fromEntries(all("#b-records details.doc").map((b) => [b.id, (b.querySelector("summary .why") || {}).dataset ? b.querySelector("summary .why").dataset.why : ""])),
    recordsOpen: !!($("#b-records") || {}).open,
    docsOutsideRecords: all("#col details.block.doc").filter((b) => !b.closest("#b-records")).map((b) => b.id),
    tablesOutsideRecords: all("#col table").filter((t) => !t.closest("#b-records") && !t.closest(".tmx")).map((t) => (t.closest("details.block") || {}).id),
    readDots: all("#col .rdot, #col .idot").length,
  };
  const first = $("#b-items .irow.j .isum");
  if (first) {
    first.click();
    const row = $("#b-items .irow.j .ib");
    report.opened = row ? row.textContent.replace(/\s+/g, " ").trim() : "";
    report.openedJump = row ? !!row.querySelector("a.jump") : false;
  }
  const src = $("#b-eval .src[data-src^='c:']");
  if (src) { src.click(); const c = d.getElementById("crit-" + src.dataset.src.slice(2)); report.sourceOpened = !!(c && c.open); }
  report.writes = writes.length;
  if (outPath) {
    all("script").forEach((s) => s.remove());
    fs.writeFileSync(outPath, "<!doctype html>\n" + d.documentElement.outerHTML);
  }
  process.stdout.write(JSON.stringify(report));
  process.exit(0);
}, 400);
