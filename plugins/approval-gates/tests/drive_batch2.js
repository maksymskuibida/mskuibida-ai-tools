/* Batch 2 scenarios for approval-gate.html under jsdom: Needs you is a view over the items in place, the readiness counter and
   its keys, Your answer, Records.

     node drive_batch2.js <page.html> <sample.json> <scenario>

   sample.json is what test_batch2.py writes. Scenarios: view, shared, settle, ready, answer, records, deeplink, marks. */
const fs = require("fs");
const { boot } = require("./gate_page_env");
const [pagePath, samplePath, scenario] = process.argv.slice(2);
const sample = JSON.parse(fs.readFileSync(samplePath, "utf8"));
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const seeded = (marks) => (w) => { w.localStorage.setItem("aidlc-rev:view", "show"); Object.keys(marks || {}).forEach((k) => w.localStorage.setItem(k, marks[k])); };

function tools(w) {
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  const shown = (n) => !!n && !n.hidden && !n.closest("[hidden]") && !n.closest(".eh");
  const filter = (name) => all("#bar .fpill").find((b) => b.firstChild.textContent === name).click();
  const pill = (name) => text(all("#bar .fpill").find((b) => b.firstChild.textContent === name));
  const ready = () => ({ text: text($("#ready")), decisions: +$("#ready").dataset.decisions, unread: +$("#ready").dataset.unread });
  const press = (key, target) => (target || d).dispatchEvent(new w.KeyboardEvent("keydown", { key, bubbles: true }));
  const clearFlash = () => all(".flash").forEach((n) => n.classList.remove("flash"));
  const flashed = () => all(".flash").map((n) => n.dataset.item || n.dataset.ekey || n.id).filter(Boolean);
  const visibleItems = () => all("[data-item]").filter(shown).map((n) => n.dataset.item);
  const blocks = () => all("#col > details.block, #col > section").filter(shown).map((b) => b.id);
  return { d, $, all, shown, filter, pill, ready, press, flashed, clearFlash, visibleItems, blocks };
}

const scenarios = {
  async view() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const r = { pillBefore: t.pill("Needs you"), order: all("#bar .fpill").map((b) => b.firstChild.textContent), ready: t.ready(), allBlocks: t.blocks() };
    t.filter("Needs you");
    r.pressed = $('#bar .fpill[aria-pressed="true"]').firstChild.textContent;
    r.items = t.visibleItems();
    r.blocks = t.blocks();
    r.sections = all("#col > details.block").filter(t.shown).map((b) => ({ id: b.id, head: text(b.querySelector(":scope > summary h2")) }));
    r.stripTiles = all("#b-bt-strip .bts").filter(t.shown).map((n) => n.dataset.item || "plain");
    r.containers = all(".dsec, details.settled, details.cgroup, section.esec:not(.lf), .tm-fold").filter(t.shown).map((n) => n.className);
    r.rows = all(".tm-row[data-tid]").filter(t.shown).map((n) => n.dataset.tid);
    r.nomatch = t.shown($("#nomatch"));
    r.answerShown = t.shown($("#b-answer"));
    return r;
  },
  async shared() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const out = {};
    t.filter("Needs you");
    const row = $('[data-item="crit:review-1"]');
    out.sameNode = row;
    row.querySelector("[data-iread]").click();
    out.afterRead = { stillShown: t.shown(row), settled: row.classList.contains("nsettled"), read: row.classList.contains("read") };
    t.filter("All");
    out.underAll = { sameNode: $('[data-item="crit:review-1"]') === row, read: row.classList.contains("read"), dot: row.querySelector("[data-iread]").classList.contains("isread") };
    /* the reverse: a mark set under All is there under Needs you */
    $('[data-item="item:FR2"] [data-iread]').click();
    t.filter("Needs you");
    out.itemAfterReadUnderAll = t.visibleItems().includes("item:FR2");
    /* a note typed in a target row under Needs you is the note under All */
    const tr = $('.tm-row[data-tid="u1:NFR1"]');
    tr.querySelector("[data-pnote]").click();
    const ta = tr.querySelector(".dnote"); ta.value = "check on a 3G phone"; ta.dispatchEvent(new w.Event("input", { bubbles: true }));
    t.filter("All");
    out.noteUnderAll = $('.tm-row[data-tid="u1:NFR1"] .dnote').value;
    out.sameRow = $('.tm-row[data-tid="u1:NFR1"]') === tr;
    return out;
  },
  async settle() {
    const { w, writes } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const out = { count0: t.pill("Needs you") };
    t.filter("Needs you");
    const row = $('.tm-row[data-tid="u1:NFR1"]');
    /* reading is not deciding: the dot leaves the row where it is, still waiting */
    row.querySelector("[data-iread]").click();
    out.afterReadOnly = { shown: t.shown(row), settled: row.classList.contains("nsettled"), count: t.pill("Needs you") };
    row.querySelector('[data-pick="fix"]').click();
    out.afterPick = { shown: t.shown(row), settled: row.classList.contains("nsettled"), count: t.pill("Needs you"), chosen: row.classList.contains("chosen") };
    /* the undo: the pick pressed again brings the row back as waiting */
    row.querySelector('[data-pick="fix"]').click();
    out.afterUndo = { shown: t.shown(row), settled: row.classList.contains("nsettled"), count: t.pill("Needs you") };
    row.querySelector('[data-pick="fix"]').click();
    /* a finding sorted, then the filter is painted again from the bar: the settled ones leave */
    const card = $('.fcard[data-fid="R-01"]');
    card.querySelector('[data-fpick="fix"]').click();
    await wait(1000);
    const card2 = $('.fcard[data-fid="R-01"]');
    out.findingKept = { shown: t.shown(card2), settled: card2.classList.contains("nsettled") };
    t.filter("Needs you");
    out.afterRepaint = t.visibleItems();
    out.count1 = t.pill("Needs you");
    out.writes = writes.filter((x) => x.targetPicks).length > 0;
    return out;
  },
  async ready() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const out = { initial: t.ready() };
    const seen = [];
    for (let i = 0; i < 6; i++) { t.clearFlash(); $('[data-rdy="n"]').click(); seen.push(t.flashed()[0]); }
    out.nextDecisions = seen;
    t.clearFlash(); $('[data-rdy="u"]').click(); out.firstUnread = t.flashed()[0];
    /* the keys do the same, and stay silent inside a field */
    t.clearFlash(); t.press("n"); const viaKey = t.flashed()[0];
    out.keyN = viaKey;
    t.clearFlash(); const before = t.flashed().length;
    $('.tm-row[data-tid="u1:NFR1"] [data-pnote]').click();
    const ta = $('.tm-row[data-tid="u1:NFR1"] .dnote');
    t.press("n", ta); t.press("u", ta);
    out.firedInField = t.flashed().length !== before;
    t.clearFlash(); t.press("u"); out.keyU = t.flashed()[0];
    /* decide everything and read everything: ready */
    all("[data-pick='accept']").forEach((b) => b.click());
    all("[data-fpick='fix']").forEach((b) => b.click());
    out.afterPicks = t.ready();
    $("[data-allread]").click();
    out.afterRead = t.ready();
    $('[data-rdy="a"]').click();
    out.answerOpen = $("#b-answer").open; out.answerShown = t.shown($("#b-answer"));
    out.flashAnswer = $("#b-answer").classList.contains("flash");
    return out;
  },
  async answer() {
    const { w, writes } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const out = { empty: text($("#answerbody")), last: all("#col > details.block, #col > section").map((b) => b.id).slice(-2) };
    $('.tm-row[data-tid="u1:NFR1"] [data-pick="fix"]').click();
    $('.tm-row[data-tid="u1:NFR2"] [data-pick="followup"]').click();
    const ta = $('.tm-row[data-tid="u1:NFR2"] .dnote'); $('.tm-row[data-tid="u1:NFR2"] [data-pnote]').click();
    ta.value = "run it after a restart"; ta.dispatchEvent(new w.Event("input", { bubbles: true }));
    $('.fcard[data-fid="R-01"] [data-fpick="accept"]').disabled || 0;
    $('.fcard[data-fid="R-02"] [data-fpick="accept"]').click();
    const nb = $('.notebtn[data-key="release-notes"]'); nb.click();
    const nt = $("#nt-release-notes"); nt.value = "mention the 3 s page"; nt.dispatchEvent(new w.Event("input", { bubbles: true }));
    await wait(1000);
    out.groups = all("#answerbody .ans-g").map((g) => ({ id: g.dataset.ans, rows: [...g.querySelectorAll("li")].map((li) => [...li.children].map(text).join(" ")) }));
    out.statement = text($("#answerbody .dsum"));
    out.left = text($("#answerbody .ans-left"));
    out.links = all("#answerbody [data-ansgo]").map((b) => b.dataset.ansgo);
    all("#answerbody [data-ansgo]").find((b) => b.dataset.ansgo === "target:U1/u1:NFR1").click();
    out.jumped = t.flashed();
    out.writes = writes.map((x) => Object.keys(x).sort().join(","));
    out.stored = { local: Object.keys(w.localStorage).filter((k) => /answer/i.test(k)) };
    return out;
  },
  async records() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const rec = $("#b-records");
    const row = (b) => ({ id: b.id, why: (b.querySelector("summary .why") || {}).dataset ? b.querySelector("summary .why").dataset.why : "", kind: text(b.querySelector("summary .pill")), dot: !!b.querySelector("summary .rdot"), rev: !!b.querySelector("summary .rv-tag") });
    return {
      blocks: all("#col > details.block, #col > section").map((b) => b.id),
      recordsOpen: rec.open, count: text($("#rec-count")),
      rows: all("#b-records details.doc").map(row),
      docsOutside: all("#col details.block.doc").filter((b) => !b.closest("#b-records")).map((b) => b.id),
      oldBlocks: [!!$("#b-reference"), !!$("#b-aswritten")],
      chips: all("#bar .jchip").map(text),
      readyBefore: t.ready(),
    };
  },
  async deeplink() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const t = tools(w), { $, all } = t;
    const out = { before: { records: $("#b-records").open, doc: $("#d-build-and-test-summary").open } };
    /* an id link and a source link into a file: Records opens, then the file, then the target */
    const open = all("[data-iopen]").find((n) => n.dataset.iopen === "FR1");
    open.click();
    const src = all(".jump[data-go]").find((n) => n.dataset.go === "d-build-and-test-summary");
    out.hasSource = !!src;
    t.clearFlash(); src.click();
    out.afterGo = { records: $("#b-records").open, doc: $("#d-build-and-test-summary").open, flashed: $("#d-build-and-test-summary").classList.contains("flash") };
    const link = all("#bar .jchip").find((c) => /Records/.test(c.textContent));
    $("#b-records").open = false; link.click();
    out.afterChip = { records: $("#b-records").open, hasChip: !!link };
    $("#b-records").open = false;
    $('[data-rvgo]') && 0;
    const id = $("#b-records details.doc:not(.rv-removed) [data-aidlc-id]");
    out.hasIdTarget = !!id;
    return out;
  },
  async marks() {
    /* a mark made on a document before Records existed keeps its key: reading a document row here writes the document's own key */
    const first = boot(pagePath, sample, seeded());
    await wait(500);
    const t1 = tools(first.w);
    t1.d.querySelector('#d-release-notes > summary .rdot').click();
    const stored = JSON.parse(first.w.localStorage.getItem(Object.keys(first.w.localStorage).find((k) => /^approval-gates:reads:/.test(k))));
    const keys = Object.keys(stored);
    const marks = {}; for (let i = 0; i < first.w.localStorage.length; i++) marks[first.w.localStorage.key(i)] = first.w.localStorage.getItem(first.w.localStorage.key(i));
    const second = boot(pagePath, sample, seeded(marks));
    await wait(500);
    const t2 = tools(second.w);
    return { keys, secondRead: t2.d.querySelector("#d-release-notes").classList.contains("read"), unreadAfter: t2.ready().unread, unreadBefore: t1.ready().unread };
  },
};
scenarios[scenario]().then((out) => { process.stdout.write(JSON.stringify(out, (k, v) => (v && v.nodeType ? "<node>" : v))); process.exit(0); }).catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); process.exit(0); });
