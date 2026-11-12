/* Drive the pages dev/preview.py wrote under jsdom and report what fix round 2 of the pages does.

     node drive_fix2.js <scenario> <page.html>      prints one JSON object

   scenarios: trace (the traceability disclosure opens to the trace), bar (the Rounds control, View and actions, the keys, the All pill),
              item (an opened item says its sentence once), dots (a criterion's read dot), ack (the acknowledgement sits with the actions),
              unit-reads (Do it / Leave it mark the row read), unit-split (the header's split is the rows' tags), unit-needs (the chip is
              the rows that wait; a settled row says Done), unit-answer (a note is listed once), unit-chain (the pieces wrap, none under three),
              viz-cue (a diagram wider than its frame says so) */
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");
const optional = (name) => { try { return require(name); } catch { return null; } };
const [scenario, file] = process.argv.slice(2);

function boot() {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String((e && e.message) || e)));
  vc.on("error", (...a) => errors.push(a.map(String).join(" ")));
  const html = fs.readFileSync(file, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, url: "https://claude.ai/artifact/x", virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
      w.scrollTo = () => {}; w.scrollBy = () => {};
      w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
      w.Element.prototype.scrollIntoView = function () {};
      const marked = optional("marked"), purify = optional("dompurify"), yaml = optional("js-yaml");
      if (marked && purify) { w.marked = marked.marked || marked; w.DOMPurify = (purify.default || purify)(w); }
      if (yaml) w.jsyaml = yaml;
    },
  });
  return { w: dom.window, errors };
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const click = (w, n) => n.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");

async function trace() {
  const { w, errors } = boot(); await wait(700);
  const d = w.document, det = d.querySelector("details[data-settled=trace]");
  if (!det) return { errors, found: false };
  det.open = true;
  const sum = text(det.querySelector("summary")), body = text(det).slice(sum.length).trim();
  return { errors, found: true, summary: sum, body, entries: det.querySelectorAll(".tlist li, td.hit, td.miss").length, again: body.startsWith(sum) || body.includes(sum) };
}

async function bar() {
  const { w, errors } = boot(); await wait(700);
  const d = w.document, rounds = d.querySelector('[data-menu=rounds], [data-val=rounds]'), view = d.querySelector('[data-menu=view], [data-val=view]');
  const all = d.querySelector('[data-filter=all], [data-val=all]');
  const out = { errors, long: text(rounds && rounds.querySelector(".rl-l")), short: text(rounds && rounds.querySelector(".rl-s")), roundsClass: rounds ? rounds.className : "", roundsAria: rounds ? rounds.getAttribute("aria-label") : "",
    viewAria: view ? view.getAttribute("aria-label") : "", viewLong: text(view && view.querySelector(".vl-l")), viewShort: text(view && view.querySelector(".vl-s")), allPill: text(all), allHasCount: !!(all && all.querySelector(".n, b.n")) };
  if (view) {
    d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "?", bubbles: true })); await wait(100);
    const pop = d.querySelector("#m-view");
    out.questionOpens = !!pop && !pop.hidden;
    out.keys = [...d.querySelectorAll("#m-view .keys kbd")].map(text);
    out.actionsLabels = [...d.querySelectorAll("#m-view .bml")].map(text);
    out.actions = [...d.querySelectorAll("#m-view button")].map(text).filter((t) => /all/i.test(t));
  }
  return out;
}

async function item() {
  const { w, errors } = boot(); await wait(700);
  const d = w.document, ix = d.querySelector("#b-items .ix, #b-items [data-iopen]");
  click(w, ix); await wait(400);
  const row = ix.closest(".irow"), sum = text(row.querySelector(".isum")).toLowerCase();
  const first = text(row.querySelector(".aw p, .aw li, .aw")).toLowerCase();
  const paras = [...row.querySelectorAll(".aw p")].map((p) => text(p).toLowerCase());
  return { errors, summary: sum, paras, sayingTwice: paras.some((p) => p.length >= 20 && sum.includes(p)), rel: [...row.querySelectorAll(".rel .chip")].map(text), first };
}

async function dots() {
  const { w, errors } = boot(); await wait(700);
  const d = w.document;
  return { errors, labels: [...d.querySelectorAll(".crow .idot")].map((x) => x.getAttribute("aria-label")) };
}

async function ack() {
  const { w, errors } = boot(); await wait(700);
  const d = w.document, t = d.querySelector('.bts[data-item="cmd:failed"]'), b = t && t.querySelector(".ackbtn");
  if (!b) return { errors, found: false };
  const kids = [...t.children];
  return { errors, found: true, last: kids[kids.length - 1] === b, afterLabel: kids.indexOf(b) > kids.indexOf(t.querySelector(".lbl")), nextToDot: b.nextElementSibling === t.querySelector(".idot") || b.previousElementSibling === t.querySelector(".idot") };
}

async function unitReads() {
  const { w, errors } = boot(); await wait(800);
  const d = w.document, n = () => text(d.querySelector("[data-val=unread] .n, [data-val=unread] b"));
  const out = { errors, before: n() };
  const first = d.querySelector(".row .suggestpick [data-val=do]"), rowId = first.dataset.key;
  click(w, first); await wait(100);
  out.afterDo = n(); out.dotAfterDo = d.getElementById(rowId).querySelector(".dot").getAttribute("aria-label");
  const second = [...d.querySelectorAll(".row .suggestpick [data-val=leave]")].find((b) => b.dataset.key !== rowId);
  click(w, second); await wait(100);
  out.afterLeave = n();
  const test = d.querySelector(".row .testpick:not(.suggestpick) [data-val=now]");
  out.hasTestPick = !!test;
  return out;
}

async function unitSplit() {
  const { w, errors } = boot(); await wait(900);
  const d = w.document, head = text(d.querySelector(".revs"));
  const m = head.match(/(\d+) changed · (\d+) new · (\d+) removed/) || [];
  const kinds = { changed: 0, new: 0 };
  d.querySelectorAll(".row:not(.rv-removed)").forEach((row) => { const t = row.querySelector(".rvb, .rv-tag"); if (t) kinds[/new/.test(text(t)) ? "new" : "changed"]++; });
  return { errors, head, said: { changed: +m[1], new: +m[2], removed: +m[3] }, tags: kinds };
}

async function unitNeeds() {
  const { w, errors } = boot(); await wait(800);
  const d = w.document, snap = () => {
    const rows = [...d.querySelectorAll(".row")].filter((r) => !r.hidden && r.querySelector(".rowhead") && !r.classList.contains("qgroup") && !r.classList.contains("rv-removed"));
    return { chip: +text(d.querySelector("[data-val=needs] .n, [data-val=needs] b")), rows: rows.length, settled: rows.filter((r) => r.classList.contains("nsettled")).length, done: rows.filter((r) => r.querySelector(".nsdone")).length };
  };
  click(w, d.querySelector("[data-val=needs]")); await wait(100);
  const before = snap();
  click(w, d.querySelector(".row .testpick button, .row .suggestpick button")); await wait(100);
  return { errors, before, after: snap() };
}

async function unitAnswer() {
  const { w, errors } = boot(); await wait(800);
  const d = w.document;
  const pick = d.querySelector(".row .testpick:not(.suggestpick) [data-val=now]"), key = pick.dataset.key;
  click(w, pick); await wait(100);
  const head = d.getElementById(key).querySelector(".rtitle"); click(w, head); await wait(100);
  const ta = d.querySelector('textarea[data-note="' + key + '"]');
  ta.value = "Use the baker's own words."; ta.dispatchEvent(new w.Event("input", { bubbles: true })); await wait(100);
  const ans = d.querySelector("#answer");
  return { errors, times: (text(ans).match(/Use the baker's own words\./g) || []).length, groups: [...ans.querySelectorAll(".ansg")].map((g) => g.dataset.ans) };
}

async function unitChain() {
  const { w, errors } = boot(); await wait(800);
  const d = w.document;
  return { errors, flow: !!d.querySelector(".mapflow"), scroll: !!d.querySelector(".mapscroll"), nodes: d.querySelectorAll(".mapflow .node").length, titles: [...d.querySelectorAll(".mapflow .node b")].map(text), tips: [...d.querySelectorAll(".mapflow .node")].map((n) => n.getAttribute("title")) };
}

async function vizCue() {
  const { w, errors } = boot(); await wait(700);
  const d = w.document, s = d.querySelector(".vz-scroll");
  if (!s) return { errors, found: false };
  Object.defineProperty(s, "scrollWidth", { configurable: true, get: () => 1024 }); Object.defineProperty(s, "clientWidth", { configurable: true, get: () => 900 });
  w.GateViz.cue(d);
  const on = !!(s.nextElementSibling && s.nextElementSibling.classList.contains("vz-cue")), said = text(s.nextElementSibling);
  Object.defineProperty(s, "scrollWidth", { configurable: true, get: () => 800 });
  w.GateViz.cue(d);
  return { errors, found: true, on, said, goneWhenFits: !(s.nextElementSibling && s.nextElementSibling.classList.contains("vz-cue")) };
}

const SCEN = { trace, bar, item, dots, ack, "unit-reads": unitReads, "unit-split": unitSplit, "unit-needs": unitNeeds, "unit-answer": unitAnswer, "unit-chain": unitChain, "viz-cue": vizCue };
SCEN[scenario]().then((r) => { process.stdout.write(JSON.stringify(r)); process.exit(0); }, (e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
