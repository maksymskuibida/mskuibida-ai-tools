# approval-gates changelog

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
