/* Shared: the canonical copy is shared/rev-diff/rev-diff.js; scripts/sync-shared.py copies it into every page that
   carries the block. What changed between two rounds of a page, shown in the page itself: words inserted are
   highlighted (.rv-ins), words removed are struck and muted (.rv-del), a block or element that is gone stays as a struck
   ghost (.rv-gone / .rv-removed), a new one is marked (.rv-new). It works on what a page already drew, so every view a
   page has gets the same diff: the page draws the earlier round the same way, off screen, and hands both trees here.

     RevDiff.diff(a, b, maxD)        Myers diff of two arrays of strings: [{t: "=" | "-" | "+", a0, a1, b0, b1}], or
                                     null when they differ in more than maxD places (the caller shows a whole replacement)
     RevDiff.words(old, now)         word-level segments [{t, s}] of two strings, cleaned up to read well
     RevDiff.markText(el, old, o)    mark the words of el that differ from the string old, in place; {ins, del}
     RevDiff.markTree(now, old, o)   mark every text block of the tree now against the tree old; {ins, del}
     RevDiff.diffKeyed(now, old, o)  match keyed parts (sections, elements) by key, then title; changed ones recurse,
                                     new ones are marked, gone ones are handed to o.onRemoved; the rest goes to markTree
     RevDiff.stops(root)             the changes in reading order, one stop per block, for next / previous
     RevDiff.reveal(node)            open every <details> around node, scroll to it and flash it
     RevDiff.pref() / setPref(v)     "show" | "clean": the viewer's choice, kept in this browser
   Standard browser APIs only; a page must not load a diff library for it. */
var RevDiff = (function () {
  "use strict";
  var WORD = /[\p{L}\p{N}_]+|\s+|[^\s\p{L}\p{N}_]/gu;
  var IS_WORD = /[\p{L}\p{N}]/u;
  var BLOCK = "p, li, td, th, h1, h2, h3, h4, h5, h6, pre, dt, dd, blockquote, figcaption, summary, caption, div";
  var CHROME = "button, svg, script, style, textarea, input, select, .rv-del, .rv-gone, .rv-removed, .rv-tag, [data-rv-skip]";
  var MAX_D = 1500;

  /* ---------- the core: Myers' O(ND) diff, prefix and suffix trimmed first ---------- */
  function diff(a, b, maxD) {
    maxD = maxD == null ? MAX_D : maxD;
    var n = a.length, m = b.length, pre = 0, suf = 0;
    while (pre < n && pre < m && a[pre] === b[pre]) pre++;
    while (suf < n - pre && suf < m - pre && a[n - 1 - suf] === b[m - 1 - suf]) suf++;
    var A = a.slice(pre, n - suf), B = b.slice(pre, m - suf), N = A.length, M = B.length;
    var moves = [];  /* [t, count] in order, over A and B */
    if (!N && !M) moves = [];
    else if (!N) moves = [["+", M]];
    else if (!M) moves = [["-", N]];
    else {
      var max = N + M, off = max + 1, v = new Int32Array(2 * max + 3), trace = [], d, k, x, y, found = -1;
      v[off + 1] = 0;
      for (d = 0; d <= max; d++) {
        if (d > maxD) return null;
        var snap = new Int32Array(2 * d + 3);
        for (k = -d - 1; k <= d + 1; k++) snap[k + d + 1] = v[off + k];
        trace.push(snap);
        for (k = -d; k <= d; k += 2) {
          if (k === -d || (k !== d && v[off + k - 1] < v[off + k + 1])) x = v[off + k + 1];
          else x = v[off + k - 1] + 1;
          y = x - k;
          while (x < N && y < M && A[x] === B[y]) { x++; y++; }
          v[off + k] = x;
          if (x >= N && y >= M) { found = d; break; }
        }
        if (found >= 0) break;
      }
      /* walk back: each d adds one insert or delete, then a snake of equal items */
      var path = []; x = N; y = M;
      for (d = found; d > 0; d--) {
        var t = trace[d], at = function (kk) { return t[kk + d + 1]; };
        k = x - y;
        var down = k === -d || (k !== d && at(k - 1) < at(k + 1));
        var pk = down ? k + 1 : k - 1, px = at(pk), py = px - pk;
        while (x > px + (down ? 0 : 1) && y > py + (down ? 1 : 0)) { path.push("="); x--; y--; }
        path.push(down ? "+" : "-");
        x = px; y = py;
      }
      while (x > 0 && y > 0) { path.push("="); x--; y--; }
      path.reverse();
      path.forEach(function (p) { var last = moves[moves.length - 1]; if (last && last[0] === p) last[1]++; else moves.push([p, 1]); });
    }
    var out = [], ia = 0, ib = 0;
    var push = function (t, c) {
      var r = { t: t, a0: ia, a1: ia, b0: ib, b1: ib };
      if (t !== "+") { ia += c; r.a1 = ia; }
      if (t !== "-") { ib += c; r.b1 = ib; }
      var last = out[out.length - 1];
      if (last && last.t === t) { last.a1 = r.a1; last.b1 = r.b1; } else out.push(r);
    };
    if (pre) push("=", pre);
    moves.forEach(function (mv) { push(mv[0], mv[1]); });
    if (suf) push("=", suf);
    return out;
  }

  /* ---------- words ---------- */
  function tokens(s) { return String(s || "").match(WORD) || []; }
  var keyOf = function (t) { return /^\s+$/.test(t) ? " " : t; };
  function countWords(s) { return tokens(s).filter(function (t) { return IS_WORD.test(t); }).length; }
  function norm(s) { return String(s || "").replace(/\s+/g, " ").trim(); }

  /* Segments of now against old: "=" kept, "-" removed (from old), "+" added. A short run kept between two changes
     (a space, a comma, one short word) joins them, so a reworded phrase reads as one removal and one insertion. */
  function words(old, now) {
    var a = tokens(old), b = tokens(now);
    var runs = diff(a.map(keyOf), b.map(keyOf));
    if (!runs) return [{ t: "-", s: a.join("") }, { t: "+", s: b.join("") }];
    var segs = runs.map(function (r) { return { t: r.t, s: r.t === "-" ? a.slice(r.a0, r.a1).join("") : b.slice(r.b0, r.b1).join("") }; });
    var changed = function (s) { return s && s.t !== "="; };
    for (var i = 1; i < segs.length - 1; i++) {
      var s = segs[i];
      if (s.t !== "=" || !changed(segs[i - 1]) || !changed(segs[i + 1])) continue;
      if (/^\s*$/.test(s.s) || (s.s.length <= 3 && !/\s/.test(s.s.trim()))) s.t = "~";  /* both sides keep it, as part of the change */
    }
    /* group each maximal change run into one removal then one insertion */
    var out = [], del = "", ins = "";
    var flush = function () { if (del) out.push({ t: "-", s: del }); if (ins) out.push({ t: "+", s: ins }); del = ins = ""; };
    segs.forEach(function (sg) {
      if (sg.t === "=") { flush(); out.push(sg); }
      else if (sg.t === "-") del += sg.s;
      else if (sg.t === "+") ins += sg.s;
      else { del += sg.s; ins += sg.s; }
    });
    flush();
    return out;
  }
  function similar(x, y) {
    var nx = norm(x).toLowerCase(), ny = norm(y).toLowerCase();
    if (nx && ny && (nx.indexOf(ny) >= 0 || ny.indexOf(nx) >= 0)) return 1;  /* one extends the other */
    var a = tokens(x).filter(function (t) { return IS_WORD.test(t); }), b = tokens(y).filter(function (t) { return IS_WORD.test(t); });
    if (!a.length || !b.length) return a.length === b.length ? 1 : 0;
    var seen = {}, hit = 0; a.forEach(function (t) { seen[t.toLowerCase()] = (seen[t.toLowerCase()] || 0) + 1; });
    b.forEach(function (t) { var k = t.toLowerCase(); if (seen[k]) { seen[k]--; hit++; } });
    return 2 * hit / (a.length + b.length);
  }

  /* ---------- the DOM ---------- */
  function skipped(node, root, o) {
    var e = node.nodeType === 1 ? node : node.parentElement;
    while (e && e !== root) { if (e.matches(CHROME) || (o.skip && e.matches(o.skip)) || (o.keyed && e.matches(o.keyed))) return true; e = e.parentElement; }
    return false;
  }
  function textNodes(root, o) {
    var out = [], doc = root.ownerDocument, w = doc.createTreeWalker(root, 4, null), n;
    while ((n = w.nextNode())) if (n.nodeValue && !skipped(n, root, o || {})) out.push(n);
    return out;
  }
  function textOf(root, o) { return joined(textNodes(root, o)).text; }
  /* The text blocks of a tree: runs of text nodes under the same nearest block, in reading order. */
  /* The joined text of a run of text nodes, with a space where two elements' words would otherwise run together
     (a tag "Fails" and a title "Is it…" read as two words, not "FailsIs"): {text, starts[]}, the start of each node. */
  function joined(nodes) {
    var text = "", starts = [];
    nodes.forEach(function (n, i) {
      var v = n.nodeValue;
      if (i && n.parentElement !== nodes[i - 1].parentElement && /\S$/.test(text) && /^\S/.test(v)) text += " ";
      starts.push(text.length); text += v;
    });
    return { text: text, starts: starts };
  }
  function units(root, o) {
    var out = [], cur = null;
    textNodes(root, o).forEach(function (n) {
      var owner = n.parentElement.closest(BLOCK);
      if (!owner || !root.contains(owner)) owner = root;
      if (!cur || cur.owner !== owner) { cur = { owner: owner, nodes: [] }; out.push(cur); }
      cur.nodes.push(n);
    });
    out.forEach(function (u) { u.text = joined(u.nodes).text; u.key = norm(u.text); });
    return out.filter(function (u) { return u.key; });
  }
  function el(doc, tag, cls, text) {
    var e = doc.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text;
    if (/rv-(del|gone)/.test(cls || "")) e.setAttribute("data-aidlc-noids", "");  /* removed text links nothing */
    return e;
  }

  /* Rewrite the text nodes of one block: ranges [from, to) of the joined text get <ins>, removed text goes in as <del>
     at its position. */
  function apply(nodes, ins, dels) {
    var starts = joined(nodes).starts, prevEnd = 0;
    nodes.forEach(function (n, idx) {
      var s = n.nodeValue, start = starts[idx], end = start + s.length, last = idx === nodes.length - 1, gap = prevEnd;
      prevEnd = end;
      var cuts = [];
      ins.forEach(function (r) { var a = Math.max(r[0], start), b = Math.min(r[1], end); if (a < b) cuts.push({ at: a - start, to: b - start, ins: true }); });
      /* a removal in the space joined() put between two nodes goes at the start of the second */
      dels.forEach(function (d) { if ((d[0] >= start && d[0] < end) || (d[0] >= gap && d[0] < start) || (last && d[0] >= end) || (d[0] === start && start === end)) cuts.push({ at: Math.min(Math.max(d[0] - start, 0), s.length), del: d[1] }); });
      if (!cuts.length) return;
      cuts.sort(function (x, y) { return x.at - y.at || (x.del ? -1 : 1); });
      var doc = n.ownerDocument, frag = doc.createDocumentFragment(), p = 0;
      cuts.forEach(function (c) {
        if (c.at > p) { frag.appendChild(doc.createTextNode(s.slice(p, c.at))); p = c.at; }
        if (c.del != null) frag.appendChild(el(doc, "del", "rv-del", c.del));
        else { frag.appendChild(el(doc, "ins", "rv-ins", s.slice(c.at, c.to))); p = c.to; }
      });
      if (p < s.length) frag.appendChild(doc.createTextNode(s.slice(p)));
      n.parentNode.replaceChild(frag, n);
    });
  }
  function markNodes(nodes, old) {
    var now = joined(nodes).text;
    var segs = words(old, now), p = 0, ins = [], dels = [], c = { ins: 0, del: 0 };
    var changedChars = 0;
    segs.forEach(function (s) { if (s.t !== "=") changedChars += s.s.length; });
    if (now.length > 60 && old.length > 60 && changedChars > 1.4 * Math.max(now.length, old.length)) segs = [{ t: "-", s: old }, { t: "+", s: now }];
    segs.forEach(function (s) {
      if (s.t === "=") p += s.s.length;
      else if (s.t === "+") { if (s.s.trim()) { ins.push([p, p + s.s.length]); c.ins += countWords(s.s); } p += s.s.length; }
      else if (s.s.trim()) { dels.push([p, s.s]); c.del += countWords(s.s); }
    });
    apply(nodes, ins, dels);
    return c;
  }
  function markText(root, old, o) { var nodes = textNodes(root, o || {}); if (!nodes.length) { if (norm(old)) { root.appendChild(el(root.ownerDocument, "del", "rv-del", old)); return { ins: 0, del: countWords(old) }; } return { ins: 0, del: 0 }; } return markNodes(nodes, String(old || "")); }
  function markAllNew(u) {
    apply(u.nodes, [[0, joined(u.nodes).text.length]], []);
    return countWords(u.text);
  }

  /* Where a ghost of removed text stands: as a row in a table, an item in a list, a block elsewhere. */
  function ghostFor(oldOwner, anchor, before, root) {
    var doc = root.ownerDocument, text = norm(oldOwner.text);
    var tr = anchor && anchor.closest("tr"), li = anchor && anchor.closest("li");
    var g, at;
    if (oldOwner.row && tr && root.contains(tr)) {
      g = el(doc, "tr", "rv-gone"); var td = el(doc, "td"); td.colSpan = Math.max(1, tr.cells.length); td.appendChild(el(doc, "del", "rv-del", text)); g.appendChild(td);
      at = tr;
      if (!before) { var nx = tr.nextElementSibling; while (nx && /\b(rdet|fdet)\b/.test(nx.className)) { at = nx; nx = nx.nextElementSibling; } }
    } else if (oldOwner.item && li && root.contains(li)) {
      g = el(doc, "li", "rv-gone"); g.appendChild(el(doc, "del", "rv-del", text)); at = li;
    } else {
      g = el(doc, "div", "rv-gone"); g.appendChild(el(doc, "del", "rv-del", text));
      at = anchor || null;
      while (at && at.parentElement && at.parentElement !== root && at.parentElement.matches("table, thead, tbody, tr, ul, ol, dl, .tablewrap, summary")) at = at.parentElement;
      if (at && at.matches("summary")) at = at.parentElement;
      if (at === root) at = null;
    }
    if (!at) { root.appendChild(g); return g; }
    if (before) at.parentNode.insertBefore(g, at); else at.parentNode.insertBefore(g, at.nextSibling);
    return g;
  }

  /* Every text block of now against old; keyed parts (o.keyed) are left to diffKeyed. */
  function markTree(now, old, o) {
    o = o || {};
    var A = units(old, o), B = units(now, o), c = { ins: 0, del: 0 };
    A.forEach(function (u) { u.row = !!u.owner.closest("tr"); u.item = !!u.owner.closest("li"); });
    var runs = diff(A.map(function (u) { return u.key; }), B.map(function (u) { return u.key; }), 4000)
      || [{ t: "-", a0: 0, a1: A.length, b0: 0, b1: 0 }, { t: "+", a0: A.length, a1: A.length, b0: 0, b1: B.length }];
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i];
      if (r.t === "=") continue;
      /* a hunk: the removals and insertions between two kept runs */
      var gone = [], added = [];
      while (i < runs.length && runs[i].t !== "=") { var h = runs[i]; if (h.t === "-") for (var a = h.a0; a < h.a1; a++) gone.push(A[a]); else for (var b = h.b0; b < h.b1; b++) added.push(B[b]); i++; }
      i--;
      var after = (runs[i + 1] && runs[i + 1].t === "=") ? B[runs[i + 1].b0] : null;
      /* pair a removed block with the inserted block it most resembles, in order */
      var pairs = [], used = {};
      gone.forEach(function (g, gi) {
        var best = -1, score = 0.34;
        added.forEach(function (n, ni) { if (used[ni]) return; if (pairs.length && ni < pairs[pairs.length - 1][1]) return; var s = similar(g.text, n.text); if (s > score) { score = s; best = ni; } });
        if (best >= 0) { used[best] = 1; pairs.push([gi, best]); }
      });
      var pairedGone = {}; pairs.forEach(function (p) { pairedGone[p[0]] = p[1]; });
      added.forEach(function (n, ni) {
        if (used[ni]) return;
        c.ins += markAllNew(n);
        var whole = textNodes(n.owner, o).length === n.nodes.length;
        if (whole && n.owner !== now) n.owner.classList.add("rv-addblk");
      });
      pairs.forEach(function (p) { var m = markNodes(added[p[1]].nodes, gone[p[0]].text); c.ins += m.ins; c.del += m.del; });
      /* ghosts: each removed block stands before the next block that is still here */
      var ghosts = [];
      gone.forEach(function (g, gi) {
        if (pairedGone[gi] !== undefined) return;
        var anchor = null, before = true;
        for (var k = gi + 1; k < gone.length && !anchor; k++) if (pairedGone[k] !== undefined) anchor = added[pairedGone[k]];
        if (!anchor) anchor = after;
        if (!anchor) { anchor = added.length ? added[added.length - 1] : (r.b0 > 0 ? B[r.b0 - 1] : null); before = false; }
        /* one ghost per removed row or list item: its cells join */
        var gkey = g.row ? g.owner.closest("tr") : g.item ? g.owner.closest("li") : g.owner;
        var hit = (g.row || g.item) ? ghosts.filter(function (x) { return x.key === gkey; })[0] : null;
        if (hit) hit.node.querySelector("del").appendChild(now.ownerDocument.createTextNode(" · " + norm(g.text)));
        else ghosts.push({ key: gkey, node: ghostFor(g, anchor && anchor.owner, before, now) });
        c.del += countWords(g.text);
      });
    }
    /* drawn diagrams keep their source in data-src: a changed one is marked as a whole */
    var srcs = function (root) { return [].slice.call(root.querySelectorAll(".diagram[data-src]")).map(function (d) { return d.getAttribute("data-src"); }); };
    var before = srcs(old);
    [].slice.call(now.querySelectorAll(".diagram[data-src]")).forEach(function (d) { if (before.indexOf(d.getAttribute("data-src")) < 0 && !skipped(d, now, o)) { d.classList.add("rv-chg"); c.ins++; } });
    return c;
  }

  /* Keyed parts first (o.keyed: a selector; o.keyOf(node): its key; o.titleOf(node): the fallback match), then the rest. */
  function tops(root, sel) { return [].slice.call(root.querySelectorAll(sel)).filter(function (n) { var p = n.parentElement; while (p && p !== root) { if (p.matches(sel)) return false; p = p.parentElement; } return true; }); }
  function diffKeyed(now, old, o) {
    var c = { ins: 0, del: 0 };
    if (!o.keyed) { var t = markTree(now, old, o); c.ins += t.ins; c.del += t.del; return c; }
    var N = tops(now, o.keyed), O = tops(old, o.keyed), match = new Map(), taken = new Set();
    var byKey = {}; O.forEach(function (x) { var k = o.keyOf(x); if (k != null && !byKey[k]) byKey[k] = x; });
    N.forEach(function (n) { var k = o.keyOf(n), x = k != null ? byKey[k] : null; if (x && !taken.has(x)) { match.set(n, x); taken.add(x); } });
    if (o.titleOf) N.forEach(function (n) {
      if (match.has(n)) return; var tt = norm(o.titleOf(n)); if (!tt) return;
      var x = O.filter(function (y) { return !taken.has(y) && norm(o.titleOf(y)) === tt; })[0]; if (x) { match.set(n, x); taken.add(x); }
    });
    var inner = Object.assign({}, o, { keyed: null });
    N.forEach(function (n) {
      var x = match.get(n);
      if (!x) { var w = countWords(textOf(n, inner)); c.ins += w; if (o.onNew) o.onNew(n, { ins: w, del: 0 }); return; }
      if (norm(textOf(n, inner)) === norm(textOf(x, inner)) && srcsEqual(n, x)) { if (o.onSame) o.onSame(n, x); return; }
      var sub = o.keyedInner ? diffKeyed(n, x, Object.assign({}, o, { keyed: o.keyedInner(n) })) : markTree(n, x, inner);
      c.ins += sub.ins; c.del += sub.del;
      if (o.onChanged) o.onChanged(n, sub, x);
    });
    /* gone: after the part that came before it in the old tree, or before the first part */
    O.forEach(function (x, i) {
      if (taken.has(x)) return;
      var w = countWords(textOf(x, inner)); c.del += w;
      var prev = null; for (var j = i - 1; j >= 0 && !prev; j--) { if (taken.has(O[j])) { match.forEach(function (ov, nv) { if (ov === O[j]) prev = nv; }); } }
      if (o.onRemoved) o.onRemoved(x, prev, N[0] || null, { ins: 0, del: w }, now);
    });
    var rest = markTree(now, old, o);
    c.ins += rest.ins; c.del += rest.del;
    return c;
  }
  function srcsEqual(a, b) {
    var s = function (r) { return [].slice.call(r.querySelectorAll(".diagram[data-src]")).map(function (d) { return d.getAttribute("data-src"); }).join("\u0000"); };
    return s(a) === s(b);
  }

  /* ---------- reading the changes ---------- */
  var STOP = ".rv-ins, .rv-del, .rv-gone, .rv-new, .rv-removed, .rv-addblk, .rv-chg.diagram, .rv-stop";
  function stops(root) {
    var out = [], lastOwner = null;
    [].slice.call(root.querySelectorAll(STOP)).forEach(function (n) {
      if (n.parentElement && n.parentElement.closest(".rv-new, .rv-removed, .rv-gone, .rv-addblk, .rv-stop")) return;
      if (n.closest("[hidden]")) return;
      var owner = n.matches(".rv-ins, .rv-del") ? (n.parentElement.closest(BLOCK) || n.parentElement) : n;
      if (owner === lastOwner) return;
      lastOwner = owner; out.push(owner);
    });
    return out;
  }
  function reveal(node) {
    var d = node.closest("details");
    while (d) { d.open = true; d = d.parentElement && d.parentElement.closest("details"); }
    var reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    try { node.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); } catch (e) { /* old browsers */ }
    node.classList.remove("rv-flash"); void node.offsetWidth; node.classList.add("rv-flash");
  }
  var PREF = "aidlc-rev:view";
  function pref() { try { return localStorage.getItem(PREF) === "clean" ? "clean" : "show"; } catch (e) { return "show"; } }
  function setPref(v) { try { localStorage.setItem(PREF, v === "clean" ? "clean" : "show"); } catch (e) { /* kept for this visit */ } }

  return { diff: diff, words: words, tokens: tokens, countWords: countWords, norm: norm, similar: similar, textOf: textOf,
    markText: markText, markTree: markTree, diffKeyed: diffKeyed, stops: stops, reveal: reveal, pref: pref, setPref: setPref };
})();
if (typeof module !== "undefined" && module.exports) module.exports = RevDiff;
