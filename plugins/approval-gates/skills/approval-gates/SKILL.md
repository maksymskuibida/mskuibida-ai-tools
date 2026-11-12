---
name: approval-gates
description: Use at every AI-DLC approval gate (and, at a unit-end gate answered Test first, for the test plan of its not-verified points: § 7). First read aidlc/.aidlc-unit-scope.json: for the Code Generation plan approval and the unit-end gate of a Unit claimed with gate_rhythm "unit-end" go straight to the unit-end flow (unit_bundle.py, a bundles/ row in "AI-DLC unit approvals"); every other gate follows the per-stage flow. At the gates that settle the components and the Units, and at a Unit's end, build the project map first (§ 8; map_bundle.py, a maps/ row in "AI-DLC maps"): the guard refuses the question without a current one. Per-stage flow: right after `aidlc engine orchestrate report --result awaiting-approval` (or `--result revised`) and before the Approval question — draft the stage's page, judge the stage against its rules in judgment.json (the evaluation, every criterion, a one-sentence summary and label per item), finalize, publish it in the developer's "AI-DLC approval gates" artifact and send its link in a message of its own before the gate question. Also when the review brief is printed with open findings (no Findings question: fix what is certain, put the rest on the gate page as cards the developer sorts), and when the developer answered, to read the notes and the finding sort they left in the page.
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
The page, `approval-gate.html` next to this file, is where the developer **reads your evaluation of the stage** and
every item in plain words, opens what they want as written, and may leave a note per document. The decision itself
is given in chat; the page holds none. Its header comment is the data contract. Never generate,
restyle or edit a page per stage.

## 1. The artifact (once per developer) — per-stage flow

`Artifact` → `action: "list"` → the artifact titled **AI-DLC approval gates**. If the developer
has none, publish `approval-gate.html` from this skill's directory once: `capabilities: {db: {}, user: {}}`,
`icon: "document"`, description "Read a stage's AI-DLC documents at its approval gate; notes come back
to Claude." Reuse its URL for every gate from then on. After a plugin update, republish the page from
this file to the same URL once, with `capabilities: {db: {}, user: {}}` (the `user` capability keeps each
viewer's read marks; an artifact published before 1.5.0 has only `db`): the rows stay.

## 2. At every per-stage gate: draft, judge, finalize, publish

The page leads with **your evaluation of the stage**, not with its documents split into lines. A script gathers what the
stage is judged against and drafts the rows; you do the judging; a second script refuses the row until every part of the
judgment is there. Max reads the page in minutes: what approving decides, what to look at first and why, then every item
in one plain sentence. After the `awaiting-approval` (or `revised`) report, and after the review brief was printed when
the stage has a reviewer:

1. **Summary.** Write your Part-2 summary of the stage (Markdown) to a file in the scratchpad folder. The page folds it
   under the evaluation.
2. **Draft.** Inside a skill the plugin root is `${CLAUDE_PLUGIN_ROOT}`:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gate_bundle.py" draft --stage <slug> [--unit <u>] --why <first|revision|stale> \
     --summary-file <the summary file> [--findings <file>] [--handling <file>] --out <a folder in the scratchpad>
   ```
   Use `--why revision` after a Request Changes round, `stale` when the review was out of date, otherwise `first`.
   It writes into the folder the draft row (`gate.json`), the documents, **`criteria.json`** and **`judgment.json`**, and
   prints `{"id", "documents", "round", "judgment", "criteria", "items", "todo", "next"}`. It never writes `writes.json`:
   there is nothing to send until you judged the stage.
   - `criteria.json` is what the stage is judged against, each with its full text and source: the engine's definition of
     the stage (`stage-N`: its Constraints and what each file it writes must hold), the reviewer's checklist
     (`review-N`: Core Review Questions and the stage's own "What to Check"), the project's settled rules (`rule-N`: every
     NEVER / ALWAYS bullet of the memory files that apply), and what earlier stages settled (`earlier-<artifact>`: one per
     document the stage consumes).
   - The rest is as before: the gate's `ids` (`aidlc_ids.py sync`, then `refs` with `--near`; leave them as written), the
     stage's items one by one (requirements, NFRs, rules, decisions, stories; whole, never clipped; a rule from its YAML
     source of truth), `buildTest` for the Build and Test stage, and the finding cards with `--findings` (§ 2a).
   - **Nothing traced is left unhandled in silence**: when the stage's traceability.json has a row that is not covered, or
     a requirement or NFR that no row covers, draft refuses and names each one. Write a JSON file `{"<id>": {"text": "…",
     "settled": true, "link": {"kind": "step|doc|code|test|unit", "target": "#<anchor> | path:<file>[#<id>] |
     unit:<Unit>"}}}`, or `{"<id>": {"text": "…", "acceptanceReason": {"text": "…", "by": "agent"}}}` (`by: "developer"`
     quotes them: `"quote": "<their words>", "message": "<where they said it>"`), and run draft again with `--handling`.
3. **Judge: do the `todo` list in `judgment.json`.** This is the work the page exists for. Read the stage's documents and
   `criteria.json`; write everything in plain words, whole sentences, never an ellipsis, never "see the document".
   - **Every criterion**: `criteria.<key>.verdict` is `holds`, `fails` or `n/a` (a project rule that has nothing to do
     with this stage is `n/a`). A `fails` gets a `note` saying what fails, and is named in the sources of a point below.
   - **`evaluation.verdict`**: `ready`, `risks` (approvable, with things to know) or `not-ready`.
   - **`evaluation.decides`**: two or three sentences on what approving this stage decides for the developer.
   - **`evaluation.lookFirst`** (at least one): what the developer should check first, each with `why` (why first).
   - **`evaluation.solid`** (at least one): what holds and needs no second look.
   - **`evaluation.risks`** (each with `severity` critical | high | medium | low), **`gaps`** (what the stage should say
     and does not), **`conflicts`** (where it disagrees with an earlier stage or a project rule): whenever there are any.
   - **Every point has `sources`**: a criterion key, an item id, `doc:<document key>` or a finding id. The page makes
     each a link that opens what it names.
   - **Every item** in `items` (the draft lists them with their text under `_asWritten`): a one-sentence `summary` (at
     most 300 characters) and a `label` by what it costs if it is wrong: `critical` wrong data, security or hard to undo;
     `high` wrong behaviour people would see; `medium` rework in this stage or Unit; `low` cosmetic or internal. Set
     `lookFirst: true` on the critical and high items the developer must check; keep or fix `relates`. Items an earlier
     stage settled are not listed: the page folds them. After a Request Changes round, items whose text did not change
     carry your earlier summary and label (`unchanged: true`); read them once.
   - **`documents`**: `covered` when the items and the evaluation say everything the file says (the page folds it under
     "As written", shown exactly as written), `shown` when the page must show it in full (questions, the review, anything
     with content no item holds). The draft guessed; check each.
   - **`revision`** (a revision round only: `--why revision`, or a round after a Request Changes): your account of the
     round for the page's "What changed in round N" block. `revision.feedback` is what the developer asked for: draft
     fills it from the audit trail's last Request Changes (`_said` holds their own words, `_conductorSummary` the
     conductor's summary); add the notes they left on the last page and how they sorted its findings, plain and whole.
     Then **one `revision.changes` entry per piece of that feedback**: `asked` (that piece, in a sentence), `what` (what
     you did, or why you left it), `where` (the places on the page it shows: `doc:<key>`, `doc:<key>#<section heading or
     element id>`, an item id, a criterion key, a finding id, `evaluation` or `summary`). `revision._changed` lists every
     section that changed since the last finalize of the stage with its `where` ready to copy, and `_changedItems` the
     items whose text changed; point at those, never guess. Finalize refuses a revision round without it, a `where` the
     page does not have, and a `doc:<key>#<heading>` the document does not hold.
   - Keys starting with `_` are notes for you; finalize drops them.
4. **Finalize.**
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gate_bundle.py" finalize --out <the same folder>
   ```
   It merges the judgment into the row (`row.json`) and checks it. While anything is missing (no evaluation, an item
   without a summary or a label, an ellipsis, a source that names nothing on the page, a failed criterion no point names)
   it refuses in the recipe shape (`Refused: … because …`, numbered steps with one line per problem, `It worked when: …`):
   fix each line in `judgment.json` and run it again. When it passes it prints `{"id", "verdict", "lookFirst", "items",
   "criteria", "writes", "batches"}` and keeps your summaries for the next round.
5. **Publish.** Send the rows with **one** `ArtifactData` `batch`: the `writes` array of `writes.json` as it is
   (`file_path` entries, no `if_version`, these are new rows). When finalize names more than one file in `batches`, send
   them in order. The guard refuses a `gates/` row with no evaluation, or with any part of the judgment missing, in the
   same recipe shape. If a write is refused because the id exists, run draft and finalize again a minute later: an id is
   a time stamp.
6. **Present the gate** as the protocol says. The completion message gets the line `**Read:** <artifact url>#<id>` next
   to the `**Review:**` line; the link may sit anywhere in your text before the question: the guard refuses the question
   until a text block of yours carries it. Then ask the engine's question exactly as the protocol words it ("Delivery
   Planning complete. How would you like to proceed?"): no link, no URL and no gate id in the question text. The options
   stay the engine's. End the turn.

The plan checkpoint of Code Generation (Approve Plan) is a gate too: the same steps, with its `code-generation-plan.md`.

What the page shows, top to bottom: on a revision round, **What changed in round N** (what the developer asked for,
your `revision.changes` with a jump to each place, then every changed, new and removed section, element and item of the
page with its words added and removed); **Claude's evaluation** (verdict, what approving decides, look at first, risks /
gaps / conflicts / solid with their sources, and "Rules checked": every criterion with its verdict, failed ones open);
**What the stage says** (every item as your sentence with its label, grouped Look at first / Matters most / Main / Minor,
opening to the item as written: its criteria, logic and examples; unchanged and earlier-settled items and the
traceability fold away with a count); the finding cards; your completion summary (folded); the review; and, last, **Records** (every
file of the stage as written, closed, the ones the evaluation does not cover first) and **Your answer** (the developer's
picks and notes, read-only; the decision itself is given in chat). A "Needs you" filter and a "n decisions left · m unread"
counter in the bar are the developer's; nothing the agent writes changes. Read marks per block and per item, and notes per
document, stay as they were. On a round with an earlier one of the same stage (and Unit) in the artifact, the page
compares itself with it (or with any earlier round the developer picks): words added are highlighted, words removed are
struck through, unchanged sections fold, a removed section, element or item stays as a struck ghost "removed since round
N", and the bar gets Changes / Clean, previous and next change (keys `p` and `n`) and a Changed filter. Clean is the
default view: no strikethroughs, and the words each round wrote tinted in that round's own colour (the latest round
wins where rounds clash), with a legend chip per round. The Unit
approvals page does the same against the earlier versions of the same Unit page.

## 2a. Review findings: fix what is certain, the rest goes on the page

There is no Findings question any more (the `review-findings` plugin is deprecated for AI-DLC). When the review brief
(`aidlc engine review-brief review --stage …`, printed **unpiped and in full**: the hook refuses a pipe or a redirect,
and a cut-off brief holds the gate) lists open findings, the hook's message names them and the findings file it saved
(`<state dir>/<session>.findings.json`). Then:

1. **Fix what you can fix for certain**: a clear, local change with one obvious result. Leave anything that needs a
   judgment, touches another stage or Unit, or that you are not sure of. Ask nothing in chat for these.
2. **Ask the reviewer again** when you fixed any: `aidlc engine log review --stage <s> [--unit <u>] --reviewer <r>
   --iteration <N+1>`, dispatch the reviewer, log its verdict, then print the brief again. READY settles every finding
   (nothing goes on the page); otherwise the new brief is the new list. If the engine's review freeze refuses an edit,
   leave that finding for the page.
3. **Suggested actions from a cheap model.** For each finding left with no reviewer action, dispatch a Haiku subagent
   (`Agent`, `model: "haiku"`) with the finding texts: one plain sentence each, starting with a verb, no ids or paths,
   `"none"` when nothing needs to change. Record them: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings.py" suggest
   --findings <file> --set '{"R-03": "…"}'`. Short titles the same way with `titles` (optional).
4. **Cards on the page**: add `--findings <file>` to the `gate_bundle.py` call of § 2. Every open finding becomes a
   card the developer sorts on the page: **Fix**, **Accept** (never on a blocking finding) or **Reject** (with a
   reason). The hook refuses a gate row without them, and the Approval question until such a page went out. Findings
   sorted Accept or Reject in an earlier round of the same stage are not shown again ("Already answered").

Under the unit-end rhythm the findings you leave go on the Unit's bundle page as rows of its findings section, each with
`coveredBy` saying where it is handled or why not (§ 5).

## 3. After the answer

- **When the page has finding cards: read the sort first**, whatever the answer: `get` `gates/<id>`, field
  `findingPicks` (`{<finding id>: {pick: fix|accept|reject, note}}`); the hook tells you what it holds and refuses every
  closing report until you read it. **Fix** cards are Request Changes: name each in `--reason` with its action and
  the developer's note. **Reject** cards go on the rejected report as `--reject-finding "<review artifact>#R-NN=<note>"`
  (with nothing to fix, carry them like an Accept and quote the note in chat). **Accept** cards are carried. A blocking
  card that is neither Fix nor Reject holds Approve: say so in one line and ask the developer to sort it. A typed answer
  that is just one choice for every card ("fix all", "accept all") counts as the sort; Accept never covers a blocking card.
- `Approve`: the engine's approved report, as usual.
- **Build and Test only: the target picks.** (The page shows the picks in the target matrix's open rows, not in a separate decisions block; `targetPicks` is unchanged.) Whatever the answer, `get` `gates/<id>` and read `targetPicks`
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

Never write `notes`, `targetPicks` or `findingPicks` (they are the developer's) or any decision field (the decision is given in chat),
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
   - **Nothing unhandled in silence**: every finding row, and every requirement or NFR row, says where it is handled
     or why not. The draft links a finding a plan sub-step names (`#step-<n>`) and one the review waived; the `todo`
     lists the rest. For each: set `coveredBy.link` `{kind: step|doc|code|test|unit, target: #step-<n> |
     path:<file>[#<id>] | unit:<Unit>}` with `settled: true`, or write `coveredBy.acceptanceReason`. A reason that is the
     developer's quotes them: `{text, by: "developer", quote: "<their words>", message: "<where: chat answer and date,
     questions file and Q id, page note>"}`; your own is `{text, by: "agent"}`. Never write "not in the plan" and leave it.
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
4. Write `writes.json` with one `ArtifactData` `batch`, put `<artifact url>#<bundle id>` anywhere in the text before the question, then ask the engine's question as the protocol words it, with no link in it. End the turn. **At the unit-end
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
   section has `agent` (what you will do) and the developer's steps, each with `do`, `criteria` (at least one short
   checkable sentence; the page numbers them under the step, A.1.1, A.1.2 …) and `verifies` (the V
   rows). Run `test_plan.py publish --plan <file> --bundle <bundle.json> --out <scratch>`; it refuses with one problem
   per line until every id, step shape and Test-now row coverage holds.
3. **The artifact (once per developer).** `Artifact` → `action: "list"` → **AI-DLC test plans**. If none, publish
   `test-plan.html` once: `capabilities: {db: {}, user: {}}`, `icon: "checklist"`, description "Steps to check a Unit's
   not-verified points; Pass or Fail each, notes come back to Claude." Reuse its URL; republish from the file after a
   plugin update. Write the plan's `writes.json` with one `ArtifactData` batch (a `plans/<id>` row).
4. **Drive it in chat.** Put `<artifact url>#<plan id>` in the text of your next response, anywhere in it (e.g. `Plan: <link>`), right after
   the write (the hook names the exact link), and in the same response ask (`AskUserQuestion`, header "Test plan"): **Do
   the agent step for A** / **Change the plan**. Never ask before the link: the plugin refuses every question until a
   text block of yours written after the plan was published carries it, and blocks a turn that ends without it. A plan
   published again needs its link again. Every question here has two options, never one.
   - *Change the plan*: ask what to change, revise the plan (a new id, `-test-v2-`), publish it again, send the link, ask again.
   - *Do the agent step for A*: do it, then `ArtifactData` `update` of `plans/<id>` with `agentDone` (all keys done so
     far); the developer's steps for the section open on the page. Ask (header "Test plan"): **Section A completed, go
     on** / **Change the plan**. For the last section: **Test plan completed** / **Change the plan**.
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
   Write the row, put the link in the text before the question, and ask the unit-end gate question again (Approve / Request
   Changes / Test first).

## Diagrams and visuals (1.33.0)

Nothing to do: `gate_bundle.py draft` derives the diagrams of the stage's records (`scripts/diagrams.py`: a trace ribbon, layers,
sequences, states, flows, every mermaid block) and writes them into the gate row as `diagrams`; the page draws them next to the text,
and a unit-end bundle's `verification.auto` comes from the code summary's Verified Here section. What you control is the records: a
traceability table with Source / Implements columns, a `components:` block with groups, a from / to table for state changes, a
numbered workflow, a mermaid flowchart. A record without that structure stays text. To see how a page looks, run
`python3 <plugin>/dev/preview.py` (synthetic data, no account).

## 8. Project maps (1.32.0)

A map shows how the pieces of the project connect: pick a block, see what it needs first and what waits for it. The maps are a
separate artifact, **AI-DLC maps** (`maps.html`), linked from the gate pages' headers, never part of a gate page. Four kinds,
each drawn from the records:

| Kind | Shows | Why it exists |
|---|---|---|
| `components` | the components of `components.md` as a layered graph, grouped, with what each needs and what waits for it | the shape of the design, which a table of components does not show |
| `units` | the Units of Units Generation as waves, with points, stories and which have landed | the order of the work, and where the project stands |
| `stories` | a matrix of stories by Units, with a row for every story in `stories.md` that no Unit builds | a coverage check: a gap is a row with no dot |
| `entities` | a matrix of entities by components (only when the components name entities) | who owns which data; an entity with no owner is a gap |

**A map is required** at these gates, and the guard refuses the Approval question (and the write of the gate's own row) until
the map was written from the records as they are now:

| Gate | Map |
|---|---|
| `domain-design` (`application-design` in older engines): the stage that settles the components | `components` |
| `units-generation` (and again whenever it is redone) | `units` |
| a Unit's end: the unit-end page, or a per-stage Unit's `code-generation` gate | `units`, with the status refreshed |

A project whose records hold no components, or no Units, has nothing to map: `map_bundle.py draft` says so and the guard passes.
The stories and entities maps are never required; build them when the story map or the components' entities are there
(`map_bundle.py draft --kind all` lists the ones with something to map).

**Build it before the gate page**, so the page's header links it:

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/map_bundle.py" draft --kind <kind|all> --out <a folder in the scratchpad>`. It reads
   the records (Units, their dependencies, waves, stories, points from `unit-points.csv`, status from the `## Unit Progress`
   table and the `UNIT_*` receipts of `aidlc-state.md` and `audit/`: a `UNIT_MERGED` receipt, or a `UNIT_COMPLETED` receipt of
   code-generation, means landed even when the table cell is empty; components from `components.md`) and writes
   `judgment.json`. It prints what it found, any record it could not read (a dependency on a Unit nothing defines), and a `todo`.
2. **Judge** in `judgment.json` what the records cannot give: a one-sentence plain `summary` per block (at most 240 characters,
   what it is for in words of someone who has not read the design) and its `group` (the lanes the map is coloured and filtered
   by, 3 to 7; what the records name as a kind is filled in as a start). Blocks you judged in an earlier revision keep their
   words (`_from: your last judgment`); only new blocks need you.
3. `... map_bundle.py finalize --kind <kind|all> --out <that folder>`. It refuses in the house shape until every block has a
   summary and a group. It marks the revision (the row carries the previous revision's blocks, so the page shows what is new,
   changed and removed in the round colours, and a block that landed with a tick) and writes `writes.json`.
4. Send its `writes` with one ArtifactData batch to the **AI-DLC maps** artifact (rows `maps/<intent>-<kind>`, written whole
   with `set`). The hook records the row, its link and the digest of the records it was built from.
5. Then build the gate page as in § 2 or § 5: `gate_bundle.py draft` and `unit_bundle.py finalize` put `maps: [{kind, url,
   title}]` on the row, and both pages show the links in their header.

**The artifact (once per developer).** `Artifact` `action: "list"` for **AI-DLC maps**. If there is none, publish `maps.html` from
this skill's directory once: title "AI-DLC maps", `capabilities: {db: {}, user: {}}`, `icon: "map"`, description "How the pieces
of each AI-DLC project connect: what a component or a Unit needs first and what waits for it." Reuse its URL; after a plugin
update republish the page from this file to the same URL once (the rows stay).

**When it is refreshed.** A map is stale when the records it was built from changed: a Unit landed, Units Generation was
redone, a component was added. The row's `digest` is a hash of those records; the guard compares it with the records at the
gate, so there is nothing to remember: build the map again whenever the guard says so (revision 2 shows what moved). Unchanged
records give the same revision.

## 6. The guard

### A plan approval asked with no page (Inception Units Generation, 2026-11-05)

The Units Generation session reached Step 4 (Get Plan Approval) and went straight to AskUserQuestion with the header "Plan" and
the options Approve Plan / Revise Plan. It had not logged `--checkpoint plan-approval`, and the guard only looked at questions
headed "Approval", so the plan was approved with no page and no link.

**Every Approve Plan question, at every stage and under any header, needs the stage's page and its visible link first.** The
guard now opens a plan gate for the stage the engine is at when such a question comes with no gate open, and refuses it until
you have recorded the plan decision (`aidlc engine log decision --stage <stage> --checkpoint plan-approval --value presented`),
published the page (the plan is in the stage's folder, so `gate_bundle.py draft` shows it), and sent the link as visible text.
The engine's `plan-approval` ask opens the gate for any stage, not only a Unit's Code Generation.

### The link is always shown, even after a restart (u20-timeline, 2026-11-03)

The unit-end bundle was written, the tool result was lost, the session restarted (a new session id: the guard's record of the
page was under the old one), and the agent asked the unit-end question with the summary only in thinking. The developer wrote
"I don't see the form"; the agent answered "check the linked artifact" with no URL. Nothing the developer could see held the link.

**Every Approval question, whatever its header (Approval or Unit-end) and at every gate (the plan approval, the unit-end gate,
a per-stage gate, and the unit-end gate asked again after a test plan), needs the page's link as a text message of yours since
the developer's last message.** After a restart, a lost tool result or a "cut off mid-stream" notice, send the link again
before the question; you cannot assume it was shown. These are not shown to the developer, so none counts: thinking, tool
calls and their results (ArtifactData, `Artifact` open, Bash output), text written after the question call (the desktop app
hides it), "see the linked artifact" with no URL, and a markdown link whose target is another address. The same order every
time, in ONE response:

1. Text of yours that includes the link `<artifact url>#<bundle or gate id>`, in full, anywhere in it (first, middle or last line; plain or as a markdown link whose target is the link; e.g. `Page: <link>`). The hook note after the row write, tool results and thinking are invisible to the developer: they have NOT seen the link until you write it as text. Nothing will make a refusal pass later.
2. Nothing after the question.
3. Then the AskUserQuestion call, with no link in it.

The guard finds the link itself when its record is gone (the newest page for the intent, stage and Unit, from any session's
record and from your ArtifactData writes in the transcript) and names it in the refusal; follow the refusal's three steps
word for word. If the developer says they do not see the form or the page, write the link again as text before anything else.
The test-plan flow (§ 7) is the same: the unit-end question asked again after the test plan needs the new page's link as text.

**A refusal is a recipe.** Every refusal of the guard starts `Refused: <what>, because <why>`, lists `Do this:` steps
1, 2, 3 …, and ends `It worked when: …`. Follow the steps in order, word for word (the paths and links in them are exact;
`<your scratchpad folder>` is yours to fill in), then check the last line.

`hooks/gate_guard.py` refuses the Approval question and the approved, rejected or accepted report until
a `gates` row for the stage (under the unit-end rhythm: the `bundles` row of the page the gate needs) was written in this session after the gate was opened and a message of yours
(in the session's transcript) carries its link `<artifact url>#<id>`, and refuses a question that carries
the link itself: the link goes in the text before the question, anywhere in it. Send it as a text block and make the AskUserQuestion call in that same response; never end the turn on the link alone (a Stop hook catches it once). The plan approval counts as open as soon as the engine asks for it (the active
directive is an `ask` with `ask_type: "plan-approval"`), and any question offering Approve Plan, Approve or Accept
as-is while a gate is open is guarded, whatever its header. The developer clears it with `/approval-gates:release`.

The answer Test first at the unit-end gate counts as neither approval nor rejection: the gate stays open, and the
question is refused again only until a unit-end page newer than the answer is written. The rejected report still goes
through, for the fixes picked after a test. Writes to `plans/` rows may not carry `results` (the developer's).
