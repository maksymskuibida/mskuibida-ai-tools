# approval-gates changelog

## 1.35.1

Fix round 2 of the pages (marketplace 1.57.0): the 16 minor findings of a second on-screen review. The look stays; the experience improves.
Templates changed: `approval-gate.html`, `unit-gate.html`, `maps.html`, the shared `gate-viz`; `scripts/judgment.py`; preview `dev/preview*.py`.

- **The bar says what is compared.** The Rounds control reads "Round 3 vs 2" ("r3 vs r2" on a phone), in the round's colour, on the per-stage
  page, the Unit pages and the maps page (a tag in the maps bar); the bar keeps its height. The first filter pill is "All", with no count.
- **View and actions.** The menu button says what it holds; its Actions row labels Expand all, Collapse all and Mark all read, and a Keys row
  lists n, u, j and k, ? and Esc; pressing ? opens it.
- **Nothing twice.** An opened item's "As written" leaves out the first line its header sentence already says; the same reference is one chip;
  a note is listed once in Your answer (with its pick, or under Notes when it has none).
- **Counts agree.** The Needs you chip counts what waits; a row settled just now stays in place marked Done and is not counted. The header's
  changed / new split is the rows' tags (a row new since the round compared with is tagged "new", whatever round last touched it).
- **One rule for picks.** Do it / Leave it mark the row read, as Test now / Later and the per-stage picks already did.
- **Disclosures and diagrams.** The traceability disclosure opens to the per-id trace, never to its own header again; a diagram wider than its
  frame has a fade, a visible scrollbar and a note; "How the pieces connect" wraps onto lines, labels are whole (cut at a word with an ellipsis
  and a title), and under three pieces it is not drawn.
- **Smaller.** The "What you asked for" card is sized by its text on a phone; a criterion's read dot is named "Mark read: <text>, <verdict>";
  the "Seen, will answer in chat" action sits at the foot of its tile; `judgment.py` names a decision whose summary is only its topic;
  the preview hands the pages whole sentences.

## 1.35.0

Fix round 1 of the pages' rework, for the per-stage page, the Unit pages and the test plan page (`approval-gate.html`,
`unit-gate.html`, `test-plan.html`, the shared `gate-viz`; `maps.html` is not touched). What a first on-screen review of 83 mock pages
found: the look stays, the experience changes. Every number below is the page's own, drawn once.

- **Round changes are always visible, in Clean too.** Every changed, new or removed thing carries a small round tag ("v3 changed",
  "v3 new", "v3 removed", "was Met" on a target whose verdict moved) in the round's colour; removed things are listed where they were,
  struck, in both views. The banner never says "Changes are hidden". The Changed filter shows exactly the changed, new and removed things
  and never drops a block that has changes (the code plan's steps included) or leaves an empty one. The Changed pill, the banner, the
  round timeline and the list of changes read one count; a Unit page compares with its first round by default (a row carries the round
  that last changed it), the Rounds menu picks a later one.
- **Nothing twice.** A record whose targets table became the matrix draws its other sections only (every such table is cut, once per
  Unit); a target named in another record's table links to its matrix row; the ledger names a target by id; an opened item lists no id its
  own text already shows, and says its title once; a criterion does not repeat its title; the criteria bars (the third copy of the same
  counts) are gone.
- **No empty shells.** An items block with no items is not drawn (its traceability line sits at the foot of the evaluation). Units Generation's
  Units are items (`digest.py`: `U<n>` headings, bullets and tables of `unit-of-work.md`, nowhere else); "stories", not "storys".
- **Text / View / Diagram, Changes / Clean never close anything**: every block and section stays as it was, the control stays under the
  pointer, and the record's own view is built, hidden, under a diagram so the read totals do not move.
- **One sticky bar** on the per-stage and the Unit pages: one row at 48 px on a wide screen, at most two to three short rows (98 px) on a
  phone. All / Needs you / Unread / Changed and the readiness counter; Rounds (the timeline and the round to compare with), Sections (Unit
  pages) or Outline (per-stage), and View (Summary | Full, Changes | Clean, Look first, High and critical, Expand all, Collapse all, Mark all
  read) open as menus. The jump chips and "Read x/y" are gone (the counter holds the unread count); every control has a tooltip.
- **Phone**: the Why first paragraph no longer inherits the document chip's `nowrap` (it pushed the page 178 px sideways); a row's sentence
  keeps its width and its tags wrap under it; outline labels wrap.
- **Unit pages open in Summary**; Do it / Leave it sit on the row's own line; "Your answer" lists a note the moment it is written; the
  tiles are numbers the page can show (Look first = what the filter shows, no Steps tile without a plan); a design row's id is no link to a
  verification row; the list marks the current page and mutes the replaced ones with their row counts.
- **Readiness is honest**: something tagged not handled, not met or failing is not settled by being read. It stays in Needs you ("N to
  look at") until the person presses "Seen, will answer in chat" on it; Ready to answer shows only then.
- **Each evaluation card is its own element** with its own read mark; "N to look at first" clears as each card is read.
- **One vocabulary** (round) and English dates (never the browser's locale inside English text).
- **The trace diagram** orders by id (US2.1 before US10.1) and sweeps to untangle; above 10 boxes a column or 36 links it is offered per
  requirement (pick one, see its chain).
- **Test plan page**: the others' width (1180 px), header with an "All plans" link and a status chip, a sticky progress strip with "Next
  step to do", a closing band, no scroll jump on load, visible focus on the Pass / Fail buttons.
- Smaller: a "sources disagree" tag has its own space under the verdict; a heat cell pressed twice clears and a filtered list says
  "Showing n of 48 · Clear filters"; under Unread the target strip leaves when nothing in it is unread; a Reject without a reason is
  "Reject, reason missing" in Your answer; read dots are named by what they mark; tooltips never show markdown table source; no anchor hash
  in a list of changes; Records opens (and says so) on a stage whose files are its content; the "Your answer" block no longer inherits an
  old inline-answer style.
- `dev/preview.py`: a scenario starts at round 1 (the audit is cleared between scenarios); summaries read like an agent's; a Unit
  page's tiles are computed; suggestion rows; the list view holds plan and unit-end pages; gate rows carry links to the maps; a gate of
  the Ideation phase with open decisions (84 pages).
- Tests: `test_fix1_pages.py` (one class per decision) and `drive_fix1.js`; the older drivers read the readiness counter and the blocks
  instead of the jump chips.

## 1.34.0

Fix round 1 for the maps page (`maps.html`): the look stays, the experience changes so a person can use the Unit map to decide what
to build next. Only the maps page, its tests and the maps scenarios of `dev/preview.py` changed.

- **The whole map fits at a glance.** The graph opens in Fit: compact cards (id and a state mark, no summary line), every wave or
  layer in view at 1440 and at 1100 without sideways scrolling. A long wave wraps into several columns; when the width asks for it
  the waves wrap into bands (the 13-layer component map is two bands). Each wave header carries a progress bar of what landed.
  Fit / Comfortable switches to today's full cards, which scroll. The side panel is a 44px rail until a block is picked and never
  more than a third of the width; the layout is made for that width either way, so picking a block never moves the cards.
- **What can I build next.** A Unit whose needs have all landed and that has not landed (nor is being built) is marked **Ready** on
  its card; a Ready now chip in the bar lights only those; the stats line says "n ready". The panel says in words (Ready to start /
  Not ready yet, waiting for ...) and marks each need and each block waiting for it as landed, being built or planned, with
  "1 of 2 landed".
- **Edges you can follow.** The picked block's edges are routed orthogonally in the gutters between columns and the gaps between
  rows, never over a card (same-wave edges go through the gutter), with arrowheads and lanes so they do not overlap. "Show every
  edge" is gone: 80 edges in 7 gutters cannot be made legible, so pointing at (or focusing) a block now previews its edges.
- **Stories and Entities.** They open as a grouped list (a story and its Units as chips, an entity and its components), gaps first,
  with a Gaps only chip carrying the count and a line saying when there are none. The matrix is the other view, offered only when
  it shows something (a gap, or rows and columns that each hold several dots); on a phone only the list is offered. The matrix has
  a legend, column headers that stay visible under the sticky bar, and Only changes since r<n> now leaves out the rows and columns
  that did not change, marks a link that is gone with a struck cross, and the round strip's counts agree with what is listed.
- **One sticky tools row, at most 64px at 1440 and 110px at 390.** Title and stats scroll away; the row holds the map kind switch,
  search, Groups (a menu from four groups up), Ready now, Gaps only, Only changes, Graph / List, Fit / Comfortable and Legend.
  Every control has a tooltip. At phone width the Graph/List and Fit switches are gone (only the list exists there).
- **One colour language with the gate pages.** Landed is a quiet filled tick; new and changed wear the colour of the round they
  came in (`--r2..--r5`) in the same `tag` shape as a gate page, and the word is "round". A Legend button is always one press away.
  The panel's change lines no longer share a class with the tag.
- Typing in the search lets go of the pick (the two no longer fight). One tab stop for the whole graph (arrows move it), no id link
  inside a card (it is in the panel), `/` and the arrows are written in the search box and the legend. Plurals are words (stories,
  entities). Preview data: Unit names and summaries are whole sentences, and some later Units rest only on landed work.

## 1.33.1

The Approval question is no longer refused on the first try at nearly every gate. The check never cared where the link sits; the
texts did. Now they say what the check does.

- Every refusal, hint and Stop reason asks for the page's link anywhere in the text written before the question (first, middle or
  last line; plain or as a markdown link), in the same response as the question. No "first line", no "nothing else on that line".
- The refusal shows its evidence: how many visible text blocks since the developer's last message, that none holds the link, and
  whether the words before the question were thinking, or the link was only in hook context, a tool result or after the question.
  It ends with "Nothing will make this pass later; write the link as text now."
- The note written after a `gates/`, `bundles/` or `plans/` row says the developer has NOT seen the link (hook notes, tool results
  and thinking are invisible to them) and gives a one-line example, `Page: <link>`.
- Not shipped: showing the link from the hook itself through `systemMessage`. The hooks documentation calls it a warning shown to
  the user but does not say that the desktop app or the CLI display it for PreToolUse, or for an allowed AskUserQuestion.

## 1.33.0

Batch 4 of the pages' rework: better presentation of the records, with visuals. Pages changed: `approval-gate.html`, `unit-gate.html`
(`maps.html`, `test-plan.html` and the rows' read keys are unchanged).

- Diagram view of a record (Text / Diagram switch, remembered per viewer): a trace ribbon, a layered diagram, sequence and state
  diagrams, a numbered flow, and every mermaid block drawn by the page itself (the mermaid library is gone). Derived in
  `scripts/diagrams.py`, stored in the gate row (`diagrams`).
- Target heat grid, verification funnel, round timeline (replaces the legend chips), plan steps as lanes, criteria dots.
- Long text: a file's outline, tables that scroll in their own frame with a sticky first column, prose at about 76 characters.
- `dev/preview.py`: every page and scenario with synthetic data, to look at without an account.
- Contract: gate rows may carry `diagrams`; the unit-end bundle may carry `verification {auto}`. `gate_bundle.py` finds
  stage folders of the initialization phase too.

## 1.32.0

Project maps (the AI-DLC maps artifact), required at the gates that settle components and Units.

## 1.31.0

Needs you as a filter, a readiness counter, Your answer, one Records block.

## 1.30.0

One list of targets, a read mark for every thing, round changes on every block.
