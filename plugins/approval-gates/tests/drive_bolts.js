/* Drive a page dev/preview.py wrote (with the bolt-plan document replaced by a test's own text) under jsdom.

     node drive_bolts.js view  <page.html>                  the bolt view of the document: the strip, the sections, the dots, the links
     node drive_bolts.js plain <pageRound2.html> <pageRound3.html>
                                                             a document with no view of its own: its sections and their dots; read them all in
                                                             round 2, then open round 3 with the same marks and say which sections are unread / changed

   Prints one JSON object. Needs jsdom, marked, dompurify and js-yaml (NODE_PATH). */
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");
const [scenario, fileA, fileB] = process.argv.slice(2);
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function boot(file, marks) {
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
      const marked = require("marked"), purify = require("dompurify"), yaml = require("js-yaml");
      w.marked = marked.marked || marked; w.DOMPurify = (purify.default || purify)(w); w.jsyaml = yaml;
      if (marks) Object.entries(marks).forEach(([k, v]) => w.localStorage.setItem(k, v));
    },
  });
  return { w: dom.window, errors };
}

function secs(block) {
  return [...block.querySelectorAll("details.sec")].map((s) => ({
    title: s.dataset.title, dot: !!s.querySelector(":scope > summary [data-eread]"), read: !!s.querySelector(":scope > summary [data-eread].isread"),
    changed: s.classList.contains("changed"), same: s.classList.contains("rv-same"),
  }));
}

async function view() {
  const { w, errors } = boot(fileA); await wait(900);
  const b = w.document.querySelector("#d-bolt-plan");
  if (!b) return { errors, found: false };
  const strip = [...b.querySelectorAll(".bolts .bolt")].map((x) => ({ title: text(x.querySelector("b")), hint: text(x.querySelector(".hint")) }));
  const refs = {};
  ["B1", "B3", "Bolt 1", "Bolt 3"].forEach((k) => { const e = b.querySelector(`[data-aidlc-id="${k}"]`); refs[k] = e ? (e.dataset.title || e.tagName) : null; });
  const links = [...b.querySelectorAll("a.xref")].map((a) => ({ ref: a.dataset.ref, dead: a.classList.contains("dead"), in: (a.closest("details.sec") || {}).dataset ? a.closest("details.sec").dataset.title : "" }));
  return { errors, found: true, strip, sections: secs(b), dots: b.querySelectorAll("[data-eread]").length, refs, links, facts: b.querySelectorAll("dl.facts dt").length };
}

async function plain() {
  const a = boot(fileA); await wait(900);
  const ba = a.w.document.querySelector("#d-bolt-plan");
  const before = { sections: secs(ba), dots: ba.querySelectorAll("[data-eread]").length, bolts: ba.querySelectorAll(".bolts .bolt").length };
  ba.querySelectorAll("[data-eread]").forEach((dot) => dot.dispatchEvent(new a.w.MouseEvent("click", { bubbles: true, cancelable: true })));
  await wait(200);
  const marks = {}; for (let i = 0; i < a.w.localStorage.length; i++) { const k = a.w.localStorage.key(i); marks[k] = a.w.localStorage.getItem(k); }
  const readInA = secs(ba).filter((s) => s.read).length;
  const b = boot(fileB, marks); await wait(900);
  const bb = b.w.document.querySelector("#d-bolt-plan");
  const after = secs(bb);
  return { errors: a.errors.concat(b.errors), before, readInA, savedMarks: Object.keys(marks).length, after,
    unread: after.filter((s) => !s.read).map((s) => s.title), changed: after.filter((s) => s.changed).map((s) => s.title),
    flatDots: bb.querySelectorAll("[data-eread]").length };
}

(async () => {
  const out = await ({ view, plain }[scenario])();
  process.stdout.write(JSON.stringify(out)); process.exit(0);
})();
