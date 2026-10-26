---
name: unit-claim
description: Use before a team AI-DLC Unit is claimed — `/aidlc --claim <unit>`, `aidlc unit claim <unit>`, or picking a Unit at the engine's unit-claim ask. Open the claim dialog (one AskUserQuestion with `metadata.source` "unit-claim:<unit>"; the plugin's mod asks which design stages run and the approval rhythm, with its recommendation above), claim with the chosen rhythm, and skip the left-out stages for that Unit only. Also when the developer wants to answer a Unit's claim dialog again.
---

# Before a Unit is claimed

A team Unit can skip design stages it does not need, and can be claimed with the `unit-end` rhythm. Under that rhythm
the design stages run with their reviewer rounds and no approval between them. The developer then stops twice: once
at the plan page (Code Generation plan approval) and once at the unit-end page. See the approval-gates plugin. The
developer chooses both for each Unit, before its claim. `hooks/claim_guard.py` refuses the claim until they have.

The script is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/claim_choice.py"` (written `claim_choice.py` below).

## 1. Is an answer already recorded?

Run `claim_choice.py status --unit <unit>`. When `choice` is set, the developer answered for this Unit already: say
in one line which stages run and which rhythm, then claim (§ 3).

## 2. Open the claim dialog

One `AskUserQuestion` call, nothing more:

- `metadata`: `{"source": "unit-claim:<unit>"}`
- one placeholder question: "Claim `<unit>`?", header `Claim`, options `Yes` and `No`.

The plugin's mod (`hooks/register.tsx`) replaces the placeholder with its own two questions and draws its
recommendation above them. Don't write a recommendation of your own and don't ask anything else first:

- **Stages**: "Suggested stages" (the stages a model recommends, each with its reason shown above the dialog), "All
  four stages", or the developer's own list typed under Other.
- **Rhythm**: the rhythms the project's pinned engine accepts (`aidlc unit claim --help`), today `unit-end` and
  `per-stage`, with no default.

After the dialog the mod adds one line, starting `unit-claim:`. Do what it says:

- **Recorded**: the answer is the Unit's choice. If the line says a stage was added back (NFR Design needs NFR
  Requirements), tell the developer in one line. Then claim (§ 3).
- **Refused**: what the developer typed could not be read clearly (a stage or rhythm name that matches nothing, or a
  stage named twice). Call `AskUserQuestion` again exactly as before and say nothing else. The mod shows the refusal
  and its suggestion above the same questions.

Never record an answer yourself: the hook refuses `claim_choice.py record` from Bash, and writing an answer file.

## 3. Claim with the choice

Claim as the engine asks, with the flags the Unit's answer gives. The mod's `unit-claim:` line names them, and so does
`claim_choice.py status --unit <unit>` (`claimFlags`):

```
aidlc unit claim <unit> --team "<label>" --rhythm <unit-end|per-stage> --skip-stages <left-out stages>
```

`--skip-stages` lists exactly the stages the developer left out, comma-separated (any of `functional-design`,
`nfr-requirements`, `nfr-design`, `infrastructure-design`). Leave it out when every stage runs. The hook refuses a claim
whose rhythm or left-out stages differ from the answer.

The claim itself skips those stages for **this Unit only**. Run `aidlc engine orchestrate next`: the Unit starts at its
first stage that runs, and Unit Progress shows the skipped ones as `[S]`. The hook refuses
`aidlc engine state unit start` of a left-out stage.

**An engine without `--skip-stages`** (older than 2.11.2-preview.20261026.101; `claim_choice.py engine` says
`skipStages: false`): claim with `--rhythm` alone. Each left-out stage is then skipped when the engine's directive names
it for the Unit:

```
aidlc engine orchestrate report --stage <slug> --unit <unit> --result skipped --reason "skipped at claim by the developer"
```

Then run `next`. `claim_choice.py skips --unit <unit>` prints these commands. Never skip a stage whose files for the
Unit are already written: the engine refuses that, so tell the developer and run the stage.

## 4. Asking again

When the developer wants to change a Unit's answer before it is claimed, run `claim_choice.py forget --unit <unit>`,
then open the dialog again (§ 2). Only when they ask.
