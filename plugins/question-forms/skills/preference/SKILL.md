---
name: preference
description: Typed by the developer as `/question-forms:preference` to change how AI-DLC questions files are answered in this project: always as a form, asked every time, or never.
disable-model-invocation: true
---

# Change the question-forms preference

The developer typed `/question-forms:preference`. Open the preference dialog: one `AskUserQuestion` with
`metadata: {"source": "question-forms:preference"}` and a placeholder question ("Show question forms?", options
"Always" and "Ask"). The plugin's mod replaces it with its own question, explains above it what a question form
is, and records the choice. Do not answer it, record it yourself, or ask anything else; the hook refuses
recording it from Bash or by writing the file.

After the answer, say in one line what is now set. If a questions file is waiting, follow the next step the mod
adds after the dialog.
