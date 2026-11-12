/* The maps page under jsdom.

     node drive_maps.js <maps.html> <rows.json> <scenario> [hash]

   rows.json: [{id, ...row}] as the `maps` collection holds them. Scenarios print one JSON report:
     index     the list of intents and their maps
     graph     a graph row: blocks, edges, a pick (panel, edges drawn), Show every edge, search, a group chip, keys
     list      the same row at phone width (matchMedia says narrow): the list and the same panel
     revision  the marks of a row that carries a previous revision
     matrix    a matrix row: a dot per cell, gaps, a pick of a row and of a column
   Needs the jsdom package. */
const fs = require("fs");
const { JSDOM } = require("jsdom");
const [pagePath, rowsPath, scenario, hash] = process.argv.slice(2);
const rows = JSON.parse(fs.readFileSync(rowsPath, "utf8"));
const html = fs.readFileSync(pagePath, "utf8").replace(/<script src=[^>]*><\/script>/g, "");
const narrow = scenario === "list";
const dom = new JSDOM("<!doctype html><html><head></head><body>" + html + "</body></html>", {
  runScripts: "outside-only", pretendToBeVisual: true, url: "https://claude.ai/artifact/x" + (hash ? "#" + hash : ""),
});
const w = dom.window;
w.matchMedia = (q) => ({ matches: narrow && /max-width/.test(q), addEventListener() {}, removeEventListener() {} });
w.scrollTo = () => {};
w.CSS = { escape: (v) => String(v).replace(/[^\w-]/g, (c) => "\\" + c) };
w.Element.prototype.scrollIntoView = function () {};
const snap = (id, data) => ({ id, exists: true, data: () => data });
const docs = rows.map((r) => { const { id, ...rest } = r; return snap(id, rest); });
const q = () => { const o = { orderBy: () => o, limit: () => o, where: () => o, onSnapshot: (cb) => { setTimeout(() => cb({ docs })); return () => {}; } }; return o; };
w.claude = { use: async (what) => (what === "db" ? { collection: () => q() } : { id: async () => "viewer" }) };
for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) w.eval(m[1]);
const d = w.document, $ = (s) => d.querySelector(s), all = (s) => [...d.querySelectorAll(s)];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");
const click = (n) => n.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));
const key = (k, target) => (target || d).dispatchEvent(new w.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
const edges = () => all("#map-canvas .edge.on").map((e) => e.dataset.from + ">" + e.dataset.to);
(async () => {
  await wait(300);
  const out = { title: d.title };
  if (scenario === "index") {
    out.rows = all(".irow").map((a) => ({ href: a.getAttribute("href"), text: text(a) }));
    out.heads = all(".idx h2").map(text);
  } else if (scenario === "graph" || scenario === "list") {
    out.bar = { tabs: all("[data-kind-tab]").map(text), current: text($('[data-kind-tab][aria-current="page"]')), stats: text($("#map-stats")), chips: all("[data-group-chip]").map(text), views: all("[data-view]").map((b) => b.dataset.view + ":" + b.getAttribute("aria-pressed")) };
    out.blocks = all("[data-block]").length;
    out.edgesTotal = all("#map-canvas .edge").length;
    out.edgesOn0 = edges();
    out.cols = all("[data-layer-label]").map(text);
    out.panel0 = text($("#map-panel"));
    const first = all("[data-block]")[Number(process.env.PICK || 0)];
    const id = process.env.PICK_ID || first.dataset.block;
    click($('[data-block="' + id + '"]'));
    out.picked = id;
    out.hash = w.location.hash;
    await wait(60);
    out.panelLinks = all("#map-panel a.aidlc-id, #map-panel-inline a.aidlc-id").map((a) => a.textContent + "|" + (a.dataset.tip || ""));
    out.panel1 = text($("#map-panel") || $("#map-panel-inline"));
    out.edgesOn1 = edges();
    out.sel = all("[data-block].sel, .lrow.sel").map((n) => n.dataset.block);
    out.dep = all(".node.dep").map((n) => n.dataset.block);
    out.user = all(".node.user").map((n) => n.dataset.block);
    out.tabindex = all(".node").every((n) => n.getAttribute("tabindex") === "0");
    out.roles = all(".node").every((n) => n.getAttribute("role") === "button");
    /* the panel's own links walk to a neighbour */
    const go = $("#map-panel [data-go], #map-panel-inline [data-go]");
    if (go) { const to = go.dataset.go; click(go); out.went = { to, sel: all("[data-block].sel, .lrow.sel").map((n) => n.dataset.block) }; }
    click($('[data-act="edges"]'));
    out.allEdges = { pressed: $('[data-act="edges"]') && $('[data-act="edges"]').getAttribute("aria-pressed"), canvasAll: !!$("#map-canvas.all") };
    key("Escape");  /* the pick is cleared: what dims now is the search */
    out.escCleared = all("[data-block].sel, .lrow.sel").length === 0;
    const search = $("#map-search");
    search.value = process.env.SEARCH || "zzzz-nothing"; search.dispatchEvent(new w.Event("input", { bubbles: true }));
    out.dimmed = all("[data-block].dim").length;
    out.search = $("#map-search").value;
    search.value = ""; $("#map-search").dispatchEvent(new w.Event("input", { bubbles: true }));
    const chip = $("[data-group-chip]");
    if (chip) { click(chip); out.offAfterChip = all("[data-block].off").length; out.chipPressed = $("[data-group-chip]").getAttribute("aria-pressed"); click($("[data-group-chip]")); }
    /* the keyboard */
    const nodes = all(".node");
    if (nodes.length) { nodes[0].focus(); key("ArrowRight", nodes[0]); out.arrowFocus = d.activeElement && d.activeElement.dataset.block; key("Enter", d.activeElement); out.enterSel = all("[data-block].sel").map((n) => n.dataset.block); key("Escape"); out.escSel = all("[data-block].sel").length; }
    out.links = all("a.aidlc-id").length;
    out.firstTip = (all("a.aidlc-id")[0] || { dataset: {} }).dataset.tip || "";
    out.listRows = all(".lrow").length;
    out.lists = all("#map-canvas[data-map-view='list'] > h2").map(text);
    click($('[data-view="graph"]')); out.afterGraphToggle = !!$("#map-canvas .plane");
  } else if (scenario === "revision") {
    out.changes = text($("#map-changes"));
    out.tags = all("[data-block]").filter((n) => n.dataset.change).map((n) => n.dataset.block + ":" + n.dataset.change);
    out.landedNodes = all("[data-block].landed").map((n) => n.dataset.block);
    out.ghosts = all("#map-changes .ghost").map((n) => n.dataset.removed);
    out.tagTexts = all(".node .rv-tag").map(text);
    const target = process.env.PICK_ID;
    if (target) { click($('[data-block="' + target + '"]')); out.panel = text($("#map-panel")); out.chgLines = all("#map-panel .chg").map(text); }
    if (target) click($('[data-block="' + target + '"]'));
    if ($('[data-act="changes"]')) { click($('[data-act="changes"]')); out.onlyChanges = all("[data-block].dim").length; }
  } else if (scenario === "matrix") {
    out.rows = all("[data-row]").filter((b) => b.closest("th")).map((b) => b.dataset.row);
    out.cols = all("th.ch [data-col]").map((b) => b.dataset.col);
    out.dots = all("td.on").length;
    out.gaps = all("tr.gap").map((t) => t.dataset.rowLine);
    out.stats = text($("#map-stats"));
    click($('[data-row="' + process.env.PICK_ID + '"]'));
    out.rowPanel = text($("#map-panel"));
    click($('th.ch [data-col="' + process.env.PICK_COL + '"]'));
    out.colPanel = text($("#map-panel"));
    out.fresh = all("td.rv-new").length;
    click($('[data-act="gaps"]'));
    out.gapRowsOnly = all("tr[data-row-line]").map((t) => t.dataset.rowLine);
    out.hash = w.location.hash;
  }
  out.errors = [];
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); process.exit(0); });
