/* Batch 1 scenarios for approval-gate.html under jsdom: one list of targets, a read mark for every separate thing, round
   changes on every structured block.

     node drive_batch1.js <page.html> <sample.json> <scenario>

   sample.json is what batch1_fixture.py prints. Scenarios: layout, picks, unread, derived, carry, rounds.
   RV_PREF=show|none picks the viewer's stored view (default show: Changes; none: Clean with each round's colour). */
const fs = require("fs");
const { boot } = require("./gate_page_env");
const [pagePath, samplePath, scenario] = process.argv.slice(2);
const sample = JSON.parse(fs.readFileSync(samplePath, "utf8"));
const PREF = process.env.RV_PREF || "show";
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const seeded = (marks) => (w) => { if (PREF !== "none") w.localStorage.setItem("aidlc-rev:view", PREF); Object.keys(marks || {}).forEach((k) => w.localStorage.setItem(k, marks[k])); };

function tools(w) {
  const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
  const shown = (n) => !!n && !n.hidden && !n.closest("[hidden]") && !n.closest(".eh");
  const filter = (name) => all("#bar .fpill").find((b) => b.firstChild.textContent === name).click();
  const progress = () => text($("#bar .progress-r .num"));
  const dotKeys = () => all("[data-iread]").map((n) => n.dataset.iread).concat(all("[data-eread]").map((n) => n.dataset.eread)).concat(all(".rdot").map((n) => "block:" + n.dataset.read));
  return { d, $, all, shown, filter, progress, dotKeys };
}
const CONTAINERS = ".dsec, details.settled, details.cgroup, section.esec:not(.lf), .tm-fold";

const scenarios = {
  async layout() {
    const { w, writes } = boot(pagePath, sample, seeded());
    await wait(500);
    const { d, $, all, dotKeys } = tools(w);
    const rows = all(".tm-row[data-tid]");
    const fold = $("details.tm-fold");
    return {
      blocks: all("#col > details.block, #col > section").map((b) => b.id),
      decideBlock: !!$("#b-bt-decide"), decideChip: all("#bar .jchip").some((c) => /Decisions/.test(c.textContent)),
      rowIds: rows.map((r) => r.dataset.tid), openRows: rows.filter((r) => !r.closest("details.tm-fold")).map((r) => r.dataset.tid),
      foldRows: rows.filter((r) => r.closest("details.tm-fold")).map((r) => r.dataset.tid), foldSummary: text(fold && fold.querySelector("summary")), foldOpen: !!(fold && fold.open),
      cardsOfTargets: all(".dcard[data-did]").length, picksPerOpenRow: rows.filter((r) => !r.closest("details.tm-fold")).map((r) => r.querySelectorAll("[data-pick]").length),
      picksInFold: rows.filter((r) => r.closest("details.tm-fold")).reduce((n, r) => n + r.querySelectorAll("[data-pick]").length, 0),
      dcount: text($("#bt-dcount")), disagree: all(".tag.dis").map(text), disagreeRow: all(".tag.dis").map((t) => t.closest(".tm-row").dataset.tid),
      itemRows: all("#b-items .irow").map((r) => ({ id: r.dataset.aidlcId, item: r.dataset.item, tlink: r.classList.contains("tlink"), vtags: r.querySelectorAll(".vtag").length, expected: /order page p95/.test(r.textContent), dot: r.querySelectorAll("[data-iread]").length, link: !!r.querySelector("[data-tgo]") })),
      itemsHead: text($("#b-items summary .hint")), itemsRead: text($("#items-read")),
      matrixDoc: all("details.doc[data-matrixdoc]").map((b) => ({ id: b.id, open: b.open, note: text(b.querySelector(".mxnote")), hint: text(b.querySelector(".mxsum")) })),
      /* targets tables the viewer can see: a table with a Target ID column inside nothing folded */
      targetTablesShown: all("#col table").filter((t) => /target/i.test(text(t.querySelector("thead"))) && !t.closest(".tmx") && ![...(function* () { let p = t.closest("details"); while (p) { yield p; p = p.parentElement && p.parentElement.closest("details"); } })()].some((dd) => !dd.open)).length,
      briefRows: all("#briefbody tr.frow").map((r) => ({ id: r.dataset.ref, sorted: r.classList.contains("sorted"), detail: !!r.parentElement.querySelector(`tr.fdet[data-for="${r.dataset.i}"]`) })),
      dots: dotKeys(),
    };
  },
  async picks() {
    const { w, writes } = boot(pagePath, sample, seeded());
    await wait(500);
    const { d, $, all, progress } = tools(w);
    const before = progress();
    $('.tm-row[data-tid="u1:NFR1"] [data-pick="fix"]').click();
    const ta = $('.tm-row[data-tid="u1:NFR1"] .dnote'); $('.tm-row[data-tid="u1:NFR1"] [data-pnote]').click();
    ta.value = "slow on a 3G phone"; ta.dispatchEvent(new w.Event("input", { bubbles: true }));
    $('.tm-row[data-tid="u1:NFR2"] [data-pick="followup"]').click();
    await wait(1000);
    const row = $('.tm-row[data-tid="u1:NFR1"]');
    return { writes: writes.map((x) => x.targetPicks).filter(Boolean), dcount: text($("#bt-dcount")), chosen: row.classList.contains("chosen"), read: row.classList.contains("read"), pressed: row.querySelector('[data-pick="fix"]').getAttribute("aria-checked"), before, after: progress(), chip: all("#bar .jchip").map(text).find((c) => /^Matrix/.test(c)) };
  },
  async unread() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const { d, $, all, shown, filter, progress, dotKeys } = tools(w);
    const r = { keys: dotKeys(), progress0: progress() };
    filter("Unread");
    r.visibleBefore = all("[data-item]").filter(shown).length;
    let n = 0;
    for (let b; n < 300 && (b = all("[data-iread], [data-eread]").find((x) => shown(x))); n++) b.click();
    r.clicks = n;
    r.visibleItems = all("[data-item]").filter(shown).map((x) => x.dataset.item);
    r.visibleElems = all("[data-ekey]").filter(shown).map((x) => x.dataset.ekey);
    r.visibleContainers = all(CONTAINERS).filter(shown).map((x) => x.className + ":" + text(x).slice(0, 30));
    r.blocksShown = all("#col > details.block, #col > section").filter(shown).map((b) => b.id);
    r.nomatch = shown($("#nomatch"));
    r.progress1 = progress();
    return r;
  },
  async derived() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(500);
    const { d, $, all, shown, filter } = tools(w);
    const targetDots = () => all(".tm-row .idot").map((x) => x.classList.contains("isread"));
    const r = { before: targetDots() };
    $('.tm-row[data-tid="u1:NFR1"] .idot').click();
    r.oneRead = targetDots(); r.matrixBlockRead = $("#b-bt-matrix").classList.contains("read");
    $("#b-bt-matrix > summary .rdot").click();
    r.afterBlockDot = targetDots(); r.matrixBlockRead2 = $("#b-bt-matrix").classList.contains("read");
    $("#b-bt-matrix > summary .rdot").click();
    r.afterBlockDot2 = targetDots();
    $("#b-eval > summary .rdot").click();
    r.evalDots = all("#b-eval [data-iread]").map((x) => x.dataset.iread + ":" + x.classList.contains("isread"));
    $('#b-eval details.crow .idot').click();
    r.evalBlockRead = $("#b-eval").classList.contains("read");
    r.itemLinkRead = (() => { const row = $("#b-items .irow.tlink"); return row && row.classList.contains("read"); })();
    return r;
  },
  async carry() {
    /* round one: everything read; round two on the same browser: what is unread */
    const one = JSON.parse(fs.readFileSync(samplePath.replace(/\.json$/, ".r1.json"), "utf8"));
    const first = boot(pagePath, one, seeded());
    await wait(500);
    const t1 = tools(first.w);
    t1.all("[data-allread]")[0].click();
    const marks = {}; const ls = first.w.localStorage;
    for (let i = 0; i < ls.length; i++) marks[ls.key(i)] = ls.getItem(ls.key(i));
    const progress1 = t1.progress();
    const second = boot(pagePath, sample, seeded(marks));
    await wait(1200);
    const t2 = tools(second.w);
    const unreadKeys = t2.all("[data-iread]").filter((x) => !x.classList.contains("isread")).map((x) => x.dataset.iread);
    const unreadEl = t2.all("[data-eread]").filter((x) => !x.classList.contains("isread")).map((x) => x.dataset.eread);
    const blocks = t2.all("#col > details.block").filter((b) => b.dataset.block).map((b) => b.dataset.block + ":" + (b.classList.contains("read") ? "read" : "unread"));
    t2.filter("Unread");
    const shownItems = t2.all("[data-item]").filter(t2.shown).map((x) => x.dataset.item);
    const changed = (() => { const o = {}; t2.all("[data-item].rv-chg, [data-item].rv-new").forEach((x) => { o[x.dataset.item] = x.classList.contains("rv-new") ? "new" : "changed"; }); return o; })();
    const same = t2.all("[data-item].rv-same").map((x) => x.dataset.item);
    return { progress1, unreadKeys, unreadEl, blocks, shownItems, changed, same, progress2: t2.progress() };
  },
  async rounds() {
    const { w } = boot(pagePath, sample, seeded());
    await wait(1500);
    const { d, $, all } = tools(w);
    const tag = (n) => [...n.querySelectorAll(".rv-tags .rv-tag")].map(text);
    return {
      chips: all("#bar .jchip").map(text),
      findings: all(".fcard").map((n) => ({ id: n.dataset.fid, cls: ["rv-new", "rv-chg", "rv-same"].filter((c) => n.classList.contains(c)), tags: tag(n), ins: [...n.querySelectorAll("ins.rv-ins")].map(text), del: [...n.querySelectorAll("del.rv-del")].map(text) })),
      targets: all(".tm-row[data-tid]").map((n) => ({ id: n.dataset.tid, cls: ["rv-new", "rv-chg", "rv-same"].filter((c) => n.classList.contains(c)), tags: tag(n), ins: [...n.querySelectorAll("ins.rv-ins")].map(text) })),
      removed: all(".rvgone .rv-removed").map(text), list: all("#rv-list li").map(text),
      brief: { ins: [...$("#briefbody").querySelectorAll("ins.rv-ins")].map(text), del: [...$("#briefbody").querySelectorAll("del.rv-del")].map(text) },
      edges: all(".rv-rb").map((n) => (n.dataset.fid || n.dataset.tid || n.dataset.item || n.id) + ":" + (n.className.match(/rv-r(\d+)/) || [])[1]),
      tinted: all("ins.rv-r").map((n) => [n.className.match(/rv-r(\d+)/)[1], n.textContent]),
      critTags: all("#b-eval details.crow").map((n) => n.id + ":" + ["rv-new", "rv-chg", "rv-same"].filter((c) => n.classList.contains(c)).join("")),
    };
  },
};
scenarios[scenario]().then((out) => { process.stdout.write(JSON.stringify(out)); process.exit(0); }).catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); process.exit(0); });
