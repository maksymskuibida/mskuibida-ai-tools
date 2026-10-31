---
name: review-findings
description: Use whenever review findings reach the developer — the review brief printed at an AI-DLC approval gate (`aidlc engine review-brief review --stage …`) with open findings, or the result of a code review (`/code-review`, the ReportFindings tool). Show each open finding in plain words with a suggested action, ask one question first (Fix / Accept / Open in form), and act on the answer; Open in form sorts each finding in a board form in the developer's "AI-DLC question forms" artifact. A hook holds back everything else until the question is answered.
---

# Review findings

Findings are decisions, not a wall of text. When they reach the developer, the developer first
says what happens to them: fix them, accept them, or sort them one by one in a form. The
`findings_guard.py` hook records every step from what the harness reports and refuses what
comes out of order. This file is the procedure; the hook's refusals say which step is open.

`FINDINGS` below stands for `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings.py"`.

## 1. When it applies

- **AI-DLC stage review.** At the end of a stage with a reviewer, the protocol runs `aidlc engine
  review-brief review --stage <slug> …` and prints its output. Open findings are the table rows
  with Status `New` or `Unresolved`; `Critical` and `Major` block, `Minor` does not. Rows that are
  `Resolved`, `Accepted risk` or `Rejected: …` are closed and do not count. (Findings of
  adversarial mid-loop reviews never reach the brief; the engine's own loop fixes them, so there
  is nothing to ask.)
- **Code review.** `/code-review` reports through the `ReportFindings` tool. Every finding is open;
  those with verdict `CONFIRMED` block, `PLAUSIBLE` ones do not. An empty report asks nothing.

**Print the brief unpiped and in full, as the only command:** `aidlc engine review-brief review
--stage <slug> …` with no `| head`, `| tail`, `| grep` and no `>` redirect. The per-finding detail
(`> R-NN Finding:`, `Where:`, `Required action:`) comes after the table, so a cut-off output holds
rows with nothing to decide on. The hook refuses a piped or redirected brief before it runs. If a
cut-off output reaches it anyway, it records no findings, says the brief was cut off, and refuses
the questions, the gate and the approved/rejected reports until you run the same command again,
unpiped. `findings.py summary|question|board` refuse a findings file with an empty finding text
for the same reason.

When there are open findings, the hook's `review-findings:` message arrives right after the
brief or the report. It holds the summary block and the path of a saved findings file (the
`--findings` argument of the commands below).

## 2. Titles, the summary and the question

**Write the titles first.** Every finding gets a short title the summary, the dialog and the board cards all show; the
hook message lists the findings that have none. A title is a whole phrase of at most 70 characters (100 at the
most), plain words, balanced backticks, no trailing "…". With more than a few findings, hand the batch to a Haiku
subagent (`model: "haiku"`) with the finding texts; for one or two, write them yourself. Record them:

```
FINDINGS titles --findings <file> --set '{"R-01": "The port cannot tell a reopened PR from a ready one", "R-02": "…"}'
```

A title that is empty, too long or has an unbalanced backtick is refused with what to fix (the others are
stored): write the refused ones again, up to twice, then leave them: the plugin then cuts a title from the finding
at a sentence or clause end, never inside a code span. The card body is the whole finding when a title exists.

Print the summary block from the hook message in chat (or render it again with `FINDINGS summary
--findings <file>`), as the text of a message of its own, before the question. The output of `summary` is a tool
result, which the developer never sees: copy it into your reply text. The hook refuses the
triage question until a message of yours since the findings were saved shows it: the review named
and a **Suggested:** action for every open finding. It shows each open finding in plain words, with
its suggested action in bold and no ids, rule codes or paths in the sentences:

```
**Review findings — Domain Design:** 2 open, 1 blocking

1. **The `Cart` rule `checkout | expire` is ambiguous.** (Blocking, domain model › Cart aggregate, invariants list) Two events can fire on the same cart, …
   **Suggested:** State the winning event. Add one line on what happens to reserved stock.
```

When you talk about a finding in chat, do the same: its number in this list and its words, never
`R-02` or `src/cart.py:42` in the sentence.

**Re-opening is the cost, small fixes ride along.** At a stage gate a blocking finding already means Request
Changes: the stage is re-opened, revised and re-reviewed. Then the minor findings that need a change are cheap, so
recommend **Fix** for them too (the summary says so and marks each such **Suggested:** line) and do not recommend
carrying them. Fix stays "fix every open finding". Only a minor finding with nothing to change, or one the model
marked not worth fixing, is carried. With nothing blocking nothing re-opens: Accept is offered as before.

The mod's model writes the **Suggested:** action for a finding with no required action. It may answer `"none"` for a
nitpick or false positive (`FINDINGS suggest --findings <file> --set '{"R-04": "none"}'`): the finding is shown as
"nothing to change" and stays Accept even in a re-opened stage.

Then ask one `AskUserQuestion` and nothing else before it: `FINDINGS question --findings <file>`
prints its input as JSON, `metadata: {"source": "review-findings"}` included; pass it as it is.
The plugin's mod builds the question again from the saved findings and draws every finding above
the dialog (Markdown on desktop, plain lines on the terminal), with a suggested action written by
a model for each finding whose reviewer named none. The question: header `Findings`, question
`"3 review findings are open (1 blocking). What should I do with them?"` (`(none blocking)` when no
finding blocks), and the options in this order:

- `Fix`: "Fix every open finding. At a stage gate this goes through Request Changes with the
  findings as the reason."
- `Accept`: "Accept all as known risks and go on." Offered **only when no finding is blocking**;
  the hook refuses the question otherwise, and refuses it when it is missing while nothing blocks.
- `Open in form`: "Sort each finding in a form: fix, accept or reject with a reason."

Until it is answered the hook refuses every other question (the Approval gate included), the
approved and rejected reports and, for a code review, edits and `git commit|push`.

## 3. What each answer means

**First, the summary of the answers.** As soon as Fix or Accept is answered here, run `FINDINGS answers --findings <file>` with no other arguments. It
prints the developer's answers, finding by finding, from what the hook recorded:

```
## Review Findings: User Answer
### R-02: Fix
#### Action items:
- State the winning event.
- Add one line on what happens to reserved stock.
#### User Note:
Checkout wins.
### R-03: Reject
#### User Note:
The name is deliberate.
```

Action items appear only where something will be done (Fix): one item as a line, several as a
list. The note appears only where the developer wrote one, as they wrote it. Send the output in
chat exactly as printed, before anything else. Until it has run, the hook refuses the gate, the
approved and rejected reports and, for a code review, edits and `git commit|push`. It also checks
that the output covers every finding with the recorded answer.

**Fix**

- AI-DLC: go on with the gate as the protocol requires. The awaiting-approval report may already
  be done. Do **not** edit the reviewed documents before the gate; the engine's review-freeze
  refuses it. In the completion message say that Request Changes carries these findings. When the
  developer picks Request Changes, the `--reason` of the rejected report names **every** open
  finding id with its required action (`R-02: state the winning event; R-03: …`); the hook refuses
  the report when an id is missing. Then revise, re-review, re-present as the protocol says.
- Code review: apply the fixes now (the `--fix` flow), then say what changed, finding by finding.

**Accept**

- AI-DLC: go on with the gate. On Approve the engine records every open finding as `Accepted
  risk` by itself. Say in the completion message that they are carried as accepted.
- Code review: list the findings as accepted in chat and go on. No fix.

**Open in form**: section 4.

An answer typed under Other decides nothing: ask in chat what the developer wants, or ask the
question again. The exception is a message that is just an option (`accept`, `fix all`, `form`,
…): the hook records it as that answer; do not ask again.

## 4. Open in form

The form is a board of the `question-forms` plugin (its `SKILL.md` § 5 is the contract) in the
developer's **AI-DLC question forms** artifact. If the developer has no such artifact, follow
that skill's § 1 to publish it first.

1. Build the rows: `FINDINGS board --findings <file> --out <scratch dir>`. It prints the form id
   (`<intent>-<stage>[-<unit>]-findings-<YYYYMMDDTHHMM>`, or `code-review-<YYYYMMDDTHHMM>`) and
   the path of `writes.json`. The board is titled "Unit <unit>: <stage name> review findings" ("<stage name> review findings" without a Unit; "Code review findings" for a code review) and is a
   list of cards in two sections (Blocking, then Can be carried; for a code review Confirmed, then Possible)
   with three decision buttons on each card: **Fix** ("Fixed before approval"), **Accept** ("Carried as a known
   risk") and **Reject** ("Not applicable"; its note field opens and a reason is required). Each finding is one
   card: the title is its first sentence, the details hold Where, Finding and Required action, and the card shows
   its severity and whether it blocks. The review suggests Fix for a blocking finding. Re-opening the stage is the
   expensive part, not a small fix, so once a stage review has a blocking finding (the stage is re-opened anyway) it also
   suggests Fix for every non-blocking finding that has a real action (the reviewer's required action or the model's
   suggestion), with a `why` saying so; a finding with nothing to change, or one the model marked "none", stays Accept,
   and so does everything when nothing blocks. A code review is unchanged (a blocking finding Fix, the rest Accept). The
   suggestion is marked on the card, but nothing is picked for the developer: every card has to be decided
   (Done stays off until it is), or the developer takes the suggestion with the bulk buttons. Its details say, in plain words, what is
   wrong, the suggested action and where; the card also carries them apart (`plain`, `action`,
   `detail`), with `refs` (what the finding points at, `{label, tip, target}`, a live link when the
   target is `#<qid>` of another card) for the page (question-forms § 5). In an AI-DLC project,
   `board` also syncs the project's id map (`aidlc_ids.py sync`) and writes the form's `ids`: the
   definition of every id the cards mention (US, AC, FR, NFR, BR, Q, U, C, E, ADR, R, …), nearest the
   reviewed document, so the page shows each one as a link with a tooltip. Its output says how many
   (`"ids": n`), and `ids_note` why there are none. Write ids as they are in the cards' text; never
   paste them into a sentence that plain words can say.
2. Write the rows with **one** `ArtifactData` `batch` whose `writes` are the array in
   `writes.json`, as it is (new rows: no `if_version`).
3. Send the form check, as `question-forms` § 5b A says: `AskUserQuestion`, header `Form`, question
   `Look at the form and pick one from above: <artifact url>#<form id>`, options `Saved in the
   form` and `Something is wrong in the form`. Only `Saved in the form` goes on, and only once the
   form reads `status: "done"`: read it with `ArtifactData` `get` of `forms/<form id>`. If it is
   not done, say so and wait. If something is wrong in the form, fix the rows (the same batch sets
   the form's `status` back to `open`) and ask again. You never write `status: "done"`; the hook
   refuses it.
4. Read the answers back with `ArtifactData` `get` of `forms/<form id>` (the hook records the
   answers from that result; `answers[qid].k[0]` is the card's box, `note` the developer's words).
   No summary of the answers is sent: the developer wrote them in the form. Then:
   - **Any card in Fix** (a stage review): that is Request Changes. Do not ask the Approval
     question; report rejected at once, with the Fix cards and the Reject cards as below, and say in
     chat which findings go back for fixing. The hook refuses the Approval question and an approved
     report here.
   - **Fix** cards: as Fix above. The rejected report's `--reason` names these cards by id with
     their required action.
   - **Accept** cards: carried; on Approve the engine records them as accepted risks.
   - **Reject** cards: `--reject-finding "<review artifact path>#R-NN=<note>"` on the rejected
     report. That is only possible together with Request Changes. When nothing is to be fixed, a
     rejected finding is carried like an accepted one and its note is quoted in chat.
   - Code review: Fix cards are fixed now, Accept cards listed as accepted, Reject cards listed
     with their note.
5. The gate (and, for a code review, every edit and commit) waits until the form is done; the hook
   refuses with `Answer the form to continue: <link>`.

### Fixed in place, then re-reviewed (Code Generation, unit-end rhythm)

Where the fixes land before the single gate, fix the Fix cards in place, commit, and run the next
review pass of the same stage (and Unit): `aidlc engine log review --stage <stage> [--unit <unit>]
--reviewer <reviewer> --iteration <N+1>`, dispatch the reviewer, then record its verdict with
`aidlc engine log review … --iteration <N+1> --verdict <verdict>`. When that logs `REVIEW_COMPLETED`
with verdict READY, the hook treats the picked findings as settled and the approved report goes
through. Any other verdict, no re-review, or a pass of another stage or Unit leaves the round as it
was: report rejected. Never ask the developer to release for this.

## 5. After the gate

The hook clears the findings when the engine's approved or rejected report for the stage runs, so
a revision's next brief starts a new round. If the same findings are printed again while the
question is already answered, the answer stands.

**Answered findings are not asked again.** The engine keeps an Accepted finding `New` until the Unit
is approved, so later briefs list it again. The hook remembers the answers per stage and Unit (across
sessions): a finding with the same id and text answered Accept or Reject is shown as one line,
`Already answered: R-07 (accepted)`, and not asked; a changed finding, or one answered Fix and still
open, is asked again. When nothing new is left there is no question: go on with the gate (Approve
records the carried findings as accepted risks). The memory ends with the approved report or the
Unit's release.

If the guard gets in the way, the developer types `/review-findings:release`.
