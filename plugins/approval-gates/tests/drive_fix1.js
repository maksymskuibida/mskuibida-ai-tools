/* Drive the pages dev/preview.py wrote under jsdom and report what fix round 1 of the pages does.

     node drive_fix1.js <scenario> <page.html> [<localStorage json>]      prints one JSON object

   scenarios: bar (the sticky bar of a per-stage or a Unit page: rows, controls, menus), clean (round marks in Clean and in Changes),
              switch (Text / View / Diagram keeps every block open and the read totals), ack (what is handled nowhere stays in Needs you
              until acknowledged), cards (each card of the evaluation has its own read mark), shell (no empty items block), unit (a Unit
              page: Summary first, Changed with steps and removed rows, a note updates Your answer, ids, list), plan (the test plan) */
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");
const optional = (name) => { try { return require(name); } catch { return null; } };
const [scenario, file, storage] = process.argv.slice(2);

function boot(pre) {
  const errors = [], calls = { scrollIntoView: 0, scrollTo: 0 };
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String((e && e.message) || e)));
  vc.on("error", (...a) => errors.push(a.map(String).join(" ")));
  const html = fs.readFileSync(file, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, url: "https://claude.ai/artifact/x", virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
      w.scrollTo = () => { calls.scrollTo++; };
      w.scrollBy = () => {};
      w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
      w.Element.prototype.scrollIntoView = function () { calls.scrollIntoView++; };
      const marked = optional("marked"), purify = optional("dompurify"), yaml = optional("js-yaml");
      if (marked && purify) { w.marked = marked.marked || marked; w.DOMPurify = (purify.default || purify)(w); }
      if (yaml) w.jsyaml = yaml;
      try { Object.entries(JSON.parse(pre || "{}")).forEach(([k, v]) => w.localStorage.setItem(k, v)); } catch (e) { /* none */ }
    },
  });
  return { w: dom.window, errors, calls };
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const click = (w, n) => n.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");

async function bar() {
  const { w, errors } = boot(storage); await wait(600);
  const d = w.document, bar = d.querySelector("#bar"), all = (s, r) => [...(r || d).querySelectorAll(s)];
  const rows = all(":scope > .barrow", bar);
  const inPop = (n) => !!n.closest(".bpop");
  const controls = all("button, a, select, input", bar).filter((n) => !inPop(n));
  return { errors, barClass: bar.className, rows: rows.length, children: [...rows[0].children].map((c) => c.className.split(" ")[0]),
    controls: controls.length, controlTexts: controls.map(text),
    popMenus: all(".bpop", bar).map((p) => ({ id: p.id, hidden: p.hidden, buttons: all("button", p).map(text) })),
    chipsOutsidePopovers: all(".jchip, nav.chips", bar).filter((n) => !inPop(n)).length,
    readCounter: !!d.querySelector(".progress-r, .progress"), hasReady: !!bar.querySelector("#ready"),
    pills: all("[data-filter], [data-act=filter]", bar).filter((n) => !inPop(n)).map((n) => (n.firstChild && n.firstChild.textContent) || ""),
    titles: controls.filter((n) => !n.getAttribute("data-tip") && !n.getAttribute("title") && !text(n)).length };
}

async function clean() {
  const { w, errors } = boot(Object.assign({}, JSON.parse(storage || "{}"))); await wait(700);
  const d = w.document, col = d.querySelector("#col"), all = (s) => [...d.querySelectorAll(s)];
  const out = { errors, rv: col.dataset.rv, banner: text(d.querySelector("#revs")), pill: text(d.querySelector('[data-filter="changed"]')) };
  out.tags = all("#col .rv-tag").filter((n) => !n.closest("#b-revision")).map(text);
  out.removed = all("#col .rv-removed, #col .rv-gone").length;
  out.roundClass = [...col.classList].filter((c) => /^rv-t\d$/.test(c));
  click(w, d.querySelector('[data-filter="changed"]')); await wait(100);
  out.itemsBlockHidden = (d.querySelector("#b-items") || {}).hidden;
  out.removedUnderChanged = all("#b-items .rv-removed").length;
  out.hiddenBlocksWithChanges = ["b-items", "b-bt-matrix", "b-records"].filter((id) => d.getElementById(id) && d.getElementById(id).hidden).length;
  out.timelineInBar = !!d.querySelector("#bar #rvlegend");
  out.dates = text(d.querySelector("#revs"));
  return out;
}

async function switchView() {
  const { w, errors } = boot(storage); await wait(700);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  d.querySelector("#b-records").open = true;
  const doc = all("#b-records details.block.doc").find((b) => b.querySelector('.seg [data-mode="diagram"]:not([hidden])'));
  if (!doc) return { errors, skipped: true };
  doc.open = true;
  const unread = () => d.querySelector("#ready").dataset.unread;
  const dots = () => all("[data-eread]").length;
  const before = { unread: unread(), dots: dots(), recOpen: d.querySelector("#b-records").open, docOpen: doc.open };
  const scroll0 = w.__scrolls = 0;
  click(w, doc.querySelector('.seg [data-mode="diagram"]')); await wait(100);
  const doc2 = d.getElementById(doc.id);
  const after = { unread: unread(), dots: dots(), recOpen: d.querySelector("#b-records").open, docOpen: doc2.open, diagram: doc2.querySelectorAll(".vz").length, underHidden: doc2.querySelectorAll(".vzunder[hidden]").length };
  click(w, doc2.querySelector('.seg [data-mode="view"]:not([hidden]), .seg [data-mode="text"]')); await wait(100);
  const doc3 = d.getElementById(doc.id);
  const back = { unread: unread(), dots: dots(), recOpen: d.querySelector("#b-records").open, docOpen: doc3.open };
  return { errors, before, after, back };
}

async function ack() {
  const { w, errors } = boot(storage); await wait(700);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  const ready = () => ({ text: text(d.querySelector("#ready")), decisions: +d.querySelector("#ready").dataset.decisions, looks: +d.querySelector("#ready").dataset.looks, unread: +d.querySelector("#ready").dataset.unread });
  const needs = () => text(d.querySelector('[data-filter="needs"]'));
  const out = { errors, start: ready(), needsStart: needs(), ackButtons: all("[data-ack]").length };
  click(w, d.querySelector("[data-allread]") || d.querySelector('[data-menu="view"]'));
  if (!d.querySelector("[data-allread]")) await wait(50);
  click(w, d.querySelector("[data-allread]")); await wait(100);
  out.afterRead = ready(); out.needsAfterRead = needs(); out.readyOk = !!d.querySelector(".rdy.ok");
  const first = d.querySelector("[data-ack]");
  if (first) { click(w, first); await wait(100); }
  out.afterOneAck = ready(); out.ackButtonsAfter = all("[data-ack]").length;
  all("[data-ack]").forEach((b) => click(w, b)); await wait(100);
  out.afterAllAck = ready(); out.readyOkAfterAll = !!d.querySelector(".rdy.ok");
  return out;
}

async function cards() {
  const { w, errors } = boot(storage); await wait(700);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  const cardsEls = all("#b-eval li[data-item]");
  const out = { errors, cards: cardsEls.length, withDot: cardsEls.filter((c) => c.querySelector("[data-iread]")).length, keys: new Set(cardsEls.map((c) => c.dataset.item)).size,
    lookFirst: all("#b-eval ol.lfl > li[data-item]").length, lf: text(d.querySelector("#lf-count")), labels: all("#b-eval li[data-item] [data-iread]").map((b) => b.getAttribute("aria-label")).slice(0, 3) };
  const lf = d.querySelector("#b-eval ol.lfl > li[data-item] [data-iread]");
  if (lf) { const total0 = d.querySelector("#ready").dataset.unread; click(w, lf); await wait(100); out.lfAfter = text(d.querySelector("#lf-count")); out.lfHidden = d.querySelector("#lf-count").hidden; out.unreadDelta = +total0 - +d.querySelector("#ready").dataset.unread; }
  return out;
}

async function shell() {
  const { w, errors } = boot(storage); await wait(700);
  const d = w.document;
  const items = d.querySelector("#b-items");
  return { errors, hasItems: !!items, head: items ? text(items.querySelector("summary")) : "", rows: d.querySelectorAll("#b-items .irow").length, trace: !!d.querySelector('#b-eval details.settled[data-settled="trace"]'),
    ids: [...d.querySelectorAll("#b-items .irow .iid")].map(text), storys: /storys/.test(d.querySelector("#col").textContent), emptyDots: [...d.querySelectorAll("details.block")].filter((b) => b.querySelector(":scope > summary .rdot") && !b.querySelector(":scope > .body").children.length).length };
}

async function unit() {
  const { w, errors } = boot(storage); await wait(800);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  const out = { errors, openRows: all(".row .rowbody").length, textareas: all("textarea").length, picksInHead: all(".rowhead [data-act=pick]").length, modeSummary: d.querySelector('[data-act=mode][data-val=summary]').getAttribute("aria-pressed") };
  out.banner = text(d.querySelector(".revs"));
  out.pillChanged = text(d.querySelector('[data-act=filter][data-val=changed]'));
  out.designIdLinks = all(".drows a.aidlc-id").length;
  out.designRowIds = all(".drows .drow").map((r) => r.id).slice(0, 3);
  out.facts = all(".facts .fact").map(text);
  const f = d.querySelector('[data-act=filter][data-val=changed]');
  if (f) {
    click(w, f); await wait(100);
    out.changed = { secs: all("section[data-sec]").map((s) => [s.dataset.sec, s.querySelectorAll(".row:not(.rv-removed)").length, s.querySelectorAll(".row.rv-removed").length]), steps: all("#plan .row.step").length, tags: all(".rowhead .rvb, .rowhead .rv-tag").length };
  }
  // a note written into a row updates Your answer at once
  click(w, d.querySelector('[data-act=filter][data-val=all]')); await wait(50);
  const first = d.querySelector('.row .rtitle'); if (first) { click(w, first); await wait(50); }
  const ta = d.querySelector("textarea[data-note]");
  if (ta) { ta.value = "Please use the baker's own words."; ta.dispatchEvent(new w.Event("input", { bubbles: true })); await wait(50); out.answerAfterNote = text(d.querySelector("#answer")); }
  return out;
}

async function plan() {
  const { w, errors, calls } = boot(storage); await wait(700);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  return { errors, scrolls: calls.scrollIntoView, pbar: !!d.querySelector("#pbar"), progress: text(d.querySelector("#pbar .meter b")), next: !!d.querySelector("[data-next]"), crumbsLink: !!d.querySelector(".crumbs a[data-nav]"), status: text(d.querySelector(".status")), band: !!d.querySelector("footer.band") };
}

async function list() {
  const { w, errors } = boot(storage); await wait(700);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  return { errors, rows: all(".lrow").map((r) => ({ old: r.classList.contains("old"), text: text(r) })) };
}

async function heat() {
  const { w, errors } = boot(storage); await wait(800);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  const rows = () => all("#bt-tm .tm-row").length, showing = () => text(d.querySelector("#bt-tm .tm-showing"));
  const cell = d.querySelector("#bt-heat [data-vz-set]");
  const out = { errors, rows0: rows(), showing0: showing(), hasCell: !!cell };
  if (cell) {
    click(w, cell); await wait(80); out.rows1 = rows(); out.showing1 = showing();
    click(w, d.querySelector(`#bt-heat [data-vz-set="${cell.dataset.vzSet}"]`)); await wait(80); out.rows2 = rows(); out.showing2 = showing();
    click(w, d.querySelector("#bt-heat [data-vz-set]")); await wait(80);
    const clear = d.querySelector("[data-btclear]"); out.clearButton = !!clear; if (clear) { click(w, clear); await wait(80); out.rows3 = rows(); out.showing3 = showing(); }
  }
  return out;
}

async function reject() {
  const { w, errors } = boot(storage); await wait(800);
  const d = w.document;
  const card = d.querySelector(".fcard");
  const btn = card && [...card.querySelectorAll("button")].find((b) => /^Reject/.test(b.textContent.trim()));
  const out = { errors, hasReject: !!btn };
  if (btn) { click(w, btn); await wait(100); out.answer = text(d.querySelector("#b-answer")); out.sorted = text(d.querySelector("#f-dcount")); }
  return out;
}

async function tips() {
  const { w, errors } = boot(storage); await wait(800);
  const d = w.document, all = (s) => [...d.querySelectorAll(s)];
  const tipText = all("a.aidlc-id").map((a) => a.dataset.tip || a.title || "");
  return { errors, links: tipText.length, rawTables: tipText.filter((t) => /\|\s*:?-{2,}/.test(t)).length,
    rawKeys: all("#rv-list .rvt").map(text).filter((t) => /#[a-z0-9]+\.\d+/.test(t)).length,
    ariaRaw: all("[aria-label]").map((n) => n.getAttribute("aria-label")).filter((l) => /^Mark (un)?read: (crit|item|finding|el|target|eval|evc):/.test(l)).length,
    dots: all("[data-iread], [data-eread]").length, ledger: all("#rv-list .rvt").map(text).filter((t) => /NFR/.test(t)).slice(0, 6) };
}

({ bar, clean, heat, reject, tips, switch: switchView, ack, cards, shell, unit, plan, list }[scenario])().then((o) => { process.stdout.write(JSON.stringify(o)); process.exit(0); }).catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
