/* Boot the pages dev/preview.py wrote under jsdom, as a browser would from file://: the stub of window.claude is in the file, the
   page's own scripts run, and anything that reaches the console as an error is reported.

     node drive_preview.js <page.html> [<page.html> ...]       prints a JSON list [{file, errors[], text, visuals{}}]

   Needs the jsdom package (NODE_PATH or a local node_modules); marked, dompurify and js-yaml are used when found. */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const optional = (name) => { try { return require(name); } catch { return null; } };

function boot(file, wait) {
  return new Promise((resolve) => {
    const errors = [];
    const vc = new VirtualConsole();
    vc.on("jsdomError", (e) => errors.push("jsdom: " + String((e && e.message) || e).slice(0, 300)));
    vc.on("error", (...a) => errors.push("console.error: " + a.map(String).join(" ").slice(0, 300)));
    const html = fs.readFileSync(file, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
    const dom = new JSDOM(html, {
      runScripts: "dangerously", pretendToBeVisual: true, url: "file://" + path.resolve(file), virtualConsole: vc,
      beforeParse(w) {
        w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
        w.scrollTo = () => {};
        w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
        w.Element.prototype.scrollIntoView = function () {};
        const marked = optional("marked"), purify = optional("dompurify"), yaml = optional("js-yaml");
        if (marked && purify) { w.marked = marked.marked || marked; w.DOMPurify = (purify.default || purify)(w); }
        if (yaml) w.jsyaml = yaml;
        w.addEventListener("error", (e) => errors.push("window: " + String(e.message).slice(0, 300)));
        w.addEventListener("unhandledrejection", (e) => errors.push("rejection: " + String(e.reason && e.reason.message || e.reason).slice(0, 300)));
      },
    });
    setTimeout(() => {
      const d = dom.window.document, count = (sel) => d.querySelectorAll(sel).length;
      resolve({ file: path.basename(file), errors, text: (d.body.textContent || "").replace(/\s+/g, " ").trim().length,
        visuals: { figures: count(".vz"), diagrams: count(".vz-svg"), heat: count(".vz-heat"), funnel: count(".vz-funnel"), timeline: count(".vz-tl"), lanes: count(".vz-lanes"), dots: count(".vz-dots") },
        blocks: count("#col > details.block, #col > section, #app .card"), title: d.title });
      dom.window.close();
    }, wait || 450);
  });
}

(async () => {
  const out = [];
  for (const f of process.argv.slice(2)) out.push(await boot(f));
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})();
