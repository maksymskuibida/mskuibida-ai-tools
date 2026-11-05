/* Shared by render_gate_page.js and drive_gate_page.js: boot approval-gate.html under jsdom with a stand-in for the artifact's db
   holding one gate.  boot(pagePath, sample) -> {w, writes}; the page has run its scripts, the db answers after a tick. */
const fs = require("fs");
const { JSDOM } = require("jsdom");
const optional = (name) => { try { return require(name); } catch { return null; } };

function boot(pagePath, sample) {
  const html = fs.readFileSync(pagePath, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
  const dom = new JSDOM("<!doctype html><html><head></head><body>" + html + "</body></html>", {
    runScripts: "outside-only", pretendToBeVisual: true, url: "https://claude.ai/artifact/x#" + sample.id,
  });
  const w = dom.window;
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.scrollTo = () => {};
  w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
  w.Element.prototype.scrollIntoView = function () {};
  const marked = optional("marked"), purify = optional("dompurify"), yaml = optional("js-yaml");
  if (marked && purify) { w.marked = marked.marked || marked; w.DOMPurify = (purify.default || purify)(w); }
  if (yaml) w.jsyaml = yaml;

  const writes = [];
  const snap = (id, data) => ({ id, exists: data !== undefined, data: () => data });
  const query = (docs) => {
    const q = { orderBy: () => q, limit: () => q, where: () => q,
      onSnapshot: (cb) => { setTimeout(() => cb({ empty: !docs.length, docs: docs.map(([id, d]) => snap(id, d)) })); return () => {}; },
      get: async () => ({ empty: !docs.length, docs: docs.map(([id, d]) => snap(id, d)) }),
      doc: (id) => ({ get: async () => snap(id, undefined), set: async (v) => { writes.push(v); } }) };
    return q;
  };
  const db = {
    collection: (name) => query(name === "gates" ? [[sample.id, sample.row]] : []),
    doc: (path) => ({
      onSnapshot: (cb) => { setTimeout(() => cb(snap(sample.id, sample.row))); return () => {}; },
      collection: () => query(Object.entries(sample.documents)),
      update: async (v) => { writes.push(v); },
    }),
  };
  w.claude = { use: async (what) => (what === "db" ? db : { id: async () => "viewer" }) };

  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) w.eval(m[1]);
  return { w, writes, html };
}
module.exports = { boot };
