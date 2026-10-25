# review-findings

When review findings reach you, you decide what happens to them before anything else does. The
agent shows each open finding in plain words, with a suggested action, and asks one question: **Fix**, **Accept** (only
when nothing blocks) or **Open in form**. A hook keeps that order.

Two sources, nothing else in this version:

- **AI-DLC stage reviews.** The review brief the protocol prints at an approval gate
  (`aidlc engine review-brief review --stage …`). Open findings are the rows with status `New` or
  `Unresolved`; `Critical` and `Major` block.
  The brief must be printed unpiped and in full: a piped or redirected call is refused, and a
  cut-off output (table without the `> R-NN Finding:` lines) is not recorded as findings.
- **Code review.** `/code-review` reports its findings through the `ReportFindings` tool. Every
  finding is open; those marked `CONFIRMED` block.

```
skills/review-findings/SKILL.md   the procedure: the summary, the question, what each answer means, the board form
skills/release/SKILL.md           /review-findings:release
scripts/findings.py               parses a brief, a review-NN.md or a ReportFindings input; renders the summary and the board rows
hooks/findings_guard.py           the guard (PreToolUse, PostToolUse, UserPromptSubmit)
hooks/register.tsx                the mod: builds the question from the saved findings and draws them above the dialog
```

## What you see

The findings in plain words, in chat and again above the question (the mod draws them in the
dialog's frame: Markdown on desktop, up to 48 rows; plain lines on the terminal, up to 12; what does
not fit is counted on one line that points at the form). No finding ids, rule codes or `file:line`
in the sentences:

```
## Review findings · Domain Design
2 open, 1 blocking. Choose below what happens to them.

### 1 · The `Cart` rule `checkout | expire` is ambiguous.
- **Blocking** · domain model › Cart aggregate, invariants list
- Two events can fire on the same cart, and the model does not say which one wins. …
- **Suggested:** State the winning event. Add one line on what happens to reserved stock.

### 2 · The Events table lists `OrderPlaced` but the flow text calls it `CheckoutDone`.
- **Not blocking** · domain model › Events
- **Suggested:** Use one name for the order event in the table and the flow text.

2 review findings are open (1 blocking). What should I do with them?   Fix / Open in form
```

The suggested action is the reviewer's required action. Where the reviewer named none (a code
review's findings, an AI-DLC finding without a `Required action:` line), the mod asks a model for
one sentence (`suggestModel`, Haiku by default; `off` keeps a fixed line), once per round, and
keeps it only when it carries no id. Another finding's id in the text becomes "finding 2"; a path
with a line becomes the file's name.

- **Fix.** At a stage gate the agent presents the gate as usual and says that Request Changes
  carries the findings. When you pick Request Changes, the reason names every open finding and its
  required action. In a code review the agent applies the fixes now.
- **Accept.** Offered only when no finding blocks. At a gate, Approve records the findings as
  accepted risks (the engine does that). In a code review they are listed as accepted.
- **Open in form.** The agent opens a board in your **AI-DLC question forms** artifact (the
  `question-forms` plugin): one card per finding, in the boxes Fix, Accept and Reject (reason
  required), each card starting where its severity says. You sort them and press Done; the agent
  shows one line per card and acts on it. Rejected cards go on the rejected report as
  `--reject-finding`.

## What the hook refuses

While findings are waiting for the first answer:

- any other question, the Approval gate included;
- `aidlc engine orchestrate report --result approved|rejected`;
- code review only: edits (a file outside the project is fine) and `git commit|push`.

And always:

- a triage question that offers Accept while a finding blocks, or leaves it out when none does;
- after Fix, a rejected report whose `--reason` misses an open finding id;
- after Open in form, the gate and the report until the form reads `status: "done"`;
- an agent writing `status: "done"` on a findings form (only your press on Done does that).

A refusal ends with how to release it. Type `/review-findings:release` to clear the guard for the
session. If python3 is missing, the hook refuses guarded calls only while a state file exists, and
says so.

State is in `~/.claude/review-findings/<session>.json` (`REVIEW_FINDINGS_DIR` moves it) next to
the findings file the agent renders from (`<session>.findings`). The hook changes it; the agent
does not.

## The data

`findings.py` turns every source into one findings document:

```json
{"source": "aidlc", "stage": "domain-design", "stage_name": "Domain Design", "artifact": "<path>",
 "findings": [{"id": "R-02", "severity": "Major", "where": "…", "finding": "…", "action": "…",
               "status": "New", "blocking": true, "title": "…"}]}
```

```
findings.py parse --brief FILE | --review FILE | --report FILE [--stage SLUG] [--unit U]
findings.py summary  --findings FILE
findings.py question --findings FILE
findings.py dialog   --findings FILE | --session ID      (what the mod draws and asks, as JSON)
findings.py suggest  --findings FILE --set JSON          (records the model's suggested actions)
findings.py board    --findings FILE [--id ID] [--title T] [--project-dir D] --out DIR
```

`board` writes `forms.json`, `cards/<id>.json` and `writes.json` for one `ArtifactData` batch: the
form `forms/<id>` (`view: "board"`, three boxes) and a `forms/<id>/questions/<finding id>` card per
finding, in the contract of the `question-forms` template. Each card's `ctx` is the plain words
(What's wrong, Suggested, Where); the card also carries the optional fields `what`, `suggested`,
`suggestedBy`, `detail`, `refs` and `badge` for a page that draws them apart:

```json
"refs": [{"t": "domain model › Cart aggregate", "kind": "section", "tip": "domain-model.md > Cart aggregate"},
         {"t": "finding 2", "kind": "finding", "tip": "R-04, card 2 in this form", "qid": "R-04"}],
"badge": {"t": "Blocking", "tip": "Major: a Critical or Major finding blocks approval until it is fixed or rejected."}
```

A ref with `qid` points at another card of the same form; one without points at something the form
does not hold (a document section, a file, a finding closed before this round), and `tip` is all
that is known of it. The form id is
`<intent>-<stage>[-<unit>]-findings-<YYYYMMDDTHHMM>`, or `code-review-<YYYYMMDDTHHMM>`.

## Install

```bash
claude plugin marketplace add maksymskuibida/mskuibida-ai-tools
claude plugin install review-findings@mskuibida-tooling
```

## Pairs with

- `question-forms` for the board. Without it the Fix and Accept answers work as described; Open in
  form needs the artifact and the template from that plugin.
- `approval-gates`, which treats the same Approval question as the engine's gate. This plugin
  stands before it: the findings are answered first, the gate comes after.

## Tests

```bash
python3 -m unittest discover -s plugins/review-findings/tests
claude plugin validate plugins/review-findings
claude plugin test plugins/review-findings
```

The Python suites use the standard library only; no network and no `aidlc` binary needed. The
mod's tests (`tests/dialog.test.tsx`) stand in for the engine, findings.py and the model.
