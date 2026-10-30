---
name: test-plan
description: Use when the developer types `/approval-gates:test-plan`, or answered Test first at an AI-DLC unit-end gate — write a test plan from the unit-end page's not-verified points, publish it in the "AI-DLC test plans" artifact, drive it section by section in chat, write the results to test-plan.md, and return to the unit-end gate (or fix the failures).
---

# Test plan

The developer wants to test the unit-end page's "Not verified yet" points before approving the Unit. The full procedure is
**§ 7 of the `approval-gates` skill** (`skills/approval-gates/SKILL.md` in this plugin); follow it step by step. In short:

1. Find the Unit's newest unit-end page (the `bundles/<id>` row in **AI-DLC unit approvals**; its bundle file is in the
   bundle store, `unit-end-latest.json`, or in the scratch folder of the page you built). Read its `picks`
   (`test_plan.py now`): the rows picked **Test now**, or all of them (say so) when none is.
2. Write the plan: sections A, B, C … (a new section wherever you must do something first), each with your agent step
   and the developer's steps (`do`, `expect`, the V rows it `verifies`). `test_plan.py publish` validates it.
3. Publish the plan in the **AI-DLC test plans** artifact (once per developer, `test-plan.html`, `capabilities:
   {db: {}, user: {}}`), send its link as a text block in a message of its own (a hook refuses every question until it is sent) and, in the same response, ask **Do the agent step for A** /
   **Change the plan**.
4. After each agent step: set `agentDone`, ask **Section A completed, go on** / **Change the plan**; after the last, **Test plan completed** / **Change the plan**
   (a question has at least two options). Read the page's results with `ArtifactData` before moving on.
5. `test_plan.py finish` writes `test-plan.md` into the Unit's code-generation stage folder. No fails → republish the
   unit-end page with `unit_bundle.py draft --tested` and ask the gate again. Fails → ask which to fix (an inline
   question for one or two; a `question-forms` form for more); nothing to fix → the gate as above, with the failures
   listed as left as known; something to fix → Request Changes through the engine's rejected report with those failures
   and their notes in `--reason`.

Started with no unit-end page yet (the Unit is not built, or the gate has not opened): say so and stop; there is nothing
to test. Per-stage gates and the plan page have no test plan.
