# approval-gates changelog

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
