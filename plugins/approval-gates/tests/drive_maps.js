/* The maps page under jsdom.

     node drive_maps.js <maps.html> <rows.json> <scenario> [hash]

   rows.json: [{id, ...row}] as the `maps` collection holds them. Scenarios print one JSON report:
     index     the list of intents and their maps
     graph     a graph row: blocks, the Fit view, a pick (panel, edges drawn, landed marks), search, a group chip, keys, one tab stop
     list      the same row at phone width (matchMedia says narrow): the list and the same panel
     ready     the Ready marks and the Ready now chip
     zoom      Fit and Comfortable
     bar       what the sticky tools row holds and what scrolls away
     revision  the marks of a row that carries a previous round
     matrix    a matrix row: the grouped list first, Gaps only, the matrix view, the picks, Only changes, the legend
   Needs the jsdom package. Env: PICK_ID, PICK_COL, SEARCH, AVAIL (the width the layout may use; the page measures it, jsdom cannot). */
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
if (process.env.AVAIL) w.MAPS_AVAIL = Number(process.env.AVAIL);
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
const px = (n, k) => parseFloat(n.style[k]);
(async () => {
  await wait(300);
  const out = { title: d.title };
  if (scenario === "index") {
    out.rows = all(".irow").map((a) => ({ href: a.getAttribute("href"), text: text(a) }));
    out.heads = all(".idx h2").map(text);
  } else if (scenario === "graph" || scenario === "list") {
    out.bar = { tabs: all("[data-kind-tab]").map(text), current: text($('[data-kind-tab][aria-current="page"]')), stats: text($("#map-stats")), chips: all("[data-group-chip]").map(text), views: all("[data-view]").map((b) => b.dataset.view + ":" + b.getAttribute("aria-pressed")), zooms: all("[data-zoom]").map((b) => b.dataset.zoom + ":" + b.getAttribute("aria-pressed")), edgesToggle: !!$('[data-act="edges"]') };
    out.blocks = all("[data-block]").length;
    out.edgesTotal = all("#map-canvas .edge").length;
    out.edgesOn0 = edges();
    out.cols = all("[data-layer-label]").map(text);
    out.fit = { canvas: $("#map-canvas") && $("#map-canvas").className, compact: all(".node.cmp").length, labels: all("[data-layer-label]").length, summaryLines: all(".node .n2").length };
    if (all(".node").length) {
      const ns = all(".node"), maxX = Math.max(...ns.map((n) => px(n, "left") + px(n, "width")));
      out.fit.planeWidth = px($(".plane"), "width"); out.fit.maxRight = maxX; out.fit.bands = new Set(ns.map((n) => px(n, "top") > 0 && px(n, "top"))).size;
      /* two cards never share the same place */
      const seen = new Set(); out.fit.overlap = 0; ns.forEach((n) => { const k = px(n, "left") + "," + px(n, "top"); if (seen.has(k)) out.fit.overlap++; seen.add(k); });
    }
    out.tabStops = all(".node[tabindex='0']").length;
    out.cardIdLinks = all(".node a, .lrow a").length;
    out.panel0 = text($("#map-panel"));
    out.rail0 = !!$("#map-panel.rail");
    const first = all("[data-block]")[Number(process.env.PICK || 0)];
    const id = process.env.PICK_ID || first.dataset.block;
    click($('[data-block="' + id + '"]'));
    out.picked = id;
    out.hash = w.location.hash;
    await wait(60);
    out.railAfter = !!$("#map-panel.rail");
    out.panelLinks = all("#map-panel a.aidlc-id, #map-panel-inline a.aidlc-id").map((a) => a.textContent + "|" + (a.dataset.tip || ""));
    out.panel1 = text($("#map-panel") || $("#map-panel-inline"));
    out.verdict = text($("#map-panel .verdict, #map-panel-inline .verdict"));
    out.needMarks = all("#map-panel .need .sm, #map-panel-inline .need .sm").map((n) => n.className.replace("sm ", ""));
    out.waitMarks = all("#map-panel .links .lnk.in .sm, #map-panel-inline .links .lnk.in .sm").map((n) => n.className.replace("sm ", ""));
    out.needsLandedLine = text($("#map-panel [data-needs-landed], #map-panel-inline [data-needs-landed]"));
    out.edgesOn1 = edges();
    out.edgeShapes = all("#map-canvas .edge.on").map((e) => /^M[\d.,-]+( L[\d.,-]+| Q[\d.,-]+ [\d.,-]+)+$/.test(e.getAttribute("d")));
    out.sel = all("[data-block].sel, .lrow.sel").map((n) => n.dataset.block);
    out.dep = all(".node.dep").map((n) => n.dataset.block);
    out.user = all(".node.user").map((n) => n.dataset.block);
    out.tabindex = all(".node").length === 0 || all(".node[tabindex]").length === all(".node").length;
    out.roles = all(".node").every((n) => n.getAttribute("role") === "button");
    /* the panel's own links walk to a neighbour */
    const go = $("#map-panel [data-go], #map-panel-inline [data-go]");
    if (go) { const to = go.dataset.go; click(go); out.went = { to, sel: all("[data-block].sel, .lrow.sel").map((n) => n.dataset.block) }; }
    key("Escape");
    out.escCleared = all("[data-block].sel, .lrow.sel").length === 0;
    /* a search and a pick do not fight: typing lets the pick go */
    click($('[data-block="' + id + '"]'));
    const search = $("#map-search");
    search.value = process.env.SEARCH || "zzzz-nothing"; search.dispatchEvent(new w.Event("input", { bubbles: true }));
    out.pickAfterSearch = all("[data-block].sel, .lrow.sel").length;
    out.dimmed = all("[data-block].dim").length;
    out.search = $("#map-search").value;
    search.value = ""; $("#map-search").dispatchEvent(new w.Event("input", { bubbles: true }));
    const chip = $("[data-group-chip]");
    if (chip) { click(chip); out.offAfterChip = all("[data-block].off").length; out.chipPressed = $("[data-group-chip]").getAttribute("aria-pressed"); click($("[data-group-chip]")); }
    /* the keyboard */
    const nodes = all(".node");
    if (nodes.length) { nodes[0].focus(); key("ArrowRight", nodes[0]); out.arrowFocus = d.activeElement && d.activeElement.dataset.block; out.tabStopsAfterArrow = all(".node[tabindex='0']").length; key("Enter", d.activeElement); out.enterSel = all("[data-block].sel").map((n) => n.dataset.block); key("Escape"); out.escSel = all("[data-block].sel").length; }
    /* nothing picked: pointing at a block previews its edges */
    if (nodes.length) { const n = all(".node")[Number(process.env.PICK || 0)]; n.dispatchEvent(new w.MouseEvent("mouseover", { bubbles: true })); out.previewEdges = all("#map-canvas .hv .edge").length; n.dispatchEvent(new w.MouseEvent("mouseout", { bubbles: true })); out.previewGone = all("#map-canvas .hv .edge").length; }
    out.links = all("a.aidlc-id").length;
    out.firstTip = (all("a.aidlc-id")[0] || { dataset: {} }).dataset.tip || "";
    out.listRows = all(".lrow").length;
    out.lists = all("#map-canvas[data-map-view='list'] > h2").map(text);
    out.legend = { hiddenAtFirst: $("#map-legend").hidden, button: !!$('[data-act="legend"]') };
    click($('[data-act="legend"]')); out.legend.shown = !$("#map-legend").hidden; out.legend.text = text($("#map-legend"));
    click($('[data-act="legend"]'));
    if ($('[data-view="graph"]')) { click($('[data-view="graph"]')); out.afterGraphToggle = !!$("#map-canvas .plane"); }
  } else if (scenario === "ready") {
    out.stats = text($("#map-stats"));
    out.chip = text($('[data-act="ready"]'));
    out.readyNodes = all(".node[data-ready='1']").map((n) => n.dataset.block);
    out.readyTags = all(".node .tag.rdy").length;
    out.readyOnLanded = all(".node.landed .tag.rdy, .node.landed[data-ready]").length;
    out.readyOnBuilding = all(".node.building[data-ready]").length;
    click($('[data-act="ready"]'));
    out.pressed = $('[data-act="ready"]').getAttribute("aria-pressed");
    out.dimmedWhenOn = all(".node.dim").length;
    out.litWhenOn = all(".node:not(.dim)").map((n) => n.dataset.block);
    click($('[data-act="ready"]'));
    out.dimmedWhenOff = all(".node.dim").length;
    out.noReadyChipWithoutStatus = !!$('[data-act="ready"]');
  } else if (scenario === "zoom") {
    out.zoom0 = $("#map-canvas").dataset.zoomNow;
    out.cmp0 = all(".node.cmp").length; out.width0 = px($(".plane"), "width");
    click($('[data-zoom="comfy"]'));
    out.zoom1 = $("#map-canvas").dataset.zoomNow;
    out.cmp1 = all(".node.cmp").length; out.width1 = px($(".plane"), "width"); out.n2 = all(".node .n2").length;
    click($('[data-zoom="fit"]'));
    out.zoom2 = $("#map-canvas").dataset.zoomNow;
  } else if (scenario === "bar") {
    const bar = $("#map-bar"), head = $("#map-head");
    out.barKids = bar ? [...bar.children].map((c) => c.id || c.className || c.tagName).slice(0, 20) : null;
    out.headHasTitle = !!head.querySelector("h1"); out.headHasStats = !!head.querySelector("#map-stats");
    out.barHasTitle = !!bar.querySelector("h1"); out.barHasStats = !!bar.querySelector("#map-stats");
    out.barHasTabs = bar.querySelectorAll("[data-kind-tab]").length; out.barHasSearch = !!bar.querySelector("#map-search");
    out.barPrecededByHead = bar.previousElementSibling === head;
    out.untitled = [...bar.querySelectorAll("button, input, a, [role=group]")].filter((c) => !(c.getAttribute("title") || c.getAttribute("aria-label") || (c.textContent || "").trim())).length;
    out.noTitleButtons = [...bar.querySelectorAll("button:not([data-group-chip]), input")].filter((c) => !c.getAttribute("title")).map((c) => c.textContent.trim() || c.id);
    out.controls = bar.querySelectorAll("button, input, a").length;
    out.stickyCss = /#map-bar \{ position: sticky/.test(html) && !/#map-head \{[^}]*sticky/.test(html);
  } else if (scenario === "revision") {
    out.changes = text($("#map-changes"));
    out.tags = all("[data-block]").filter((n) => n.dataset.change).map((n) => n.dataset.block + ":" + n.dataset.change);
    out.landedNodes = all("[data-block].landed").map((n) => n.dataset.block);
    out.ghosts = all("#map-changes .ghost").map((n) => n.dataset.removed);
    out.tagTexts = all(".node .tag.rtag").map(text);
    out.roundClass = $("#app > div").className;
    const target = process.env.PICK_ID;
    if (target) { click($('[data-block="' + target + '"]')); out.panel = text($("#map-panel")); out.chgLines = all("#map-panel .cl").map(text); }
    if (target) click($('[data-block="' + target + '"]'));
    if ($('[data-act="changes"]')) { click($('[data-act="changes"]')); out.onlyChanges = all("[data-block].dim").length; }
  } else if (scenario === "matrix") {
    out.stats = text($("#map-stats"));
    out.defaultView = $("#map-canvas").dataset.mapView;
    out.listRows = all(".mrow").map((r) => r.dataset.rowLine);
    out.listHeads = all("#map-canvas > h2").map(text);
    out.noGapsLine = text($("[data-nogaps]"));
    out.gapsChip = text($('[data-act="gaps"]')); out.gapsDisabled = !!$('[data-act="gaps"]').disabled;
    out.chipsOfFirst = all(".mrow")[0] ? all(".mrow")[0].querySelectorAll(".lchips .lnk").length : 0;
    out.offered = !!$('[data-mview="matrix"]');
    click($('[data-act="gaps"]'));
    out.gapRowsOnly = all(".mrow").map((t) => t.dataset.rowLine);
    if (!$('[data-act="gaps"]').disabled) click($('[data-act="gaps"]'));
    out.legendInBar = !!$('[data-act="legend"]');
    if (out.offered) {
      click($('[data-mview="matrix"]'));
      out.rows = all("[data-row]").filter((b) => b.closest("th")).map((b) => b.dataset.row);
      out.cols = all("th.ch [data-col]").map((b) => b.dataset.col);
      out.dots = all("td.on").length;
      out.gaps = all("tr.gap").map((t) => t.dataset.rowLine);
      out.matrixLegend = text($("#map-mleg"));
      out.fresh = all("td.is-new").length;
      click($('[data-row="' + process.env.PICK_ID + '"]'));
      out.rowPanel = text($("#map-panel"));
      click($('th.ch [data-col="' + process.env.PICK_COL + '"]'));
      out.colPanel = text($("#map-panel"));
      out.hash = w.location.hash;
      click($('[data-act="gaps"]'));
      out.gapRowsMatrix = all("tr[data-row-line]").map((t) => t.dataset.rowLine);
      if (!$('[data-act="gaps"]').disabled) click($('[data-act="gaps"]'));
      if ($('[data-act="changes"]')) {
        click($('[data-act="changes"]'));
        out.changedRows = all("tr[data-row-line]").map((t) => t.dataset.rowLine);
        out.changedCols = all("th.ch [data-col]").map((b) => b.dataset.col);
        out.droppedCells = all("td.gone").length;
        out.freshChanged = all("td.is-new").length;
        click($('[data-act="changes"]'));
      }
      click($('[data-mview="list"]'));
      out.backToList = $("#map-canvas").dataset.mapView;
    }
    if ($('[data-act="changes"]')) {
      click($('[data-act="changes"]'));
      out.changedListRows = all(".mrow").map((r) => r.dataset.rowLine);
      out.revisionStrip = text($("#map-changes"));
      click($('[data-act="changes"]'));
    }
    out.revisionStripOff = text($("#map-changes"));
  }
  out.pageText = text(d.body);
  out.errors = [];
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); process.exit(0); });
