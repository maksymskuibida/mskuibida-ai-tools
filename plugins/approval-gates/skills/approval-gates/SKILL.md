---
name: approval-gates
description: Use at every AI-DLC approval gate (and, at a unit-end gate answered Test first, for the test plan of its not-verified points: § 7). First read aidlc/.aidlc-unit-scope.json: for the Code Generation plan approval and the unit-end gate of a Unit claimed with gate_rhythm "unit-end" go straight to the unit-end flow (unit_bundle.py, a bundles/ row in "AI-DLC unit approvals"); every other gate follows the per-stage flow. Per-stage flow: right after `aidlc engine orchestrate report --result awaiting-approval` (or `--result revised`) and before the Approval question — publish the stage's documents as a page in the developer's "AI-DLC approval gates" artifact and send its link in a message of its own before the gate question. Also when the developer answered, to read the notes they left in the page.
---

# Approval gates

## 0. Decide the flow first — before anything else

There are two flows with different scripts, different rows and a different artifact. Read
`aidlc/.aidlc-unit-scope.json` in the project (the claim's stamp) and pick:

| The gate in hand | Flow |
|---|---|
| `"gate_rhythm": "unit-end"` **and** it is the Unit's Code Generation **plan approval** (Approve Plan) **or** its **unit-end gate** (`directive.unit_gate: "unit-end"`) | **Unit-end flow → § 5.** `unit_bundle.py`, a `bundles/<id>` row, the artifact **AI-DLC unit approvals**. Go straight there; do not read §§ 1–4 for it. |
| Any other gate: every gate of a `per-stage` Unit or of a project with no claim, and every design-stage gate of a unit-end Unit (the stages that run with no approval between them) | **Per-stage flow → §§ 1–4.** `gate_bundle.py`, a `gates/<id>` row, the artifact **AI-DLC approval gates**. |

A `gates/` row written for a unit-end Unit's plan approval or unit-end gate is the wrong page: the hook refuses
the write and says so. The hook's message at the gate names the flow too; when it and this table disagree, the
stamp wins.

## Per-stage flow

Every approval gate gets a page, always. The engine's gate stays exactly as the engine prescribes:
the completion message, then the Approval question with `AskUserQuestion`, then the end of your turn.
The page, `approval-gate.html` next to this file, is where the developer **reads** the stage's
documents, each in a view made for its kind, and may leave a note per document. The decision itself
is given in chat; the page holds none. Its header comment is the data contract. Never generate,
restyle or edit a page per stage.

## 1. The artifact (once per developer) — per-stage flow

`Artifact` → `action: "list"` → the artifact titled **AI-DLC approval gates**. If the developer
has none, publish `approval-gate.html` from this skill's directory once: `capabilities: {db: {}, user: {}}`,
`icon: "document"`, description "Read a stage's AI-DLC documents at its approval gate; notes come back
to Claude." Reuse its URL for every gate from then on. After a plugin update, republish the page from
this file to the same URL once, with `capabilities: {db: {}, user: {}}` (the `user` capability keeps each
viewer's read marks; an artifact published before 1.5.0 has only `db`): the rows stay.

## 2. At every per-stage gate

After the `awaiting-approval` (or `revised`) report, and after the review brief was printed when the
stage has a reviewer:

1. Write your Part-2 summary of the stage (Markdown) to a file in the scratchpad folder.
2. Build the rows. Inside a skill the plugin root is `${CLAUDE_PLUGIN_ROOT}`:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gate_bundle.py" --stage <slug> [--unit <u>] --why <first|revision|stale> \
     --summary-file <the summary file> --out <a folder in the scratchpad>
   ```
   Use `--why revision` after a Request Changes round, `stale` when the review was out of date, otherwise
   `first`. It prints `{"id", "stage", "unit", "documents", "writes", "batches", "round"}` and writes
   `writes.json` next to the rows. Without a path it reads the project from `$CLAUDE_PROJECT_DIR`.
   It also writes the gate's `ids`, what every id the page shows is: it runs the shared `aidlc_ids.py sync` (the
   checkout's id map, kept outside the project) and then `refs` over the summary, the brief and every document, with
   `--near` the stage's documents, so the page's Q1 and R-01 are this stage's and its BR1.1 this Unit's. Leave it as
   the script wrote it. A warning that the map could not be built leaves `ids` out; the page then links only the ids
   it shows itself.
   For the `build-and-test` stage the script also writes `buildTest` into the gate row: it reads the stage's tables
   (the Target Verification Matrix, the commands and results, coverage against its floor, the evidence legend) so the
   page shows a results strip, a filterable target matrix and a decision card per Not Met or Unverified target, with
   the instruction files folded under Reference. Nothing for you to do; when the tables are not found the field is left
   out and the page shows the stage like any other.
3. Send the rows with **one** `ArtifactData` `batch`: the `writes` array of `writes.json` as it is
   (`file_path` entries, no `if_version`, these are new rows). When the script says the writes do not
   fit one batch, send the files named in `batches`, in order. If a write is refused because the id exists,
   run the script again a minute later: an id is a time stamp.
4. Present the gate as the protocol says. The completion message gets the line
   `**Read:** <artifact url>#<id>` next to the `**Review:**` line; that message is where the link lives,
   and it is sent first: the guard refuses the question until a message of yours carries the link.
   Then ask the engine's question exactly as the protocol words it ("Delivery Planning complete. How
   would you like to proceed?"): no link, no URL and no gate id in the question text, so the dialog stays
   readable. The options stay the engine's. End the turn.

The plan checkpoint of Code Generation (Approve Plan) is a gate too: the same steps, with its
`code-generation-plan.md`.

## 3. After the answer

- `Approve`: the engine's approved report, as usual.
- **Build and Test only: the target picks.** Whatever the answer, `get` `gates/<id>` and read `targetPicks`
  (`{<target id>: {pick, note?}}`, written by the page: `accept`, `followup` or `fix`). Act on them with the answer:
  `fix` → the answer is Request Changes: name those targets (id and the developer's note) in the rejected report's
  `--reason` as what to fix; `followup` → record each in the stage's follow-up work (a follow-up line in the
  stage's summary or the project's follow-up list, with its note) and mention them in your next message; `accept` →
  record each as a known limit (a line in the summary's known limitations). A Not Met or Unverified target with no
  pick is undecided: say so in one line and ask in chat. Picks do not change the decision itself, which is the chat
  answer: when the developer approves but picked `fix` for something, say so and ask before approving past it.
- `Request Changes`: first `ArtifactData` `get` of `gates/<id>`. If `notes` holds anything, quote it
  (each note under its document's title) in the rejected report's `--reason`, together with what the
  developer typed in chat. If the page holds nothing and the chat answer has no feedback, ask what
  should change, as the protocol says.
- After the revision and the new review, the `revised` report opens a fresh gate: § 2 again, with a new id.

## 4. Never

Never write `notes` or `targetPicks` (they are the developer's) or any decision field (the decision is given in chat),
and never update a row: each presentation is a fresh id.

## 5. Unit-end flow: a Unit with the unit-end rhythm

*(You are here from § 0: the Unit's plan approval or its unit-end gate.)* A team Unit claimed with `--rhythm unit-end` (the claim's stamp `aidlc/.aidlc-unit-scope.json` says
`"gate_rhythm": "unit-end"`) stops for the developer twice, not once per stage: the design stages run with their
reviewer rounds and no approval between them, then the **plan page** at the Code Generation plan approval (the
developer's one look at every design stage), then the code, then the **unit-end page** at the Unit's one gate
(`directive.unit_gate: "unit-end"`). Each page is one gate bundle, a JSON file whose contract is
`contract/README.md` and `contract/gate-bundle.schema.json` in this plugin, rendered by `unit-gate.html` next to this
file. Under `per-stage`, everything above (§ 1 to § 4) applies unchanged.

**The artifact (once per developer).** `Artifact` → `action: "list"` → the artifact titled **AI-DLC unit
approvals**. If there is none, publish `unit-gate.html` once: `capabilities: {db: {}, user: {}}`, `icon: "checklist"`,
description "A Unit's plan and unit-end pages for AI-DLC; read here, answer in chat." Reuse its URL from then on, and
republish from this file to the same URL after a plugin update.

**At each of the two stops**, after the engine opened it (the hook tells you which page):

1. Draft: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/unit_bundle.py" draft --page plan|unit-end --unit <unit> --out <scratch>/bundle.json`.
   It reads the stage records and fills every row a script can find (answers, assumptions, open or waived reviewer
   findings and what in the plan settles each, the code plan's steps; on the unit-end page the code summary's
   deviations, what is not verified and what was built, and the approved plan page folded). It prints a `todo` list.
2. Do the `todo` list in the file. This is the judgment the page exists for:
   - **Label every row** by what it costs if it is wrong: `critical` wrong data, security, or hard to undo; `high`
     wrong behaviour the person would see; `medium` rework in this Unit; `low` cosmetic or internal. Rows of the
     unit-end `built` section are `core`, `main` or `minor`.
   - **Look first**: set `lookFirst` on the critical and high rows that are an assumption you made or a finding left
     open (on the unit-end page: a change or an unverified point the person must check).
   - **Plain words**: titles are one line; bodies say what it means for the person, not where it is written.
   - **Write the sections the records cannot give**: `narrows` (where the design narrows something already approved),
     `visible` (what people see, stored data, API/MCP shape, security, dependencies), `tests` (grouped, one row per
     group); on the unit-end page an empty `changes` section with `asApproved: true` when the design stays as approved,
     and a `map` of how the built pieces connect.
   - **References**: every id you mention gets a `{label, tip, target}`: `#<anchor>` inside the bundle,
     `path:<record>#<id>` for a record. The tip says what the reference says. Ids in any text (a title, a body, a
     sub-step) become links with tooltips on the page by themselves; write them where a reader needs them, plain words
     around them.
   - **A revision** (after Request Changes): the draft carries every row whose source did not change over as you left
     it. Write `revNote` on each row and step you changed ("Changed in v2: …", "New in v2: …") and one line in
     `header.revisions` for the new revision.
3. Finalize: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/unit_bundle.py" finalize --bundle <scratch>/bundle.json --out <scratch>/out`.
   It marks what changed since the last presentation, writes the bundle's `ids` (the shared `aidlc_ids.py sync`, then
   `refs` over every text of the bundle with `--near` the Unit's stage folders), validates the bundle, and refuses
   with one problem per line until it holds to the contract. Pass `--project-dir` when the project is not the working
   directory. Never edit `ids` by hand: run finalize again.
4. Write `writes.json` with one `ArtifactData` `batch`, send `**Read:** <artifact url>#<bundle id>` in a message of its
   own, then ask the engine's question as the protocol words it, with no link in it. End the turn. **At the unit-end
   gate** (not the plan approval) the question carries a third option, **Test first**, after Approve and Request
   Changes; see § 7.

**After the answer**, `ArtifactData` `get` of `bundles/<id>`: the page stores the developer's notes per row
(`notes.<row anchor>`) and their lean on a suggestion (`picks.<row anchor>`: `do` or `leave`). On Request Changes quote
them in the rejected report's `--reason` with the chat answer. On Approve with notes or picks present, say so in one line
and ask in chat whether to act on them; the decision is the chat answer. A Request Changes at the unit-end gate sends
the Unit's whole chain back for review (the engine floors every stage of the Unit); say so when the developer asks for
a small change that the plan page would have been the cheaper place for. Never write `notes` or `picks`.

## 7. Testing the not-verified points before the unit-end gate

On the unit-end page every row of "Not verified yet" has a **Test now / Later** pick (stored as `picks.<row anchor>` =
`now` or `later`). The developer can test those points through a guided test plan before approving. It starts two ways:
the developer answers the unit-end gate **Test first**, or types `/approval-gates:test-plan` at any time (the skill
`approval-gates:test-plan` holds the same steps). Test first is not Approve and not Request Changes: the gate stays open,
and the guard refuses the gate question again only until the page is republished after the testing. Per-stage gates have
no test plan.

1. **Which rows.** `ArtifactData` `get` of `bundles/<id>`, save its `picks` to a file, then
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_plan.py" now --bundle <the unit-end bundle.json> --picks-file <file>`.
   It prints the V rows to test: those picked Test now, or all of them when none is picked (then tell the developer
   that all are covered because none was picked).
2. **Write the plan** as JSON (`aidlc-test-plan/1`, contract/README.md): sections A, B, C … with steps A.1, A.2, B.1 …
   A new section starts wherever you must do something first (seed data, start a server, deploy, reset state). Each
   section has `agent` (what you will do) and the developer's steps, each with `do`, `expect` and `verifies` (the V
   rows). Run `test_plan.py publish --plan <file> --bundle <bundle.json> --out <scratch>`; it refuses with one problem
   per line until every id, step shape and Test-now row coverage holds.
3. **The artifact (once per developer).** `Artifact` → `action: "list"` → **AI-DLC test plans**. If none, publish
   `test-plan.html` once: `capabilities: {db: {}, user: {}}`, `icon: "checklist"`, description "Steps to check a Unit's
   not-verified points; Pass or Fail each, notes come back to Claude." Reuse its URL; republish from the file after a
   plugin update. Write the plan's `writes.json` with one `ArtifactData` batch (a `plans/<id>` row).
4. **Drive it in chat.** Send `**Read:** <artifact url>#<plan id>` in a message of its own. In the same response ask
   (`AskUserQuestion`, header "Test plan"): **Do the agent step for A** / **Change the plan**.
   - *Change the plan*: ask what to change, revise the plan (a new id, `-test-v2-`), publish it again, send the link, ask again.
   - *Do the agent step for A*: do it, then `ArtifactData` `update` of `plans/<id>` with `agentDone` (all keys done so
     far); the developer's steps for the section open on the page. Ask a one-button question: **Section A completed, go
     on**. For the last section the button is **Test plan completed**.
   - On every button, first `ArtifactData` `get` of `plans/<id>` and read `results`. A step without a result, or a
     section the developer has not finished, is said in one line and asked again; never go on past it. After
     "Section A completed, go on", do the agent step of B the same way. Never write `results` (the page does).
5. **After the last section.** Save `results` to a file and run `test_plan.py finish --plan <file> --results <file>
   --bundle <bundle.json>`: it writes `test-plan.md` (plan, each step's result, notes, date) and `test-plan.json` into
   the Unit's code-generation stage folder.
   - **No failed steps** → go to step 6.
   - **Failed steps** → ask which to fix. One or two: one `AskUserQuestion` per failed step (Fix / Leave as known), the
     step and the developer's Fail note in the question text. Three or more: one form per the `question-forms` skill,
     one question per failed step (options Fix / Leave as known, the Fail note as the question's context). Then run
     `finish` again with `--fix <the step ids to fix>` (or `--fix none`).
     - **Nothing to fix** → step 6; the left failures show as *Failed, left as known*.
     - **Something to fix** → answer the unit-end gate with Request Changes through the engine's normal rejected
       report, with the picked failures and their notes in `--reason` (the Unit's whole chain goes back for review;
       say so), then fix them. The unit-end page that follows is built again with `--tested` (step 6), so the left
       failures stay listed.
6. **Back to the gate.** `unit_bundle.py draft --page unit-end --unit <unit> --tested <stage folder>/test-plan.json
   --out <scratch>/bundle.json`, then the todo list and `finalize` as in § 5. The page splits the not-verified section:
   *Verified by you* (passed), *Still not verified* (picked Later, or failed and being fixed), *Failed, left as known*.
   Write the row, send the link in a message of its own, and ask the unit-end gate question again (Approve / Request
   Changes / Test first).

## 6. The guard

`hooks/gate_guard.py` refuses the Approval question and the approved, rejected or accepted report until
a `gates` row for the stage (under the unit-end rhythm: the `bundles` row of the page the gate needs) was written in this session after the gate was opened and a message of yours
(in the session's transcript) carries its link `<artifact url>#<id>`, and refuses a question that carries
the link itself: the link goes in a message of its own. Send it as a text block and make the AskUserQuestion call in that same response; never end the turn on the link alone (a Stop hook catches it once). The plan approval counts as open as soon as the engine asks for it (the active
directive is an `ask` with `ask_type: "plan-approval"`), and any question offering Approve Plan, Approve or Accept
as-is while a gate is open is guarded, whatever its header. The developer clears it with `/approval-gates:release`.

The answer Test first at the unit-end gate counts as neither approval nor rejection: the gate stays open, and the
question is refused again only until a unit-end page newer than the answer is written. The rejected report still goes
through, for the fixes picked after a test. Writes to `plans/` rows may not carry `results` (the developer's).
