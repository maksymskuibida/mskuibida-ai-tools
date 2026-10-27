---
name: approval-gates
description: Use at every AI-DLC approval gate, right after `aidlc engine orchestrate report --result awaiting-approval` (or `--result revised`) and before the Approval question — publish the stage's documents as a page in the developer's "AI-DLC approval gates" artifact and send its link in a message of its own before the gate question. For a Unit claimed with the unit-end rhythm, at its Code Generation plan approval and at its one unit-end gate, build the Unit's gate bundle instead and publish it in the "AI-DLC unit approvals" artifact. Also when the developer answered, to read the notes they left in the page.
---

# Approval gates

Every approval gate gets a page, always. The engine's gate stays exactly as the engine prescribes:
the completion message, then the Approval question with `AskUserQuestion`, then the end of your turn.
The page, `approval-gate.html` next to this file, is where the developer **reads** the stage's
documents, each in a view made for its kind, and may leave a note per document. The decision itself
is given in chat; the page holds none. Its header comment is the data contract. Never generate,
restyle or edit a page per stage.

## 1. The artifact (once per developer)

`Artifact` → `action: "list"` → the artifact titled **AI-DLC approval gates**. If the developer
has none, publish `approval-gate.html` from this skill's directory once: `capabilities: {db: {}, user: {}}`,
`icon: "document"`, description "Read a stage's AI-DLC documents at its approval gate; notes come back
to Claude." Reuse its URL for every gate from then on. After a plugin update, republish the page from
this file to the same URL once, with `capabilities: {db: {}, user: {}}` (the `user` capability keeps each
viewer's read marks; an artifact published before 1.5.0 has only `db`): the rows stay.

## 2. At every gate

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
- `Request Changes`: first `ArtifactData` `get` of `gates/<id>`. If `notes` holds anything, quote it
  (each note under its document's title) in the rejected report's `--reason`, together with what the
  developer typed in chat. If the page holds nothing and the chat answer has no feedback, ask what
  should change, as the protocol says.
- After the revision and the new review, the `revised` report opens a fresh gate: § 2 again, with a new id.

## 4. Never

Never write `notes` (they are the developer's) or any decision field (the decision is given in chat),
and never update a row: each presentation is a fresh id.

## 5. A Unit with the unit-end rhythm

A team Unit claimed with `--rhythm unit-end` (the claim's stamp `aidlc/.aidlc-unit-scope.json` says
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
   own, then ask the engine's question as the protocol words it, with no link in it. End the turn.

**After the answer**, `ArtifactData` `get` of `bundles/<id>`: the page stores the developer's notes per row
(`notes.<row anchor>`) and their lean on a suggestion (`picks.<row anchor>`: `do` or `leave`). On Request Changes quote
them in the rejected report's `--reason` with the chat answer. On Approve with notes or picks present, say so in one line
and ask in chat whether to act on them; the decision is the chat answer. A Request Changes at the unit-end gate sends
the Unit's whole chain back for review (the engine floors every stage of the Unit); say so when the developer asks for
a small change that the plan page would have been the cheaper place for. Never write `notes` or `picks`.

## 6. The guard

`hooks/gate_guard.py` refuses the Approval question and the approved, rejected or accepted report until
a `gates` row for the stage (under the unit-end rhythm: the `bundles` row of the page the gate needs) was written in this session after the gate was opened and a message of yours
(in the session's transcript) carries its link `<artifact url>#<id>`, and refuses a question that carries
the link itself: the link goes in a message of its own. The plan approval counts as open as soon as the engine asks for it (the active
directive is an `ask` with `ask_type: "plan-approval"`), and any question offering Approve Plan, Approve or Accept
as-is while a gate is open is guarded, whatever its header. The developer clears it with `/approval-gates:release`.
