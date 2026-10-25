/* The ids an AI-DLC page shows (US1.1, AC1.1.2, FR1.4, NFR3, BR1.2, Q4, U31, C2, ADR-009, R-01, ...), each a link with
   a tooltip saying what it is. Shared: the canonical copy is shared/aidlc-ids/aidlc-ids.js in mskuibida-ai-tools,
   copied into every page by scripts/sync-shared.py. Edit it there.

   The page gives it a map of what each id is, `ids` = {"FR1.4": {kind, title, text, doc}}, the output of
   `aidlc_ids.py refs` written with the page's data, and marks each element that shows an id's own definition with
   data-aidlc-id="<id>". Then:

     AidlcIds.linkify(root, ids, { toast: fn })   turn every id in root's text into a link; run after each render
     AidlcIds.observe(root, getIds, { toast: fn }) the same, again whenever root's content changes

   A link whose id is shown in the page jumps there and flashes it. One that is not shown still looks like a link: its
   tooltip says what it is, and a click shows a toast that it is not in this page. An id no document defines says so.
   The tooltip is the page's own: the link carries data-tip and aria-label, which every page's tooltip reads. */
var AidlcIds = (function () {
  "use strict";
  var ID = /(^|[^\w-])([A-Z][A-Z]{0,4}-?\d+[a-z]?(?:[.-]\d+[a-z]?)*(?:-[A-Z]{1,4}\d+[a-z]?)?)(?![\w-])/g;
  var NOT_IDS = /^(UTF-?\d+|SHA-?\d+|ISO-?\d+|RFC-?\d+|HTTP-?\d+|TLS-?\d|H[1-6]|V\d+|X\d+|P\d|ES\d+|ID\d*)$/;
  var KINDS = { US: "Story", AC: "Acceptance criterion", FR: "Functional requirement", NFR: "Non-functional requirement",
    BR: "Business rule", Q: "Question", U: "Unit", C: "Contract", E: "External interface", ADR: "Decision record",
    R: "Review finding", D: "Decision", DR: "Design rule", S: "Screen", M: "Mockup", T: "Task" };
  var SKIP = "a, button, code, pre, script, style, textarea, input, select, option, [data-aidlc-noids]";

  function prefix(id) { return (/^[A-Z]+/.exec(id) || [""])[0]; }
  function docName(doc) { return String(doc || "").split("/").pop(); }

  function anchorOf(id) {
    var css = window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/["\\]/g, "\\$&");
    return document.querySelector('[data-aidlc-id="' + css + '"]');
  }

  /** The tooltip of an id: what it is, in plain words, and where it is written. */
  function tip(id, def) {
    if (!def) return id + ": not found in this project's documents.";
    var kind = def.kind || KINDS[prefix(id)] || "";
    var head = (kind ? kind + " " : "") + id + (def.title ? ": " + def.title : "");
    var body = def.text && def.text !== def.title ? " " + def.text : "";
    return head + (/[.!?…]$/.test(head) || !body ? "" : ".") + body + (def.doc ? " (" + docName(def.doc) + ")" : "");
  }

  /** Whether a word is an id this page knows of, or looks like one of a kind it knows. */
  function isId(word, ids, prefixes) {
    if (NOT_IDS.test(word)) return false;
    return Object.prototype.hasOwnProperty.call(ids, word) || prefixes[prefix(word)] === true;
  }

  function linkify(root, ids, opts) {
    if (!root) return;
    ids = ids || {};
    opts = opts || {};
    var prefixes = {};
    Object.keys(ids).forEach(function (k) { prefixes[prefix(k)] = true; });
    Object.keys(KINDS).forEach(function (k) { prefixes[k] = true; });
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue || !/[A-Z]-?\d/.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
        var p = n.parentElement;
        return p && !p.closest(SKIP) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var text = node.nodeValue, last = 0, frag = null, m;
      var own = node.parentElement.closest("[data-aidlc-id]");
      ID.lastIndex = 0;
      while ((m = ID.exec(text))) {
        var word = m[2], start = m.index + m[1].length;
        if (!isId(word, ids, prefixes) || (own && own.getAttribute("data-aidlc-id") === word)) continue;
        frag = frag || document.createDocumentFragment();
        frag.appendChild(document.createTextNode(text.slice(last, start)));
        var a = document.createElement("a");
        var def = ids[word];
        a.className = "aidlc-id" + (def ? "" : " aidlc-id-unknown");
        a.href = "#" + encodeURIComponent(word);
        a.textContent = word;
        a.setAttribute("data-aidlc-ref", word);
        a.setAttribute("data-tip", tip(word, def));
        a.setAttribute("aria-label", tip(word, def));
        frag.appendChild(a);
        last = start + word.length;
      }
      if (frag) {
        frag.appendChild(document.createTextNode(text.slice(last)));
        node.parentNode.replaceChild(frag, node);
      }
    });
    markLive(root);
    bind(root, opts);
  }

  /** Links whose id is shown in the page get the live look; the rest the out-of-page one. */
  function markLive(root) {
    Array.prototype.forEach.call(root.querySelectorAll("a.aidlc-id"), function (a) {
      a.classList.toggle("aidlc-id-out", !anchorOf(a.getAttribute("data-aidlc-ref")));
    });
  }

  function bind(root, opts) {
    if (root.__aidlcIds) { root.__aidlcIds.opts = opts; return; }
    root.__aidlcIds = { opts: opts };
    root.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a.aidlc-id");
      if (!a || !root.contains(a)) return;
      e.preventDefault();
      var id = a.getAttribute("data-aidlc-ref"), target = anchorOf(id);
      var say = root.__aidlcIds.opts.toast || function (t) { window.alert(t); };
      if (target) {
        var closed = target.closest("details:not([open])");
        if (closed) closed.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.remove("aidlc-flash");
        void target.offsetWidth;
        target.classList.add("aidlc-flash");
        if (target.tabIndex < 0 && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      } else if (a.classList.contains("aidlc-id-unknown")) {
        say(id + " isn't defined in this project's documents.");
      } else {
        say(id + " isn't in this page. What it is: in its tooltip.");
      }
    });
  }

  function observe(root, getIds, opts) {
    if (!root) return;
    var busy = false;
    var run = function () {
      if (busy) return;
      busy = true;
      try { linkify(root, getIds(), opts); } finally { busy = false; }
    };
    run();
    new MutationObserver(function () { if (!busy) window.requestAnimationFrame(run); })
      .observe(root, { childList: true, subtree: true, characterData: true });
  }

  return { linkify: linkify, observe: observe, tip: tip, KINDS: KINDS };
})();
