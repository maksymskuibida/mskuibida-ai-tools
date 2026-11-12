/* Drive approval-gate.html under jsdom through one named scenario and print a JSON report of what the page shows.

     node drive_gate_page.js <page.html> <sample.json> <scenario>

   Scenarios: items (read the items, filter Unread), finding (answer finding cards), elements (mark document elements).
   The sample is what test_gate_page_render.py builds: the finalized row and documents, plus whatever the scenario needs. */
const fs = require("fs");
const { boot } = require("./gate_page_env");
const [pagePath, samplePath, scenario] = process.argv.slice(2);
const sample = JSON.parse(fs.readFileSync(samplePath, "utf8"));
const { w } = boot(pagePath, sample);
const d = w.document, $ = (sel) => d.querySelector(sel), all = (sel) => [...d.querySelectorAll(sel)];
const click = (sel) => { const n = typeof sel === "string" ? $(sel) : sel; if (!n) throw new Error("no " + sel); n.click(); };
const filter = (name) => click(all("#bar .fpill").find((b) => b.firstChild.textContent === name));
const shown = (n) => !!n && !n.hidden && !n.closest("[hidden]") && !n.closest(".eh");
const chips = () => all("#col > details.block:not([hidden])").map((b) => b.querySelector(":scope > summary").textContent.replace(/\s+/g, " ").trim());
const progress = () => { const r = d.querySelector("#ready"); return r ? "Read " + (+r.dataset.total - +r.dataset.unread) + "/" + r.dataset.total : ""; };
const where = () => { const a = d.activeElement; return a ? (a.closest("[data-fid]") ? "card:" + a.closest("[data-fid]").dataset.fid : a.closest("#b-findings") ? "findings-header" : a.closest("#bar") ? "bar" : a.closest("[data-ekey]") ? "el:" + a.closest("[data-ekey]").dataset.ekey : a.tagName) : ""; };

const scenarios = {
  items() {
    const r = {};
    const tiers = () => all("#b-items .tier").map((t) => ({ name: t.querySelector("h3").firstChild.textContent, shown: shown(t) }));
    const rows = all("#b-items .irow");
    r.rows = rows.length;
    filter("Unread");
    r.unreadAllShown = { block: shown($("#b-items")), tiers: tiers() };
    filter("All");
    for (let b; (b = all("#b-items .tier")[0].querySelector(".irow:not(.read) [data-iread]")); ) b.click();  /* the items repaint on each press */
    filter("Unread");
    r.firstTierRead = { block: shown($("#b-items")), tiers: tiers(), chips: chips() };
    filter("All");
    for (let b; (b = $("#b-items .irow:not(.read) [data-iread]")); ) b.click();
    filter("Unread");
    r.allRead = { block: shown($("#b-items")), tiers: tiers(), folds: all("#b-items details.settled").map(shown), chips: chips(), nomatch: shown($("#nomatch")) };
    filter("All");
    r.back = { block: shown($("#b-items")), tiers: tiers(), chips: chips() };
    return r;
  },
  finding() {
    const r = {}, card = (id) => $(`.fcard[data-fid="${id}"]`), pick = (id, k) => click(`[data-fpick="${k}"][data-fid="${id}"]`);
    r.before = { read: card("F1").classList.contains("read"), chip: chips().find((c) => c.startsWith("Findings")) };
    pick("F1", "fix");
    r.picked = { read: card("F1").classList.contains("read"), pick: card("F1").classList.contains("chosen"), other: card("F2").classList.contains("read") };
    pick("F1", "fix");  /* un-pick */
    r.unpicked = { read: card("F1").classList.contains("read"), pick: card("F1").classList.contains("chosen") };
    filter("Unread");
    r.unread = { f1: shown(card("F1")), f2: shown(card("F2")), f3: shown(card("F3")) };
    pick("F2", "accept");
    r.afterF2 = { f2: shown(card("F2")), focus: where() };
    pick("F3", "accept");
    r.afterAll = { block: shown($("#b-findings")), chip: chips().some((c) => c.startsWith("Findings")), focus: where() };
    filter("All");
    r.back = { block: shown($("#b-findings")), f1: shown(card("F1")), f1Read: card("F1").classList.contains("read") };
    return r;
  },
  elements() {
    const r = {}, doc = (k) => $("#d-" + k);
    const dots = (k) => all(`#d-${k} [data-eread]`);
    r.counts = { components: dots("components").length, entities: dots("entities").length, rules: dots("rules").length };
    r.keys = all("[data-eread]").map((b) => b.dataset.eread);
    r.dotRows = all("#d-rules tr.rrow").map((tr) => tr.lastElementChild.className);
    r.progress0 = progress();
    const first = dots("components")[0]; first.click();
    r.afterOne = { card: $("#d-components .card").classList.contains("er"), progress: progress(), blockRead: doc("components").classList.contains("read"), stored: Object.keys(JSON.parse(w.localStorage.getItem(w.localStorage.key(0)) || "{}")) };
    filter("Unread");
    r.unreadOne = { hiddenCards: all("#d-components .card").filter((c) => !shown(c)).length, total: all("#d-components .card").length, blockShown: shown(doc("components")) };
    dots("components").forEach((b) => { if (b.closest("[data-ekey]").classList.contains("er")) return; b.click(); });
    r.unreadAll = { blockShown: shown(doc("components")), blockRead: doc("components").classList.contains("read"), chip: chips().filter((c) => c.startsWith("Components")), entities: shown(doc("entities")) };
    filter("All");
    r.entityMark = (() => { const b = dots("entities")[0]; b.click(); const sec = b.closest("details.sec"); return { read: sec.classList.contains("er"), key: b.dataset.eread }; })();
    r.rule = (() => { const tr = $("#d-rules tr.rrow"); const b = tr.querySelector("[data-eread]"); b.click(); return { read: tr.classList.contains("er"), det: tr.nextElementSibling.dataset.ekeyOf === b.dataset.eread }; })();
    filter("Unread");
    r.rulesUnread = { shownRows: all("#d-rules tr.rrow").filter(shown).length, rows: all("#d-rules tr.rrow").length, detEh: all("#d-rules tr.rdet.eh").length };
    filter("All");
    /* the block's own dot marks every element, and unmarking it clears them */
    $("#d-rules > summary .rdot").click();
    r.blockDot = { elements: all("#d-rules tr.rrow").every((t) => t.classList.contains("er")), blockRead: doc("rules").classList.contains("read") };
    $("#d-rules > summary .rdot").click();
    r.blockDotOff = { elements: all("#d-rules tr.rrow").some((t) => t.classList.contains("er")), blockRead: doc("rules").classList.contains("read") };
    return r;
  },
};
setTimeout(() => {
  let out;
  try { out = scenarios[scenario](); } catch (e) { out = { error: String(e && e.stack || e) }; }
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
}, 400);
