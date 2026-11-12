/* The visuals of the AI-DLC gate pages: second views of data a page already has, drawn as inline SVG or HTML, every colour a
   token of the page. Shared: the canonical copy is shared/gate-viz/gate-viz.js in mskuibida-ai-tools, copied into every page
   that draws them by scripts/sync-shared.py. Edit it there.

   Every function returns an HTML string (no DOM needed, so a test can run it under Node); GateViz.bind(root, fn) adds the
   hover highlight. A mark that stands for something on the page carries data-vz-go="<id>" (an id, a row key) and the page
   decides where it goes; a mark that stands for a filter carries data-vz-set="<name>:<value>". Each figure has an
   aria-label and a visually hidden list of what it shows: the text it stands for stays one click away on the page.

     GateViz.diagram(d, opts)    a record's diagram from the gate row's `diagrams` (trace, layers, sequence, states, steps, flow,
                                 list); opts.prev is the same diagram of the round compared with, opts.maps the row's maps
     GateViz.heat(m)             targets: Units across, groups down, a cell coloured by its worst verdict
     GateViz.funnel(f)           the verification points: one stacked bar
     GateViz.timeline(rounds)    v1 .. vN with what each round changed, added and removed
     GateViz.lanes(steps)        plan steps grouped by layer, in order
     GateViz.dots(groups)        one dot per criterion, coloured by verdict
     GateViz.outline(items)      a file's headings as a side list and a collapsible strip */
var GateViz = (function () {
  "use strict";
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function clip(s, n) { s = String(s == null ? "" : s).replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function tw(s, px) { return String(s).length * (px || 6.6); }  /* text width, close enough for the sizes drawn */
  function figure(kind, d, inner, extra) {
    var alt = d.alt || d.title || "Diagram";
    return '<figure class="vz vz-' + kind + '" data-aidlc-noids role="group" aria-label="' + esc(alt) + '" data-vz="' + esc(d.id || kind) + '">' +
      (d.title && !extra.noTitle ? '<figcaption class="vz-title">' + esc(d.title) + (extra.hint ? '<span class="hint">' + esc(extra.hint) + "</span>" : "") + "</figcaption>" : "") +
      '<div class="vz-scroll" tabindex="0" role="region" aria-label="' + esc((d.title || "Diagram") + ", scrolls sideways") + '">' + inner + "</div>" +
      (extra.after || "") + '<ul class="vz-sr">' + (extra.alt || []).map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul></figure>";
  }

  /* ---------- what a diagram holds, as keys: a mark new since the round compared with, a mark gone ---------- */
  function keysOf(d) {
    var out = [];
    if (!d) return out;
    if (d.kind === "trace") (d.nodes || []).forEach(function (n) { out.push([n.id, n.id]); });
    else if (d.kind === "layers") (d.layers || []).forEach(function (l) { l.items.forEach(function (i) { out.push([i.id, i.label || i.id]); }); });
    else if (d.kind === "flow") { (d.nodes || []).forEach(function (n) { out.push(["n:" + n.id, n.label]); }); (d.edges || []).forEach(function (e) { out.push(["e:" + e.from + ">" + e.to + ":" + (e.text || ""), e.from + " → " + e.to]); }); }
    else if (d.kind === "states") { (d.states || []).forEach(function (s) { out.push(["s:" + s, s]); }); (d.transitions || []).forEach(function (t) { out.push(["t:" + t.from + ">" + t.to + ":" + t.text, t.from + " → " + t.to]); }); }
    else if (d.kind === "sequence") (d.messages || []).forEach(function (m) { out.push(["m:" + m.from + ">" + m.to + ":" + m.text, m.from + " → " + m.to + (m.text ? ": " + m.text : "")]); });
    else if (d.kind === "steps") (d.steps || []).forEach(function (s) { out.push(["p:" + s.text, s.text]); });
    else if (d.kind === "list") (d.items || []).forEach(function (i) { out.push(["l:" + i.text, i.text]); });
    return out;
  }
  function compare(d, prev) {
    if (!prev) return { isNew: function () { return false; }, gone: [] };
    var old = {}, now = {};
    keysOf(prev).forEach(function (k) { old[k[0]] = k[1]; });
    keysOf(d).forEach(function (k) { now[k[0]] = 1; });
    return { isNew: function (k) { return !old.hasOwnProperty(k); }, gone: Object.keys(old).filter(function (k) { return !now[k]; }).map(function (k) { return old[k]; }) };
  }
  function goneNote(c) {
    return c.gone.length ? '<p class="vz-gone"><span class="rv-tag gone">removed</span> ' + c.gone.slice(0, 8).map(esc).join(", ") + (c.gone.length > 8 ? " and " + (c.gone.length - 8) + " more" : "") + "</p>" : "";
  }

  /* ---------- a graph laid out left to right or top down (flow and state diagrams) ---------- */
  function layout(nodes, edges, dir) {
    var ids = nodes.map(function (n) { return n.id; }), idx = {};
    ids.forEach(function (id, i) { idx[id] = i; });
    var out = {}, back = {}, state = {};
    ids.forEach(function (id) { out[id] = []; });
    edges.forEach(function (e) { if (idx.hasOwnProperty(e.from) && idx.hasOwnProperty(e.to)) out[e.from].push(e); });
    function dfs(id) {
      state[id] = 1;
      out[id].forEach(function (e) { if (state[e.to] === 1) back[e.from + ">" + e.to + ":" + (e.text || "")] = true; else if (!state[e.to]) dfs(e.to); });
      state[id] = 2;
    }
    ids.forEach(function (id) { if (!state[id]) dfs(id); });
    var rank = {};
    function rk(id) {
      if (rank.hasOwnProperty(id)) return rank[id];
      rank[id] = 0;
      var best = 0;
      edges.forEach(function (e) { if (e.to === id && idx.hasOwnProperty(e.from) && !back[e.from + ">" + e.to + ":" + (e.text || "")] && e.from !== id) best = Math.max(best, rk(e.from) + 1); });
      return (rank[id] = best);
    }
    ids.forEach(rk);
    var layers = [];
    ids.forEach(function (id) { (layers[rank[id]] = layers[rank[id]] || []).push(id); });
    layers = layers.filter(Boolean);
    var pos = {};
    layers.forEach(function (l) { l.forEach(function (id, i) { pos[id] = i; }); });
    for (var pass = 0; pass < 3; pass++) {
      layers.forEach(function (l, li) {
        if (!li) return;
        var bary = {};
        l.forEach(function (id) {
          var ps = edges.filter(function (e) { return e.to === id && rank[e.from] === li - 1; }).map(function (e) { return pos[e.from]; });
          bary[id] = ps.length ? ps.reduce(function (a, b) { return a + b; }, 0) / ps.length : pos[id];
        });
        l.sort(function (a, b) { return bary[a] - bary[b]; });
        l.forEach(function (id, i) { pos[id] = i; });
      });
    }
    var horizontal = dir === "LR" || dir === "RL", size = {};
    nodes.forEach(function (n) { size[n.id] = { w: Math.max(72, Math.min(190, tw(n.label, 6.8) + 26)), h: n.shape === "diamond" ? 44 : 34 }; });
    var gapN = horizontal ? 18 : 22, at = {}, cursor = 0, span = 0, extent = [], gapAfter = [];
    layers.forEach(function (l, li) {  /* room for the longest label of an arrow leaving this rank, when ranks sit side by side */
      var w = 0;
      edges.forEach(function (e) { if (e.text && rank[e.from] === li && rank[e.to] > li) w = Math.max(w, tw(clip(e.text, 24), 6)); });
      gapAfter.push(horizontal ? Math.max(64, Math.min(190, w + 32)) : 46);
    });
    layers.forEach(function (l) {
      var along = 0;
      l.forEach(function (id) { along += (horizontal ? size[id].h : size[id].w) + gapN; });
      extent.push(along - gapN); span = Math.max(span, along - gapN);
    });
    layers.forEach(function (l, li) {
      var thick = Math.max.apply(null, l.map(function (id) { return horizontal ? size[id].w : size[id].h; })), p = (span - extent[li]) / 2;
      l.forEach(function (id) {
        var s = size[id];
        at[id] = horizontal ? { x: cursor + (thick - s.w) / 2, y: p, w: s.w, h: s.h } : { x: p, y: cursor + (thick - s.h) / 2, w: s.w, h: s.h };
        p += (horizontal ? s.h : s.w) + gapN;
      });
      cursor += thick + gapAfter[li];
    });
    var last = gapAfter[gapAfter.length - 1] || 0;
    return { at: at, back: back, w: (horizontal ? cursor - last : span) + 16, h: (horizontal ? span : cursor - last) + 16, horizontal: horizontal };
  }
  function nodeShape(n, p) {
    var x = p.x + 8, y = p.y + 8, w = p.w, h = p.h;
    if (n.shape === "diamond") return '<polygon points="' + [(x + w / 2) + "," + y, (x + w) + "," + (y + h / 2), (x + w / 2) + "," + (y + h), x + "," + (y + h / 2)].join(" ") + '"/>';
    if (n.shape === "circle" || n.shape === "stadium" || n.shape === "round") return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="' + (n.shape === "round" ? 10 : h / 2) + '"/>';
    if (n.shape === "cyl") return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="6"/><path d="M' + x + " " + (y + 8) + " q" + (w / 2) + " 7 " + w + ' 0" fill="none"/>';
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="5"/>';
  }
  function edgePath(a, b, L, loop) {
    var ax, ay, bx, by;
    if (L.horizontal) {
      var fwd = a.x <= b.x;
      ax = a.x + (fwd ? a.w : 0) + 8; ay = a.y + a.h / 2 + 8; bx = b.x + (fwd ? 0 : b.w) + 8; by = b.y + b.h / 2 + 8;
      var m = (ax + bx) / 2;
      return { d: loop ? "M" + ax + " " + ay + " C" + (ax + 30) + " " + (ay - 46) + " " + (bx - 30) + " " + (by - 46) + " " + bx + " " + by : "M" + ax + " " + ay + " C" + m + " " + ay + " " + m + " " + by + " " + bx + " " + by, lx: (ax + bx) / 2, ly: (ay + by) / 2 + (loop ? -34 : 0) };
    }
    var down = a.y <= b.y;
    ax = a.x + a.w / 2 + 8; ay = a.y + (down ? a.h : 0) + 8; bx = b.x + b.w / 2 + 8; by = b.y + (down ? 0 : b.h) + 8;
    var my = (ay + by) / 2;
    return { d: loop ? "M" + ax + " " + ay + " C" + (ax + 60) + " " + (ay + 30) + " " + (bx + 60) + " " + (by - 30) + " " + bx + " " + by : "M" + ax + " " + ay + " C" + ax + " " + my + " " + bx + " " + my + " " + bx + " " + by, lx: (ax + bx) / 2 + (loop ? 46 : 0), ly: (ay + by) / 2 };
  }
  /* one marker per drawing, with an id of its own: a marker defined in a hidden (closed) drawing is not drawn for one that shows */
  var markers = 0;
  function mark() { var id = "vzm" + (++markers); return { id: id, defs: '<defs><marker id="' + id + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="vz-head"/></marker></defs>' }; }
  function graph(d, c, goKey) {
    var nodes = d.kind === "states" ? d.states.map(function (s) { return { id: s, label: s, shape: s === "start" || s === "end" ? "stadium" : "round" }; }) : d.nodes;
    var edges = d.kind === "states" ? d.transitions.map(function (t) { return { from: t.from, to: t.to, text: t.text }; }) : d.edges;
    var L = layout(nodes, edges, d.kind === "states" ? "LR" : (d.dir || "TD")), byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var groups = {};
    nodes.forEach(function (n) { if (n.group) (groups[n.group] = groups[n.group] || []).push(n.id); });
    var mk = mark();
    var svg = '<svg class="vz-svg" xmlns="http://www.w3.org/2000/svg" width="' + Math.ceil(L.w) + '" height="' + Math.ceil(L.h) + '" viewBox="0 0 ' + Math.ceil(L.w) + " " + Math.ceil(L.h) + '" role="img" aria-label="' + esc(d.alt || "") + '">' + mk.defs;
    Object.keys(groups).forEach(function (g) {
      var bx = groups[g].map(function (id) { return L.at[id]; }), x0 = Math.min.apply(null, bx.map(function (b) { return b.x; })) + 8 - 10, y0 = Math.min.apply(null, bx.map(function (b) { return b.y; })) + 8 - 20;
      var x1 = Math.max.apply(null, bx.map(function (b) { return b.x + b.w; })) + 8 + 10, y1 = Math.max.apply(null, bx.map(function (b) { return b.y + b.h; })) + 8 + 10;
      svg += '<g class="vz-group"><rect x="' + x0 + '" y="' + y0 + '" width="' + (x1 - x0) + '" height="' + (y1 - y0) + '" rx="8"/><text x="' + (x0 + 8) + '" y="' + (y0 + 13) + '">' + esc(clip(g, 40)) + "</text></g>";
    });
    edges.forEach(function (e) {
      var a = L.at[e.from], b = L.at[e.to]; if (!a || !b) return;
      var loop = !!L.back[e.from + ">" + e.to + ":" + (e.text || "")] || e.from === e.to, p = edgePath(a, b, L, loop);
      svg += '<g class="vz-edge' + (e.style ? " " + e.style : "") + '" data-from="' + esc(e.from) + '" data-to="' + esc(e.to) + '"><path d="' + p.d + '" marker-end="url(#' + mk.id + ')"/>' +
        (e.text ? '<text x="' + p.lx + '" y="' + p.ly + '" text-anchor="middle">' + esc(clip(e.text, 24)) + "</text>" : "") + "</g>";
    });
    nodes.forEach(function (n) {
      var p = L.at[n.id], key = d.kind === "states" ? "s:" + n.id : "n:" + n.id, isNew = c.isNew(key);
      svg += '<g class="vz-node' + (isNew ? " vz-new" : "") + '" tabindex="0" role="button" data-id="' + esc(n.id) + '" data-vz-go="' + esc(goKey(n)) + '" aria-label="' + esc(n.label + (isNew ? " (new in this round)" : "")) + '">' +
        "<title>" + esc(n.label) + "</title>" + nodeShape(n, p) + '<text x="' + (p.x + 8 + p.w / 2) + '" y="' + (p.y + 8 + p.h / 2 + 4) + '" text-anchor="middle">' + esc(clip(n.label, 26)) + "</text></g>";
    });
    return svg + "</svg>";
  }

  /* ---------- a trace ribbon: columns left to right, a curve for every link ---------- */
  /* natural order: US2.1 before US10.1, FR9 before FR10 */
  function natKey(s) { return String(s).split(/(\d+)/).map(function (p, i) { return i % 2 ? +p : p.toLowerCase(); }); }
  function natCmp(a, b) {
    var x = natKey(a), y = natKey(b), n = Math.min(x.length, y.length);
    for (var i = 0; i < n; i++) if (x[i] !== y[i]) return typeof x[i] === "number" && typeof y[i] === "number" ? x[i] - y[i] : (String(x[i]) < String(y[i]) ? -1 : 1);
    return x.length - y.length;
  }
  var TRACE_MAX_COL = 10, TRACE_MAX_EDGES = 36, chosen = {};  /* above this size a trace is a tangle: it is offered per requirement */
  /* the ribbon of one set of nodes: each column in natural order, then swept back and forth so that a box sits near the boxes it links to */
  function drawTrace(d, c) {
    var cols = d.cols || [], per = {}, W = 150, H = 38, GX = 70, GY = 12, top = 30, edges = d.edges || [];
    (d.nodes || []).forEach(function (n) { (per[n.col] = per[n.col] || []).push(n); });
    cols.forEach(function (k) { (per[k.key] || []).sort(function (a, b) { return natCmp(a.id, b.id); }); });
    var pos = function (key) { var at = {}; (per[key] || []).forEach(function (n, i) { at[n.id] = i; }); return at; };
    var sweep = function (ci, from) {
      var at = pos(cols[from].key);
      var mean = function (n) { var xs = edges.map(function (e) { return e[1] === n.id && at.hasOwnProperty(e[0]) ? at[e[0]] : e[0] === n.id && at.hasOwnProperty(e[1]) ? at[e[1]] : null; }).filter(function (x) { return x !== null; }); return xs.length ? xs.reduce(function (a, b) { return a + b; }, 0) / xs.length : 1e9; };
      var arr = per[cols[ci].key] || [], idx = {}; arr.forEach(function (n, i) { idx[n.id] = i; });
      arr.sort(function (a, b) { return (mean(a) - mean(b)) || (idx[a.id] - idx[b.id]); });
    };
    for (var pass = 0; pass < 3; pass++) {
      for (var ci = 1; ci < cols.length; ci++) sweep(ci, ci - 1);
      for (var cj = cols.length - 2; cj >= 0; cj--) sweep(cj, cj + 1);
    }
    var rows = Math.max.apply(null, cols.map(function (k) { return (per[k.key] || []).length; }).concat([1]));
    var at = {}, width = cols.length * W + (cols.length - 1) * GX + 16, height = top + rows * (H + GY) + 8;
    cols.forEach(function (k, ci) { (per[k.key] || []).forEach(function (n, ri) { at[n.id] = { x: 8 + ci * (W + GX), y: top + ri * (H + GY) }; }); });
    var mk = mark();
    var svg = '<svg class="vz-svg" xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="' + esc(d.alt || "") + '">' + mk.defs;
    cols.forEach(function (k, ci) { svg += '<text class="vz-colh" x="' + (8 + ci * (W + GX)) + '" y="16">' + esc(k.label) + "</text>"; });
    edges.forEach(function (e) {
      var a = at[e[0]], b = at[e[1]]; if (!a || !b) return;
      var ax = a.x + W, ay = a.y + H / 2, bx = b.x, by = b.y + H / 2, m = (ax + bx) / 2;
      svg += '<g class="vz-edge" data-from="' + esc(e[0]) + '" data-to="' + esc(e[1]) + '"><path d="M' + ax + " " + ay + " C" + m + " " + ay + " " + m + " " + by + " " + bx + " " + by + '" marker-end="url(#' + mk.id + ')"/></g>';
    });
    (d.nodes || []).forEach(function (n) {
      var p = at[n.id], isNew = c.isNew(n.id), label = n.label ? n.id + " " + n.label : n.id;
      svg += '<g class="vz-node' + (n.ok === false ? " bad" : "") + (isNew ? " vz-new" : "") + '" tabindex="0" role="link" data-id="' + esc(n.id) + '" data-vz-go="' + esc(n.id) + '" aria-label="' + esc(label + (n.ok === false ? ", not covered" : "") + (isNew ? ", new in this round" : "")) + '">' +
        "<title>" + esc(label) + '</title><rect x="' + p.x + '" y="' + p.y + '" width="' + W + '" height="' + H + '" rx="6"/><text class="vz-id" x="' + (p.x + 9) + '" y="' + (p.y + 15) + '">' + esc(n.id) + "</text>" +
        (n.label ? '<text class="vz-sub" x="' + (p.x + 9) + '" y="' + (p.y + 29) + '">' + esc(clip(n.label, 22)) + "</text>" : "") + "</g>";
    });
    return svg + "</svg>";
  }
  /* The trace: all at once while it reads (a few boxes a column); above that it is a tangle, so it is offered per requirement: pick one, see its chain. */
  function trace(d, c) {
    var cols = d.cols || [], nodes = d.nodes || [], edges = d.edges || [];
    var big = Math.max.apply(null, cols.map(function (k) { return nodes.filter(function (n) { return n.col === k.key; }).length; }).concat([0])) > TRACE_MAX_COL || edges.length > TRACE_MAX_EDGES;
    if (!big || !cols.length) return drawTrace(d, c);
    var first = nodes.filter(function (n) { return n.col === cols[0].key; }).sort(function (a, b) { return natCmp(a.id, b.id); });
    var sel = chosen[d.id || "trace"]; if (!first.some(function (n) { return n.id === sel; })) sel = first.length ? first[0].id : "";
    var chain = function (id) {  /* what it leads to and what leads to it, through every column */
      var keep = {}, out = {}, back = {}; keep[id] = 1;
      var go = function (fromIdx, toIdx) { var q = [id], seen = {}; seen[id] = 1; while (q.length) { var x = q.shift(); edges.forEach(function (e) { var nx = e[fromIdx] === x ? e[toIdx] : null; if (nx && !seen[nx]) { seen[nx] = 1; keep[nx] = 1; q.push(nx); } }); } };
      go(0, 1); go(1, 0);
      return { cols: cols, nodes: nodes.filter(function (n) { return keep[n.id]; }), edges: edges.filter(function (e) { return keep[e[0]] && keep[e[1]]; }), alt: d.alt, id: d.id };
    };
    return '<div class="vz-pickrow"><label>' + esc(cols[0].label) + ' <select class="vz-pick" data-vz-pick="' + esc(d.id || "trace") + '" aria-label="Pick one to see its chain">' + first.map(function (n) { return '<option value="' + esc(n.id) + '"' + (n.id === sel ? " selected" : "") + ">" + esc(n.label ? n.id + " " + clip(n.label, 40) : n.id) + "</option>"; }).join("") + "</select></label>" +
      '<span class="hint">' + plural(first.length, cols[0].label.toLowerCase().replace(/s$/, "")) + ", " + plural(edges.length, "link") + ": too many to draw at once, so pick one and see what it leads to</span></div>" +
      first.map(function (n) { return '<div class="vz-chain" data-for="' + esc(n.id) + '"' + (n.id === sel ? "" : " hidden") + ">" + drawTrace(chain(n.id), c) + "</div>"; }).join("");
  }
  /* ---------- layers: a band per layer, the components in it, what they depend on one hover away ---------- */
  function layers(d, c, opts) {
    var uses = {};
    (d.edges || []).forEach(function (e) { (uses[e[0]] = uses[e[0]] || []).push(e[1]); });
    var html = '<div class="vz-layers">' + d.layers.map(function (l, i) {
      return '<div class="vz-layer"><div class="vz-lname">' + esc(l.name) + '<span class="n">' + l.items.length + "</span></div><div class=\"vz-items\">" + l.items.map(function (it) {
        var u = uses[it.id] || [], isNew = c.isNew(it.id);
        return '<button type="button" class="vz-item' + (isNew ? " vz-new" : "") + '" data-id="' + esc(it.id) + '" data-uses="' + esc(u.join("|")) + '" data-vz-go="' + esc(it.id) + '" aria-label="' + esc(it.label + (u.length ? ", depends on " + u.join(", ") : ", depends on nothing here") + (isNew ? ", new in this round" : "")) + '">' +
          "<b>" + esc(clip(it.label, 30)) + "</b>" + (it.note ? "<small>" + esc(clip(it.note, 70)) + "</small>" : "") + (u.length ? '<span class="uses">uses ' + u.length + "</span>" : "") + "</button>";
      }).join("") + "</div></div>" + (i < d.layers.length - 1 ? '<div class="vz-down" aria-hidden="true">depends on ↓</div>' : "");
    }).join("") + "</div>";
    return html;
  }

  /* ---------- a sequence: lifelines, numbered messages top to bottom ---------- */
  function sequence(d, c) {
    var A = d.actors || [], longest = Math.max.apply(null, d.messages.map(function (m) { return tw("00. " + clip(m.text, 40), 6.2); }).concat([120]));
    var gap = Math.min(320, Math.max(150, longest + 24)), left = 20, top = 44, row = 40, width = left * 2 + (A.length - 1) * gap + 70, height = top + (d.messages.length + 1) * row, x = {}, mk = mark();
    A.forEach(function (a, i) { x[a] = left + 36 + i * gap; });
    var svg = '<svg class="vz-svg" xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="' + esc(d.alt || "") + '">' + mk.defs;
    A.forEach(function (a) {
      svg += '<g class="vz-actor"><line x1="' + x[a] + '" y1="34" x2="' + x[a] + '" y2="' + (height - 6) + '"/><rect x="' + (x[a] - 56) + '" y="6" width="112" height="26" rx="6"/><text x="' + x[a] + '" y="23" text-anchor="middle">' + esc(clip(a, 16)) + "<title>" + esc(a) + "</title></text></g>";
    });
    d.messages.forEach(function (m, i) {
      var y = top + 14 + i * row, a = x[m.from], b = x[m.to], isNew = c.isNew("m:" + m.from + ">" + m.to + ":" + m.text);
      var self = a === b, label = (i + 1) + ". " + clip(m.text, 40);
      svg += '<g class="vz-msg' + (isNew ? " vz-new" : "") + '" tabindex="0" role="button" data-vz-text="' + esc(m.text || m.from) + '" aria-label="' + esc("Step " + (i + 1) + ": " + m.from + " to " + m.to + (m.text ? ", " + m.text : "") + (isNew ? ", new in this round" : "")) + '">' +
        "<title>" + esc(m.from + " → " + m.to + (m.text ? ": " + m.text : "")) + "</title>" +
        (self ? '<path d="M' + a + " " + y + " h28 v14 h-26" + '" marker-end="url(#' + mk.id + ')"/><text x="' + (a + 34) + '" y="' + (y + 4) + '">' + esc(label) + "</text>"
          : '<line x1="' + a + '" y1="' + y + '" x2="' + b + '" y2="' + y + '" marker-end="url(#' + mk.id + ')"/><text x="' + ((a + b) / 2) + '" y="' + (y - 6) + '" text-anchor="middle">' + esc(label) + "</text>") + "</g>";
    });
    return svg + "</svg>";
  }

  /* ---------- steps: the numbered list as a chain ---------- */
  function steps(d, c) {
    return '<ol class="vz-steps">' + d.steps.map(function (s) {
      var isNew = c.isNew("p:" + s.text);
      return '<li class="' + (isNew ? "vz-new" : "") + '"><button type="button" data-vz-text="' + esc(s.text) + '"><span class="no">' + s.n + "</span><span>" + esc(s.text) + "</span></button></li>";
    }).join("") + "</ol>";
  }
  function listOf(d, c) {
    return '<div class="vz-listbox"><p class="hint">' + esc(d.heading || "Diagram") + ", as a list</p><ul>" + d.items.map(function (i) {
      return '<li class="' + (c.isNew("l:" + i.text) ? "vz-new" : "") + '">' + esc(i.text) + (i.note ? ' <span class="hint">' + esc(i.note) + "</span>" : "") + "</li>";
    }).join("") + "</ul></div>";
  }

  function altOf(d) {
    var out = [];
    if (d.kind === "trace") (d.edges || []).forEach(function (e) { out.push(e[0] + " leads to " + e[1]); });
    else if (d.kind === "layers") d.layers.forEach(function (l) { out.push("Layer " + l.name + ": " + l.items.map(function (i) { return i.label; }).join(", ")); });
    else if (d.kind === "flow") (d.edges || []).forEach(function (e) { out.push(e.from + " to " + e.to + (e.text ? " (" + e.text + ")" : "")); });
    else if (d.kind === "states") (d.transitions || []).forEach(function (t) { out.push(t.from + " to " + t.to + (t.text ? " on " + t.text : "")); });
    else if (d.kind === "sequence") (d.messages || []).forEach(function (m, i) { out.push((i + 1) + ". " + m.from + " to " + m.to + (m.text ? ": " + m.text : "")); });
    else if (d.kind === "steps") (d.steps || []).forEach(function (s) { out.push(s.n + ". " + s.text); });
    else if (d.kind === "list") (d.items || []).forEach(function (i) { out.push(i.text); });
    return out.slice(0, 80);
  }

  function diagram(d, opts) {
    opts = opts || {};
    var c = compare(d, opts.prev), inner = "", extra = { alt: altOf(d), after: goneNote(c) }, hint = "";
    if (d.kind === "trace") { inner = trace(d, c); hint = "press a box to go to it"; if (d.more) extra.after += '<p class="hint">' + plural(d.more, "more id") + " not drawn; they are in the text.</p>"; }
    else if (d.kind === "layers") {
      inner = layers(d, c, opts); hint = "hover a box to see what it depends on";
      var m = (opts.maps || []).filter(function (x) { return x && x.kind === d.map && /^https:\/\//.test(String(x.url || "")); })[0];
      if (m) extra.after += '<p class="vz-maplink"><a href="' + esc(m.url) + '" target="_blank" rel="noopener" data-map-link="' + esc(m.kind) + '">Open the full ' + esc(m.title || d.map + " map") + "</a></p>";
    } else if (d.kind === "sequence") { inner = sequence(d, c); hint = "press a message to find it in the text"; }
    else if (d.kind === "steps") { inner = steps(d, c); hint = "press a step to find it in the text"; }
    else if (d.kind === "flow" || d.kind === "states") { inner = graph(d, c, function (n) { return ""; }); hint = "press a box to find it in the text"; }
    else if (d.kind === "list") { inner = listOf(d, c); extra.noTitle = false; }
    else return "";
    extra.hint = hint;
    if (d.kind === "steps" || d.kind === "list" || d.kind === "layers") return figure(d.kind, d, inner, extra).replace(/ class="vz-scroll" tabindex="0" role="region" aria-label="[^"]*"/, ' class="vz-flat"');
    return figure(d.kind, d, inner, extra);
  }

  /* ---------- the target heat grid ---------- */
  var HEAT = { "Not Met": "notmet", Unverified: "unverified", Met: "met", "N/A": "na" };
  function heat(m) {
    var cols = m.cols || [], rows = m.rows || [], cells = m.cells || {}, on = m.active || "";
    var total = 0; Object.keys(cells).forEach(function (k) { total += cells[k].n; });
    var head = '<tr><th scope="col"><span class="sr">Group</span></th>' + cols.map(function (c) { return '<th scope="col"><button type="button" class="vz-hcol" data-vz-set="heat:col:' + esc(c) + '" aria-pressed="' + (on === "col:" + c) + '">' + esc(c) + "</button></th>"; }).join("") + "</tr>";
    var body = rows.map(function (r) {
      return '<tr><th scope="row"><button type="button" class="vz-hrow" data-vz-set="heat:row:' + esc(r) + '" aria-pressed="' + (on === "row:" + r) + '">' + esc(r) + "</button></th>" + cols.map(function (c) {
        var x = cells[r + "\u0001" + c];
        if (!x) return '<td class="empty"><span aria-hidden="true">·</span><span class="sr">none</span></td>';
        var key = r + "\u0001" + c, tip = x.n + " target" + (x.n === 1 ? "" : "s") + " in " + c + " / " + r + ", worst: " + x.worst;
        return '<td><button type="button" class="vz-cell ' + HEAT[x.worst] + '" data-vz-set="heat:cell:' + esc(key) + '" aria-pressed="' + (on === "cell:" + key) + '" aria-label="' + esc(tip) + '" data-tip="' + esc(tip) + '">' + x.n + "</button></td>";
      }).join("") + "</tr>";
    }).join("");
    var legend = '<p class="vz-legend">' + ["Not Met", "Unverified", "Met", "N/A"].map(function (v) { return '<span><i class="' + HEAT[v] + '"></i>' + v + "</span>"; }).join("") + '<span class="hint">a cell is coloured by its worst target; press one to filter the list</span></p>';
    return '<figure class="vz vz-heat" data-aidlc-noids role="group" aria-label="' + esc("Target heat grid: " + total + " targets, " + cols.length + " Units, " + rows.length + " groups") + '"><figcaption class="vz-title">Where the targets stand' +
      (on ? ' <button type="button" class="vz-clear" data-vz-set="heat:">Show all</button>' : "") + '</figcaption><div class="vz-scroll" tabindex="0" role="region" aria-label="Target heat grid, scrolls sideways"><table class="vz-table"><caption class="sr">Targets by Unit and group; each cell is the number of targets, coloured by the worst verdict</caption>' + head + body + "</table></div>" + legend + "</figure>";
  }

  /* ---------- the verification funnel ---------- */
  var FUN = [["auto", "Covered by automated tests", "auto"], ["verified", "Verified by you", "verified"], ["unverified", "Not verified", "unverified"], ["failed", "Failed, left as known", "failed"]];
  function funnel(f) {
    var total = f.total || 0, on = f.active || "";
    if (!total) return "";
    var segs = FUN.map(function (s) { return { k: s[0], label: s[1], n: f[s[0]] || 0 }; });
    var bar = segs.filter(function (s) { return s.n; }).map(function (s) {
      var pct = Math.max(2, s.n / total * 100);
      var inner = "<b>" + s.n + "</b><span>" + esc(s.label) + "</span>", lab = esc(s.label + ": " + plural(s.n, "point") + " of " + total), tip = esc(s.label + ": " + s.n + " of " + total);
      /* the points the code's own tests cover are not rows of the list below, so that part is not a filter */
      if (s.k === "auto") return '<span class="vz-seg auto" style="flex:' + pct.toFixed(2) + ' 1 0" role="img" aria-label="' + lab + '" data-tip="' + tip + '">' + inner + "</span>";
      return '<button type="button" class="vz-seg ' + s.k + '" style="flex:' + pct.toFixed(2) + ' 1 0" data-vz-set="verif:' + s.k + '" aria-pressed="' + (on === s.k) + '" aria-label="' + lab + '" data-tip="' + tip + '">' + inner + "</button>";
    }).join("");
    var line = segs.map(function (s) { return s.label + " " + s.n; }).join(", ");
    return '<figure class="vz vz-funnel" data-aidlc-noids role="group" aria-label="' + esc("Verification funnel: " + total + " points; " + line) + '"><figcaption class="vz-title">Where the ' + plural(total, "point") + ' stand<span class="hint">press a part to show only its points; the tests&#39; part is not one of the rows below</span></figcaption><div class="vz-bar">' + bar + "</div>" +
      (on ? '<button type="button" class="vz-clear" data-vz-set="verif:">Show all points</button>' : "") + '<ul class="vz-sr">' + segs.map(function (s) { return "<li>" + esc(s.label + ": " + s.n) + "</li>"; }).join("") + "</ul></figure>";
  }

  /* ---------- the round timeline: it replaces the legend chips; each round is still one pressable chip (data-rvonly) ---------- */
  function timeline(rounds, only) {
    if (!rounds || !rounds.length) return "";
    var max = Math.max.apply(null, rounds.map(function (r) { return r.changed + r.added + r.removed; }).concat([1]));
    return '<ol class="vz-tl rv-legend" role="group" aria-label="Changes by version">' + rounds.map(function (r) {
      var n = r.changed + r.added + r.removed, h = n ? Math.max(14, Math.round(n / max * 100)) : 0;
      var words = r.words ? '<span class="w">' + r.words + (r.words === 1 ? " word" : " words") + "</span>" : "";
      var label = "Version " + r.k + (r.base ? ", the first round" : ": " + plural(r.changed, "change") + ", " + r.added + " added, " + r.removed + " removed");
      if (r.base) return '<li><span class="vz-round base rv-t' + r.tone + '" data-tip="The first round: everything in it was written then"><i aria-hidden="true"></i><b>v' + r.k + '</b><span class="w">first round</span></span></li>';
      return '<li><button type="button" class="vz-round rv-chip rv-t' + r.tone + '" data-rvonly="' + r.k + '" aria-pressed="' + (only === r.k) + '" aria-label="' + esc(label + (only === r.k ? ", shown alone" : "")) + '" data-tip="' + esc(label) + '"><i aria-hidden="true"></i><b>v' + r.k + "</b>" +
        ('<span class="vz-spark" aria-hidden="true"><s style="height:' + h + '%"></s></span><span class="vz-nums"><span class="c" title="changed">~' + r.changed + '</span><span class="a" title="added">+' + r.added + '</span><span class="g" title="removed">−' + r.removed + "</span></span>") + words + "</button></li>";
    }).join("") + "</ol>";
  }

  /* ---------- plan steps as lanes ---------- */
  function lanes(L) {
    var lanesL = L.lanes || [];
    if (lanesL.length < 2) return "";
    var total = lanesL.reduce(function (a, l) { return a + l.steps.length; }, 0);
    return '<figure class="vz vz-lanes" data-aidlc-noids role="group" aria-label="' + esc("Plan steps by layer: " + total + " steps in " + lanesL.length + " layers, in build order") + '"><figcaption class="vz-title">Steps by layer<span class="hint">press a step to go to its row</span></figcaption><div class="vz-lanes-in">' + lanesL.map(function (l) {
      return '<div class="vz-lane"><div class="vz-lname">' + esc(l.name) + '<span class="n">' + l.steps.length + '</span></div><ol class="vz-lsteps">' + l.steps.map(function (s) {
        return '<li><button type="button" class="vz-lstep" data-vz-go="' + esc(s.key) + '" aria-label="' + esc("Step " + s.n + ": " + s.title + (s.implements && s.implements.length ? ", implements " + s.implements.join(", ") : "")) + '"><span class="no">' + esc(s.n) + "</span><span class=\"t\">" + esc(clip(s.title, 60)) + "</span>" +
          (s.implements && s.implements.length ? '<span class="im">' + s.implements.slice(0, 4).map(esc).join(" · ") + (s.implements.length > 4 ? " +" + (s.implements.length - 4) : "") + "</span>" : "") + "</button></li>";
      }).join("") + "</ol></div>";
    }).join("") + '</div><ul class="vz-sr">' + lanesL.map(function (l) { return "<li>" + esc(l.name + ": " + l.steps.map(function (s) { return "step " + s.n + " " + s.title; }).join("; ")) + "</li>"; }).join("") + "</ul></figure>";
  }

  /* ---------- criteria at a glance ---------- */
  function dots(groups) {
    var all = groups.reduce(function (a, g) { return a + g.items.length; }, 0);
    if (!all) return "";
    var tally = {}; groups.forEach(function (g) { g.items.forEach(function (c) { tally[c.v] = (tally[c.v] || 0) + 1; }); });
    var line = ["holds", "fails", "n/a", "unjudged"].filter(function (k) { return tally[k]; }).map(function (k) { return tally[k] + " " + ({ holds: "hold", fails: "fail", "n/a": "not relevant", unjudged: "not judged" })[k]; }).join(", ");
    return '<div class="vz vz-dots" data-aidlc-noids role="group" aria-label="' + esc("Criteria at a glance: " + all + " criteria; " + line) + '">' + groups.map(function (g) {
      return '<span class="vz-dg"><span class="gn">' + esc(g.name) + "</span>" + g.items.map(function (c) {
        return '<button type="button" class="vz-dot ' + String(c.v).replace("/", "") + '" data-vz-go="' + esc(c.key) + '" aria-label="' + esc(c.title + ": " + c.label) + '" data-tip="' + esc(c.title + " — " + c.label) + '"></button>';
      }).join("") + "</span>";
    }).join("") + '<span class="vz-dl hint">' + esc(line) + "</span></div>";
  }

  /* ---------- a file's outline: a sticky list beside it on wide screens, a collapsible strip on narrow ones ---------- */
  function outline(items) {
    if (!items || items.length < 5) return "";
    var li = items.map(function (i) { return '<li class="l' + (i.level || 2) + '"><button type="button" data-vz-jump="' + esc(i.id) + '">' + esc(clip(i.title, 60)) + "</button></li>"; }).join("");
    return '<nav class="fo-side" data-rv-skip aria-label="Headings of this file"><p class="fo-h">In this file</p><ol>' + li + '</ol></nav><details class="fo-strip" data-rv-skip><summary>In this file<span class="n">' + items.length + ' headings</span></summary><ol>' + li + "</ol></details>";
  }

  /* hover or focus a box: it and what it is linked to stand out, the rest steps back */
  function bind(root) {
    if (!root || root.__vz) return; root.__vz = true;
    function on(e) {
      var n = e.target.closest && e.target.closest(".vz-node, .vz-item"); if (!n) return;
      var fig = n.closest(".vz"), id = n.getAttribute("data-id"), rel = {}; rel[id] = 1;
      [].forEach.call(fig.querySelectorAll(".vz-edge"), function (g) {
        var hit = g.getAttribute("data-from") === id || g.getAttribute("data-to") === id; g.classList.toggle("on", hit);
        if (hit) { rel[g.getAttribute("data-from")] = 1; rel[g.getAttribute("data-to")] = 1; }
      });
      (n.getAttribute("data-uses") || "").split("|").forEach(function (u) { if (u) rel[u] = 1; });
      fig.classList.add("vz-focus");
      [].forEach.call(fig.querySelectorAll(".vz-node, .vz-item"), function (x) { x.classList.toggle("rel", !!rel[x.getAttribute("data-id")]); });
    }
    function off(e) {
      var fig = e.target.closest && e.target.closest(".vz"); if (!fig) return;
      if (e.relatedTarget && fig.contains(e.relatedTarget)) return;
      fig.classList.remove("vz-focus");
      [].forEach.call(fig.querySelectorAll(".on, .rel"), function (x) { x.classList.remove("on", "rel"); });
    }
    root.addEventListener("mouseover", on); root.addEventListener("focusin", on);
    root.addEventListener("mouseout", off); root.addEventListener("focusout", off);
    root.addEventListener("keydown", function (e) {
      var n = e.target.closest && e.target.closest(".vz-node[data-vz-go], .vz-msg"); if (n && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); n.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
    });
    /* a trace too big to draw at once: the picked requirement's chain shows, the others are hidden; the choice is kept */
    root.addEventListener("change", function (e) {
      var s = e.target.closest && e.target.closest("select.vz-pick"); if (!s) return;
      chosen[s.getAttribute("data-vz-pick") || "trace"] = s.value;
      [].forEach.call((s.closest(".vz") || root).querySelectorAll(".vz-chain"), function (c) { c.hidden = c.getAttribute("data-for") !== s.value; });
    });
  }

  return { diagram: diagram, heat: heat, funnel: funnel, timeline: timeline, lanes: lanes, dots: dots, outline: outline, bind: bind, keysOf: keysOf, esc: esc };
})();
if (typeof module !== "undefined" && module.exports) module.exports = GateViz;
