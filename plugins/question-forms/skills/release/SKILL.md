---
name: release
description: Typed by the developer as `/question-forms:release` to clear the question-forms guard for this session. The hook has already cleared it when the prompt was submitted; this skill only tells the assistant so.
disable-model-invocation: true
---

# Release the question-forms guard

The developer typed `/question-forms:release`. The `question_guard.py` hook deleted this session's
state when the prompt was submitted: no questions file is pending, the turn is no longer held back for a form,
and the engine is no longer refused for a file with empty `[Answer]:` tags.

Say so in one line and go on with what the developer was doing. Do not open a form, ask anything or touch
the state files yourself. The next questions file written opens the guard again.
