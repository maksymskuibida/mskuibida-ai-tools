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
     RevDiff.attributeText(texts, rounds)  the latest text of a chain of rounds as [{r, s}]: r is the round that last wrote s
     RevDiff.attributeTree(now, olds, rounds, o)  the same on a tree: marks each round's words and blocks in its colour
     RevDiff.unmark(root)           take the Changes marks off a tree again
     RevDiff.legend(rounds, counts, only) / only(root, k) / toggleOnly(root, btn, cur)  the legend chips and their filter
     RevDiff.stops(root)             the changes in reading order, one stop per block, for next / previous
     RevDiff.reveal(node)            open every <details> around node, scroll to it and flash it
     RevDiff.pref() / setPref(v)     "show" | "clean" (the default): the viewer's choice, kept in this browser
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
      ins.forEach(function (r) { var a = Math.max(r[0], start), b = Math.min(r[1], end); if (a < b) cuts.push({ at: a - start, to: b - start, ins: true, cls: r[2] }); });
      /* a removal in the space joined() put between two nodes goes at the start of the second */
      dels.forEach(function (d) { if ((d[0] >= start && d[0] < end) || (d[0] >= gap && d[0] < start) || (last && d[0] >= end) || (d[0] === start && start === end)) cuts.push({ at: Math.min(Math.max(d[0] - start, 0), s.length), del: d[1] }); });
      if (!cuts.length) return;
      cuts.sort(function (x, y) { return x.at - y.at || (x.del ? -1 : 1); });
      var doc = n.ownerDocument, frag = doc.createDocumentFragment(), p = 0;
      cuts.forEach(function (c) {
        if (c.at > p) { frag.appendChild(doc.createTextNode(s.slice(p, c.at))); p = c.at; }
        if (c.del != null) frag.appendChild(el(doc, "del", "rv-del", c.del));
        else { frag.appendChild(el(doc, "ins", c.cls || "rv-ins", s.slice(c.at, c.to))); p = c.to; }
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

  /* Pair each removed block with the added block it most resembles, in order: {pairs: [[gi, ni]], used: {ni: 1}}. */
  function pairUp(gone, added) {
    var pairs = [], used = {};
    gone.forEach(function (g, gi) {
      var best = -1, score = 0.34;
      added.forEach(function (n, ni) { if (used[ni]) return; if (pairs.length && ni < pairs[pairs.length - 1][1]) return; var s = similar(g.text, n.text); if (s > score) { score = s; best = ni; } });
      if (best >= 0) { used[best] = 1; pairs.push([gi, best]); }
    });
    return { pairs: pairs, used: used };
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
      var pr = pairUp(gone, added), pairs = pr.pairs, used = pr.used;
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


  /* ---------- which round changed what (Clean view) ----------
     Round k's changes are the difference between round k-1 and round k, folded forward onto the latest text: a word
     keeps the round that last wrote it, so where a later round changed the same words or block again, the later round
     wins. Rounds are numbers (2, 3, ...); 0 is the first round the text appeared in, which is not coloured. */
  var TONES = 4;
  function tone(k) { return ((Math.max(2, k) - 2) % TONES) + 2; }
  var isSpace = function (t) { return /^\s+$/.test(t); };
  /* The tokens of text with the round that wrote each one, given the tokens and rounds of the text before it (null when
     there was none: everything is then written by round). */
  function carry(prev, text, round) {
    var toks = tokens(text), tags = new Array(toks.length), i;
    var runs = prev ? diff(prev.toks.map(keyOf), toks.map(keyOf), 4000) : null;
    if (!runs) { for (i = 0; i < toks.length; i++) tags[i] = round; }
    else {
      runs.forEach(function (r, ri) {
        var j;
        if (r.t === "+") { for (j = r.b0; j < r.b1; j++) tags[j] = round; }
        else if (r.t === "=") {
          var kept = toks.slice(r.b0, r.b1).join("");
          /* a short run kept between two changes (a space, a comma, one short word) is part of the change */
          var between = ri > 0 && ri < runs.length - 1 && (/^\s*$/.test(kept) || (kept.length <= 3 && !/\s/.test(kept.trim())));
          for (j = r.b0; j < r.b1; j++) tags[j] = between ? round : prev.tags[r.a0 + (j - r.b0)];
        }
      });
    }
    /* a space between two words written by the same round belongs to it */
    for (i = 1; i < toks.length - 1; i++) if (isSpace(toks[i]) && tags[i - 1] === tags[i + 1]) tags[i] = tags[i - 1];
    return { toks: toks, tags: tags };
  }
  function segmentsOf(c) {
    var out = [];
    c.toks.forEach(function (t, i) { var last = out[out.length - 1]; if (last && last.r === c.tags[i]) last.s += t; else out.push({ r: c.tags[i], s: t }); });
    return out;
  }
  /* The latest text of a chain of texts (oldest first, null where a round had none) as [{r, s}]: r is the round that
     wrote s, 0 for the first round. rounds[i] is the round number of texts[i]. */
  function attributeText(texts, rounds) {
    var prev = null;
    texts.forEach(function (t, i) { if (t == null) { prev = null; return; } prev = carry(prev, t, i === 0 ? 0 : rounds[i]); });
    return prev ? segmentsOf(prev) : [];
  }
  /* The tree now against the trees before it (olds[i] has round rounds[i], null where that round did not have this part;
     the last of rounds is now's): words last written by a later round are wrapped in <ins class="rv-r rv-rK rv-tT">, a
     block written whole by one round gets that class itself. Returns {words: {round: n}, blocks: {round: n}}. */
  function attributeTree(now, olds, rounds, o) {
    o = o || {};
    var prev = null, n = rounds.length, out = { words: {}, blocks: {} };
    for (var i = 0; i < n; i++) {
      var root = i === n - 1 ? now : olds[i];
      if (!root) { prev = null; continue; }
      var B = units(root, o), base = i === 0 ? 0 : rounds[i];
      if (!prev) B.forEach(function (u) { var c = carry(null, u.text, base); u.toks = c.toks; u.tags = c.tags; u.block = base; });
      else {
        var runs = diff(prev.map(function (u) { return u.key; }), B.map(function (u) { return u.key; }), 4000)
          || [{ t: "-", a0: 0, a1: prev.length, b0: 0, b1: 0 }, { t: "+", a0: prev.length, a1: prev.length, b0: 0, b1: B.length }];
        var settle = function (u, from) { var c = carry(from, u.text, rounds[i]); u.toks = c.toks; u.tags = c.tags; u.block = from ? from.block : rounds[i]; };
        for (var r = 0; r < runs.length; r++) {
          var h = runs[r];
          if (h.t === "=") { for (var j = 0; j < h.b1 - h.b0; j++) settle(B[h.b0 + j], prev[h.a0 + j]); continue; }
          var gone = [], added = [];
          while (r < runs.length && runs[r].t !== "=") { var x = runs[r]; if (x.t === "-") for (var a = x.a0; a < x.a1; a++) gone.push(prev[a]); else for (var b = x.b0; b < x.b1; b++) added.push(B[b]); r++; }
          r--;
          var pr = pairUp(gone, added);
          pr.pairs.forEach(function (p) { settle(added[p[1]], gone[p[0]]); });
          added.forEach(function (u, ni) { if (!pr.used[ni]) settle(u, null); });
        }
      }
      prev = B;
    }
    (prev || []).forEach(function (u) {
      var whole = u.owner !== now && textNodes(u.owner, o).length === u.nodes.length, skip = -1, pos = 0, ranges = [];
      if (u.block > 0 && whole) { u.owner.classList.add("rv-rb", "rv-r" + u.block, "rv-t" + tone(u.block)); skip = u.block; out.blocks[u.block] = (out.blocks[u.block] || 0) + 1; }
      u.toks.forEach(function (t, k) {
        var tag = u.tags[k], last = ranges[ranges.length - 1];
        if (IS_WORD.test(t) && tag > 0) out.words[tag] = (out.words[tag] || 0) + 1;
        if (tag > 0 && tag !== skip) {
          if (last && last.tag === tag && last[1] === pos) last[1] = pos + t.length;
          else ranges.push(Object.assign([pos, pos + t.length, "rv-r rv-r" + tag + " rv-t" + tone(tag)], { tag: tag }));
        }
        pos += t.length;
      });
      if (ranges.length) apply(u.nodes, ranges.filter(function (q) { return joined(u.nodes).text.slice(q[0], q[1]).trim(); }), []);
    });
    return out;
  }
  /* Take the word-level marks of the Changes view (and any colours) off a tree, so the text reads as it was drawn. */
  function unmark(root) {
    var seen = [];
    [].slice.call(root.querySelectorAll("ins.rv-ins, ins.rv-r")).forEach(function (n) {
      var p = n.parentNode; while (n.firstChild) p.insertBefore(n.firstChild, n); p.removeChild(n); if (seen.indexOf(p) < 0) seen.push(p);
    });
    [].slice.call(root.querySelectorAll("del.rv-del")).forEach(function (n) {
      if (n.closest(".rv-gone, .rv-removed")) return;
      var p = n.parentNode; p.removeChild(n); if (seen.indexOf(p) < 0) seen.push(p);
    });
    seen.forEach(function (p) { p.normalize(); });
    [].slice.call(root.querySelectorAll(".rv-rb")).forEach(function (n) { n.className = n.className.replace(/\brv-(rb|dim|r\d+|t\d+)\b/g, "").replace(/\s+/g, " ").trim(); });
  }
  /* The legend of rounds: a chip each, with the words that round last wrote; a click shows only that round's colour. */
  function legend(rounds, counts, only) {
    return '<span class="rv-legend" role="group" aria-label="Changes by version">' + rounds.map(function (k) {
      var w = counts && counts[k] || 0;
      return '<button type="button" class="rv-chip rv-t' + tone(k) + '" data-rvonly="' + k + '" aria-pressed="' + (only === k) + '"><i aria-hidden="true"></i>v' + k + (w ? '<span class="n">' + w + "</span>" : "") + "</button>";
    }).join("") + "</span>";
  }
  /* Dim every colour but round k's (k = 0: none dimmed). */
  function only(root, k) {
    [].slice.call(root.querySelectorAll(".rv-r, .rv-rb")).forEach(function (n) { n.classList.toggle("rv-dim", !!k && !n.classList.contains("rv-r" + k)); });
  }
  /* A click on a legend chip: the round now shown alone (0 when the same chip is clicked again). */
  function toggleOnly(root, btn, current) {
    var k = +btn.getAttribute("data-rvonly"); k = k === current ? 0 : k;
    only(root, k);
    [].slice.call(btn.parentElement.querySelectorAll("[data-rvonly]")).forEach(function (b) { b.setAttribute("aria-pressed", String(+b.getAttribute("data-rvonly") === k)); });
    return k;
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
  function pref() { try { return localStorage.getItem(PREF) === "show" ? "show" : "clean"; } catch (e) { return "clean"; } }
  function setPref(v) { try { localStorage.setItem(PREF, v === "show" ? "show" : "clean"); } catch (e) { /* kept for this visit */ } }

  return { diff: diff, words: words, tokens: tokens, countWords: countWords, norm: norm, similar: similar, textOf: textOf,
    markText: markText, markTree: markTree, attributeText: attributeText, attributeTree: attributeTree, unmark: unmark, legend: legend, only: only, toggleOnly: toggleOnly, tone: tone, diffKeyed: diffKeyed, stops: stops, reveal: reveal, pref: pref, setPref: setPref };
})();
if (typeof module !== "undefined" && module.exports) module.exports = RevDiff;
