# question-forms

Every AI-DLC questions file becomes a form in one private artifact, **AI-DLC question
forms**, published once per developer from the template in this plugin. The agent writes the
questions as rows, the developer answers in the page, the agent reads one document back and
copies the answers word for word into the file's `[Answer]:` tags. Besides questions with options it
renders text-only questions and board forms (cards sorted into 2–4 boxes, used by `pr-review` and
`review-findings`). One template, so every form looks the same on every machine; no HTML is generated per stage.

The page shares its look and its habits with the approval-gates pages: a sticky bar with filters
(unanswered, new or changed since you looked), the answered count, the save state and Done, and a
chip per question or box; tooltips on ids, terms and badges; links between questions, and links
that say when their source isn't in the form; a clear Saved / Saving / Not saved state with
retries. It works at phone width and from the keyboard.

## The preference, and what enforces it

The first time a questions file is written in a project, a dialog asks the developer how they want to fill questions
files — **Always show question forms**, **Ask every time** or **Never show** — with a short Markdown note above it on what
a question form is. The choice is per user and per project (the project is the main checkout, so its git worktrees share
it), kept in `~/.claude/plugins/data/question-forms/`, and recorded by the plugin's mod, never by the agent.
`/question-forms:preference` changes it later. Under **Ask every time** each questions file gets its own dialog: open the
form, or edit the file yourself. **Never** leaves the plugin out of the way.

`hooks/question_guard.py` (stdlib Python, per-session state; nothing happens outside an AI-DLC project) refuses:

- **Stop**: ending the turn while the preference dialog or the per-file ask is owed, or while a form's `forms/<id>`
  row was not written in this session after its file, or no assistant message carries `<artifact url>#<id>`. Bounded:
  after three blocks in a turn the stop goes through with a note.
- **AskUserQuestion** with the form link inside it: the link goes in a message of its own, before the ask.
- **`aidlc engine orchestrate next|continue|report`** for a stage whose form was opened while its file still has empty
  `[Answer]:` tags: read the form and copy the answers first.
- Recording the preference from Bash (`preference.py set|answer`) or writing the plugin's data files by hand.

`/question-forms:release` clears the session's state. Tests: `python3 -m unittest discover -s plugins/question-forms/tests`
and `claude plugin test plugins/question-forms`.

```
hooks/question_guard.py                  the guard
hooks/register.tsx                       the mod: the two dialogs, with the explanation drawn above
scripts/preference.py                    the preference, the per-file answers and the session state
skills/question-forms/SKILL.md           the procedure the agent follows at every questions file
skills/question-forms/question-form.html the template — the data contract is in its header
```

A change to the look or the data contract is a PR on the template.

## Install

```bash
claude plugin marketplace add maksymskuibida/mskuibida-ai-tools
claude plugin install question-forms@mskuibida-tooling
```

## Pairs with

`SKILL.md` § 5 (board forms) and § 5b (the form check and the summary) refer to a `pr-review`
plugin — its `review-pr`, `address-review` and `self-review` skills and its `review_flow` hook.
That plugin is not in this marketplace. Without it, questions files and text questions work as
described; the board-form procedure is there for whichever skill opens a board.
