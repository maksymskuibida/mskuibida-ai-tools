# approval-gates changelog

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
