---
name: unit-claim
description: Use before a team AI-DLC Unit is claimed — `/aidlc --claim <unit>`, `aidlc unit claim <unit>`, or picking a Unit at the engine's unit-claim ask. Send your reasoning per design stage as one message, then ask one dialog (which design stages run, the approval rhythm, whether to save the choice), claim with the chosen rhythm, and skip the left-out stages for that Unit only. Also when the developer wants to change or save their claim choice.
---

# Before a Unit is claimed

A team Unit can skip design stages it does not need, and can be claimed with the `unit-end` rhythm. Under that rhythm
the design stages run with their reviewer rounds and no approval between them. The developer then stops twice: once
at the plan page (Code Generation plan approval) and once at the unit-end page. See the approval-gates plugin. The
developer makes this choice once, before the claim. `hooks/claim_guard.py` refuses the claim until they have made it,
or until a saved choice exists.

The script is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/claim_choice.py"` (written `claim_choice.py` below).

## 1. Is a choice already in force?

Run `claim_choice.py status --unit <unit>`.

- **`choice` is set** (an earlier answer for this Unit, or a choice saved for the project or for the developer): say in
  one line which stages run and which rhythm, then claim (§ 4). Don't show the dialog. The hook refuses it once a
  choice is saved.
- **`agentPick` is true** (the saved choice is "use the agent's pick"): send message 1 (§ 2), record your pick with
  `claim_choice.py pick --unit <unit> --stages <slugs, comma-separated, or none>`, then claim (§ 4).
- **Otherwise** (`ask` is true): send message 1 (§ 2), then message 2 (§ 3).

## 2. Message 1: your reasoning, plain text

Run `claim_choice.py stages`. It prints the four design stages and each stage's own `condition:`, read from the
project's stage graph. Read what the Unit is: its entry in `inception/units-generation/unit-of-work.md` and its
stories. Then send a message of its own, with one line per design stage. Each line says whether the stage applies to
this Unit, judged against that stage's condition, and why, in plain words:

```
- Functional Design: run. The calendar has its own rules (neighbours, month range, keys) that need writing down.
- NFR Requirements: skip. No new performance, security or stack choice; U3's targets cover the header.
- NFR Design: skip. It needs NFR Requirements, which is skipped.
- Infrastructure Design: skip. Nothing changes in how the app is built, run or released.
```

Write it as text, not as thinking or inside a tool call. The hook refuses the dialog until a message of yours, sent
since the developer's last prompt, names all four stages.

## 3. Message 2: one dialog, three questions

One `AskUserQuestion` call with exactly these three questions. Keep each question to one line. Put the detail in the
option descriptions.

1. **header `Stages`**, `multiSelect: true`. The question line names the Unit in backticks and names your pick, for
   example "Which design stages should `u4-day-navigation` run? I'd run Functional Design only." The options are the
   four stages, labelled `Functional Design`, `NFR Requirements`, `NFR Design` and `Infrastructure Design`. Add
   " (Recommended)" to the label of each stage you picked. Each description is your one-line reason.
2. **header `Rhythm`**: "How should this Unit be approved?" with two options:
   - `unit-end`: one plan page before the code and one page at the end; no stop between design stages.
   - `per-stage`: an approval after every stage, as today.

   Put first the one the project's affirmed `Unit Gate Rhythm` names, and mark it "(Recommended)".
3. **header `Save`**: "Save this choice?" with three options:
   - `No`: ask again at the next claim.
   - `For me`: saved in this plugin's data folder; you won't be asked again.
   - `For this project`: a bookkeeping pull request adds `.unit-claim.json`; nobody on the project is asked again.

Summary confirmation is a project setting. Don't ask about it.

The hook records the answer as the Unit's choice. **NFR Design without NFR Requirements adds NFR Requirements back**:
when the hook says so, tell the developer in one line. A free-text answer the hook cannot read comes back as a
question to ask in chat.

## 4. Claim with the choice

Claim as the engine asks, and add the chosen rhythm:

```
aidlc unit claim <unit> --team "<label>" --rhythm <unit-end|per-stage>
```

The hook refuses a claim without `--rhythm` or with a different one.

After the claim, a stage the choice leaves out is skipped for **this Unit only**. Use the engine's per-Unit
conditional skip when its directive names that stage for the Unit:

```
aidlc engine orchestrate report --stage <slug> --unit <unit> --result skipped --reason "skipped at claim by the developer"
```

Then run `next`. `claim_choice.py skips --unit <unit>` prints these commands. The hook refuses
`aidlc engine state unit start` of a left-out stage and names the skip to run instead. Never skip a stage whose files
for the Unit are already written: the engine refuses that, so tell the developer and run the stage.

## 5. "For this project": the bookkeeping pull request

The Unit goes on with the choice at once. Saving it for the project is separate work that lands as its own pull
request:

1. Offer to run it in its own session. In the Claude desktop app, use `start_session` with `initiation: "offer"`. The
   brief: check out the project's default branch in a fresh worktree; run
   `claim_choice.py save --scope project --stages <slugs|none> --rhythm <rhythm> --project-dir <that worktree>`; commit
   `.unit-claim.json`; open the pull request; follow the project's and the developer's rules for after a PR is opened.
   Elsewhere, ask in chat.
2. **If it runs elsewhere**, carry on with the Unit here.
3. **If it runs here**, do the same steps in a separate worktree of the default branch, never in the Unit's claimed
   checkout. Create the pull request first. Then follow any after-PR rules the project or the developer has (review,
   labels, CI). Then offer to continue the Unit.

## 6. Changing a saved choice

- For the developer: `claim_choice.py save --scope me --stages <slugs|none|agent> --rhythm <rhythm>`. `agent` means
  "use the agent's pick for each Unit without asking". The reasoning message is still sent.
- For the project: the same command with `--scope project`, through a bookkeeping pull request (§ 5).
- To be asked again for one Unit: `claim_choice.py forget --unit <unit>`.

Do any of these only when the developer asks.
