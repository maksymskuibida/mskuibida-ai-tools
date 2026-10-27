#!/usr/bin/env python3
"""Review findings: parse them, summarise them for the chat, lay them out as a board form.

Sources
  parse --brief FILE    the text `aidlc engine review-brief review --stage S` prints at an approval gate
  parse --review FILE   a readable `reviews/review-NN.md` of a stage (the 6-column `### Findings` table)
  parse --report FILE   the input of Claude Code's `ReportFindings` tool (`{"findings": [...]}`)

A findings document is JSON:
  {"source": "aidlc" | "code-review", "stage": "<slug>", "stage_name": "Domain Design", "artifact": "<path>",
   "reviewer"?, "findings": [{"id", "severity", "where", "finding", "action", "status", "blocking", "title",
                              "scenario"?, "category"?, "suggested"?}]}
`findings` holds the OPEN findings only (AI-DLC: Status New or Unresolved; code review: all of them).
Blocking is severity Critical or Major (AI-DLC), or verdict CONFIRMED (code review).

  summary --findings FILE   the inline summary block for the chat: each finding in plain words with "Suggested: …"
  dialog --findings FILE | --session ID
                            what the plugin's mod draws above the triage question and asks, as JSON (`--session`
                            reads the findings the guard saved for that session)
  answers --findings FILE [--choice fix|accept | --form FILE]
                            the summary of the developer's answers ("## Review Findings: User Answer"), from what the
                            guard recorded for the session (or the given chat answer, or a done form's document)
  suggest --findings FILE --set JSON
                            record a model's suggested action ({"<id>": "…"}) on findings that have no required action
  question --findings FILE  the triage AskUserQuestion input (header Findings), as JSON
  board --findings FILE [--id ID] [--title T] [--project-dir D] --out DIR
                            forms.json, cards/<qid>.json and writes.json for one ArtifactData batch that
                            opens a BOARD form in the "AI-DLC question forms" artifact

`-` as a file reads stdin. Standard library only; the guard hook imports this file by path.
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys

BLOCKING_SEVERITIES = {"critical", "major"}
OPEN_STATUSES = {"new", "unresolved"}
FINDING_ID = re.compile(r"^[A-Za-z]+-\d+$")
QUOTE = re.compile(r"^>\s*([A-Za-z]+-\d+)\s+(Finding|Where|Required action):\s*(.*)$")
FIELD_NAMES = {"finding": "finding", "where": "where", "required action": "action"}
SUMMARY_LIMIT = 140
TITLE_LIMIT = 90

TRIAGE_HEADER = "Findings"
FIX_LABEL, ACCEPT_LABEL, FORM_LABEL = "Fix", "Accept", "Open in form"
SOURCE = "review-findings"  # the triage question's `metadata.source`: the plugin's mod draws the findings above it


# ---------------------------------------------------------------- text helpers

def one_line(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clip(text, limit):
    text = one_line(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def first_sentence(text, limit):
    """The first sentence of a text on one line, cut to `limit` characters (with a final ellipsis when cut)."""
    text = one_line(text)
    found = re.search(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(])", text)
    return clip(text[:found.start()] if found else text, limit)


def slug(text):
    return re.sub(r"[^a-z0-9._-]+", "-", str(text).lower()).strip("-")


def severity_of(raw):
    raw = one_line(raw)
    return raw[:1].upper() + raw[1:].lower() if raw else ""


# ---------------------------------------------------------------- tables and quotes

def split_row(line):
    """The cells of a markdown table row; `\\|` inside a cell is a literal pipe."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", body)]


def tables(text):
    """[(header cells, [row cells])] for each markdown table in the text."""
    found, header, rows = [], None, []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            cells = split_row(line)
            if header is None:
                header = [c.lower() for c in cells]
            elif all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) or not c for c in cells):
                continue
            else:
                rows.append(cells)
        elif header is not None:
            found.append((header, rows))
            header, rows = None, []
    return found


def findings_table(text):
    """The first table with an ID, a Severity and a Status column, as [{column name: cell}]."""
    for header, rows in tables(text):
        if "id" in header and "severity" in header and "status" in header:
            return [{h: (row[i] if i < len(row) else "") for i, h in enumerate(header)} for row in rows
                    if row and FINDING_ID.match(row[0])]
    return []


def quotes(text):
    """{id: {finding, where, action}} from the `> R-NN Finding:` blocks of a brief; a block runs to the next blank line."""
    out, current = {}, None
    for line in text.splitlines():
        found = QUOTE.match(line)
        if found:
            fid, name, rest = found.groups()
            current = out.setdefault(fid, {}), FIELD_NAMES[name.lower()]
            current[0][current[1]] = rest.strip()
        elif current is not None and line.strip():
            current[0][current[1]] += "\n" + re.sub(r"^>\s?", "", line).strip()
        else:
            current = None
    return out


def header_line(text, name):
    found = re.search(rf"^\*\*{re.escape(name)}:\*\*[ \t]*(.+?)[ \t]*$", text, re.M)
    return found.group(1).strip() if found else ""


def is_blocking(severity):
    return severity.strip().lower() in BLOCKING_SEVERITIES


def record(fid, severity, where, finding, action, status):
    severity = severity_of(severity)
    return {"id": fid, "severity": severity, "where": where.strip(), "finding": finding.strip(),
            "action": action.strip(), "status": status.strip(), "blocking": is_blocking(severity),
            "title": first_sentence(finding, TITLE_LIMIT)}


# ---------------------------------------------------------------- parsers

def parse_brief(text, stage=None):
    """The open findings of a review brief. `stage` is the slug from the command (the brief names only the stage)."""
    name = header_line(text, "Stage")
    art = header_line(text, "Review artifact").strip("`")
    hydrated = quotes(text)
    found = []
    for row in findings_table(text):
        if one_line(row.get("status", "")).lower() not in OPEN_STATUSES:
            continue
        quote = hydrated.get(row["id"], {})
        found.append(record(row["id"], row.get("severity", ""), quote.get("where") or row.get("where", ""),
                            quote.get("finding", ""), quote.get("action", ""), row.get("status", "")))
    return {"source": "aidlc", "stage": stage or slug(name), "stage_name": name, "artifact": art,
            "outcome": header_line(text, "Review outcome"), "findings": found}


def parse_review(text, stage=None):
    """The open findings of a readable `reviews/review-NN.md`."""
    found = []
    for row in findings_table(text):
        if one_line(row.get("status", "")).lower() not in OPEN_STATUSES:
            continue
        found.append(record(row["id"], row.get("severity", ""), row.get("location", row.get("where", "")),
                            row.get("finding", ""), row.get("required action", ""), row.get("status", "")))
    doc = {"source": "aidlc", "stage": stage or "", "stage_name": "", "artifact": "", "findings": found}
    for key, name in (("verdict", "Verdict"), ("reviewer", "Reviewer"), ("iteration", "Iteration")):
        value = header_line(text, name)
        if value:
            doc[key] = value
    return doc


def parse_report(data):
    """The findings of a `ReportFindings` call: the tool input (`{"findings": [...]}`) or just the list."""
    items = data.get("findings") if isinstance(data, dict) else data
    found = []
    for n, item in enumerate(i for i in (items or []) if isinstance(i, dict)):
        verdict = str(item.get("verdict") or "").upper()
        where = str(item.get("file") or "")
        if where and item.get("line") not in (None, ""):
            where += f":{item['line']}"
        summary = str(item.get("summary") or item.get("short_summary") or "")
        found.append({
            "id": f"F-{n + 1:02d}", "severity": verdict.capitalize() if verdict else "Unrated", "where": where,
            "finding": summary.strip(), "action": "", "status": "New", "blocking": verdict == "CONFIRMED",
            "title": clip(item.get("short_summary") or first_sentence(summary, TITLE_LIMIT), TITLE_LIMIT),
            "scenario": str(item.get("failure_scenario") or "").strip(), "category": str(item.get("category") or "").strip(),
        })
    return {"source": "code-review", "stage": "", "stage_name": "code review", "artifact": "", "findings": found}


CUT_OFF = ("the review brief was cut off (piped through head/tail/grep or redirected): run the command again "
           "unpiped as the only command")


def unfilled(doc):
    """The ids of the open findings that have no finding text: a brief whose `> R-NN Finding:` lines never arrived."""
    return [f.get("id", "?") for f in doc.get("findings") or [] if not one_line(f.get("finding"))]


def incomplete(doc):
    """The refusal text when an open finding has no finding text, else "". A form or a summary built from
    such a document would show the developer cards with nothing to decide on."""
    ids = unfilled(doc)
    return f"{CUT_OFF}. No finding text for: {', '.join(ids)}." if ids else ""


def counts(doc):
    found = doc.get("findings") or []
    return len(found), sum(1 for f in found if f.get("blocking"))


# ---------------------------------------------------------------- plain words

# The findings above the triage dialog: the mod's tree is held to 48 rows on desktop (Markdown) and 12 on the
# terminal (plain lines), counting a row per line and one more per 40 columns it runs to.
DIALOG_ROWS, TERMINAL_ROWS, ROW_COLUMNS = 48, 12, 40
TERMINAL_LINE = 79
FINDING_REF = re.compile(r"(?<![\w-])R-\d+(?![\w-])")
FILE_LINE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*([\w-][\w.-]*\.[A-Za-z]\w*)):(\d+)(?:-\d+)?(?![\w:])")
DOC_EXT = re.compile(r"\.(?:md|markdown|txt)$", re.I)
NO_ACTION = "No change was named by the reviewer: decide in the form whether to fix, accept or reject it."


def rows(text):
    """The rows a text takes around the question dialog: a row per line and one more per 40 columns."""
    return sum(1 + len(line) // ROW_COLUMNS for line in str(text).split("\n"))


def unticked(text):
    """Plain text without markdown code ticks and bold marks, for the terminal."""
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", str(text).replace("`", ""))


def doc_name(name):
    """`domain-model.md` -> `domain model`; a name that is no document stays as it is."""
    base = os.path.basename(name.strip())
    return re.sub(r"[-_]+", " ", DOC_EXT.sub("", base)).strip() if DOC_EXT.search(base) else name.strip()


def place(f, code):
    """(plain words for where a finding is, the reference behind them) — the path and line go to the reference."""
    raw = one_line(f.get("where")).rstrip(". ").removesuffix("...").removesuffix("…").strip()
    if not raw:
        return "", None
    if code:
        found = re.fullmatch(r"(.+?):(\d+)", raw)
        path, line = (found.group(1), found.group(2)) if found else (raw, "")
        tip = f"{path}, line {line}" if line else path
        return f"in {os.path.basename(path)}", {"label": os.path.basename(path), "tip": tip, "target": f"path:{path}"}
    head, _, section = raw.partition(" > ")
    name = doc_name(head)
    plain = f"{name} › {section.strip()}" if section.strip() else name
    return plain, {"label": plain, "tip": raw, "target": f"doc:{raw}"}


def plain(text, numbers, refs):
    """A finding's words without internal ids: another finding's id becomes "finding N" (its number in this list),
    a `path/file.py:42` becomes the file's name. Each becomes a reference (`refs`, `{label, tip, target}`): target
    `#<qid>` is another card of the same form, a live link; `path:`, `doc:` and `finding:` targets are not in the form."""
    def finding(m):
        fid = m.group(0)
        n = numbers.get(fid)
        add(refs, {"label": f"finding {n}" if n else "an earlier finding",
                   "tip": f"{fid}, card {n} in this form" if n else f"{fid}, closed before this round; not in this form",
                   "target": f"#{fid}" if n else f"finding:{fid}"})
        return f"finding {n}" if n else "an earlier finding"

    def file_line(m):
        add(refs, {"label": m.group(2), "tip": f"{m.group(1)}, line {m.group(3)}", "target": f"path:{m.group(1)}"})
        return m.group(2)

    return FILE_LINE.sub(file_line, FINDING_REF.sub(finding, one_line(text)))


def add(refs, ref):
    if ref and all((r["target"], r["tip"]) != (ref["target"], ref["tip"]) for r in refs):
        refs.append(ref)


def readable(doc):
    """Each open finding in plain words, in the order of the form's cards:
    [{id, n, title, rest, what, suggested, suggested_by, where, blocking, scenario, refs}].
    `title` is the first sentence (a code review's short summary), `rest` what the finding says after it, `what` the
    whole finding, `suggested` the reviewer's required action, else the one the mod's model wrote, else a fixed line."""
    code = doc.get("source") == "code-review"
    found = doc.get("findings") or []
    numbers = {f.get("id"): n for n, f in enumerate(found, 1)}
    out = []
    for n, f in enumerate(found, 1):
        refs = []
        where, ref = place(f, code)
        add(refs, ref)
        what = plain(f.get("finding"), numbers, refs)
        title = plain(f.get("title") or first_sentence(f.get("finding"), TITLE_LIMIT), numbers, refs)
        head = title.removesuffix("…")
        rest = what[len(head):].strip() if what.startswith(head) else what
        action = one_line(f.get("action"))
        model = one_line(f.get("suggested"))
        suggested, by = ((plain(action, numbers, refs), "reviewer") if action else
                         (plain(model, numbers, refs), "model") if model else ("", "none"))
        if not suggested:
            scenario = one_line(f.get("scenario"))
            word = scenario.split(" ", 1)[0]
            scenario = scenario[:1].lower() + scenario[1:] if word[:1].isupper() and word[1:] == word[1:].lower() else scenario
            suggested = f"Change it so that this no longer happens: {scenario}" if code and scenario else NO_ACTION
        out.append({"id": f.get("id"), "n": n, "title": title, "rest": rest, "what": what, "suggested": suggested,
                    "suggested_by": by, "where": where, "blocking": bool(f.get("blocking")),
                    "scenario": plain(f.get("scenario"), numbers, refs) if f.get("scenario") else "", "refs": refs})
    return out


def needs_suggestion(doc):
    """The ids of the open findings that have neither a required action nor a model's suggestion yet."""
    return [f["id"] for f in doc.get("findings") or [] if not one_line(f.get("action")) and not one_line(f.get("suggested"))]


def label_of(doc):
    return "code review" if doc.get("source") == "code-review" else (doc.get("stage_name") or doc.get("stage") or "review")


def status_word(item):
    return "Blocking" if item["blocking"] else "Not blocking"


def item_block(item, rest_limit, suggested_limit):
    """One finding as Markdown: a heading, then its status and place, what is wrong and the suggested action."""
    meta = f"**{status_word(item)}**" + (f" · {item['where']}" if item["where"] else "")
    lines = [f"### {item['n']} · {item['title']}", f"- {meta}"]
    if item["rest"] and rest_limit:
        lines.append(f"- {clip(item['rest'], rest_limit)}")
    lines.append(f"- **Suggested:** {clip(item['suggested'], suggested_limit)}")
    return "\n".join(lines)


def more_line(left):
    noun = "finding" if left == 1 else "findings"
    return f"…and {left} more {noun}. Pick **Open in form** to see every one."


def fitted(blocks, header, budget, more):
    """The header and as many findings as fit `budget` rows; each finding takes its fullest form that fits, the
    rest are counted on one closing line. `blocks` is a list of [fullest form, …, shortest form] per finding."""
    out, used = [header], rows(header)
    for i, forms in enumerate(blocks):
        left = len(blocks) - i - 1
        reserve = rows(more(left)) + 1 if left else 0
        pick = next((b for b in forms if used + 1 + rows(b) + reserve <= budget), None)
        if pick is None:
            out.append(more(len(blocks) - i))
            return out
        out.append(pick)
        used += 1 + rows(pick)
    return out


def dialog_markdown(doc, budget=DIALOG_ROWS):
    """The findings above the triage dialog on desktop, vscode and mobile: at most `budget` rows."""
    items = readable(doc)
    total, blocking = counts(doc)
    header = (f"## Review findings · {label_of(doc)}\n{total} open, {blocking or 'none'} blocking. "
              "Choose below what happens to them.")
    forms = [[item_block(it, 260, 220), item_block(it, 120, 140), item_block(it, 0, 100)] for it in items]
    return "\n\n".join(fitted(forms, header, budget, more_line))


def dialog_lines(doc, budget=TERMINAL_ROWS):
    """The findings above the triage dialog on the terminal, as plain lines: at most `budget` rows."""
    items = readable(doc)
    total, blocking = counts(doc)
    out = [f"Review findings · {label_of(doc)}: {total} open, {blocking or 'none'} blocking"]
    used = rows(out[0])
    for i, it in enumerate(items):
        head = clip(f"{it['n']}. {unticked(it['title'])}" + (" (blocking)" if it["blocking"] else ""), TERMINAL_LINE)
        tip = "   " + clip(f"Suggested: {unticked(it['suggested'])}", TERMINAL_LINE - 3)
        left = len(items) - i - 1
        tail = clip(unticked(more_line(left)), TERMINAL_LINE) if left else ""
        need = rows(head) + rows(tip) + (rows(tail) if tail else 0)
        if used + need > budget:
            if used + rows(head) + (rows(tail) if tail else 0) <= budget:
                out.append(head)
                used += rows(head)
                continue
            out.append(clip(unticked(more_line(len(items) - i)), TERMINAL_LINE))
            return out
        out += [head, tip]
        used += rows(head) + rows(tip)
    return out


def dialog(doc, findings_file=""):
    """What the mod draws and asks: the triage question (tagged for the mod), the Markdown and the terminal lines."""
    question = triage(doc)
    return {"findings": findings_file, "question": question, "markdown": dialog_markdown(doc),
            "lines": dialog_lines(doc), "needs_suggestion": needs_suggestion(doc),
            "items": [{k: it[k] for k in ("id", "n", "title", "what", "where", "scenario")} for it in readable(doc)]}


def suggest(doc, suggestions):
    """Set the model's suggested action on the findings that have no required action; returns the ids set.
    A finding with the reviewer's own action keeps it, and an empty or over-long suggestion is ignored."""
    done = []
    for f in doc.get("findings") or []:
        text = one_line((suggestions or {}).get(f.get("id")))
        if text and len(text) <= 400 and not one_line(f.get("action")):
            f["suggested"] = text
            done.append(f["id"])
    return done


# ---------------------------------------------------------------- the chat side

def summary(doc):
    """The inline summary block the agent prints before it asks: each finding in plain words, with its suggested
    action; ids, rule codes and paths stay out of the sentences."""
    total, blocking = counts(doc)
    head = f"**Review findings — {label_of(doc)}:** {total} open, {blocking} blocking"
    if not total:
        return head
    lines = []
    for it in readable(doc):
        meta = status_word(it) + (f", {it['where']}" if it["where"] else "")
        lines.append(f"{it['n']}. **{it['title']}** ({meta})" + (f" {clip(it['rest'], SUMMARY_LIMIT)}" if it["rest"] else ""))
        lines.append(f"   **Suggested:** {it['suggested']}")
    return head + "\n\n" + "\n".join(lines)


def question_text(total, blocking):
    noun = "review finding is" if total == 1 else "review findings are"
    count = f"{blocking} blocking" if blocking else "none blocking"
    return f"{total} {noun} open ({count}). What should I do with them?"


def triage(doc):
    """The AskUserQuestion input of the triage question: Accept only when nothing blocks."""
    total, blocking = counts(doc)
    code = doc.get("source") == "code-review"
    options = [{"label": FIX_LABEL, "description": "Fix every open finding now." if code else
                "Fix every open finding. At a stage gate this goes through Request Changes with the findings as the reason."}]
    if not blocking:
        options.append({"label": ACCEPT_LABEL, "description": "Accept all as known risks and go on."})
    options.append({"label": FORM_LABEL, "description": "Sort each finding in a form: fix, accept or reject with a reason."})
    return {"questions": [{"question": question_text(total, blocking), "header": TRIAGE_HEADER,
                           "options": options, "multiSelect": False}], "metadata": {"source": SOURCE}}


# ---------------------------------------------------------------- the developer's answers

ANSWERS_HEADING = "## Review Findings: User Answer"
BOX_WORDS = {"fix": "Fix", "accept": "Accept", "reject": "Reject"}


def sentences(text):
    """A text's sentences, on one line each; a line break also ends one."""
    out = []
    for line in str(text or "").splitlines():
        line = one_line(line)
        out += [p for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(])", line) if p]
    return out


def action_items(item):
    """What will be done for a finding the developer sorted into Fix, in plain words: the suggested action, one item
    per sentence. With no suggested action, the finding itself is the thing to change."""
    if item["suggested_by"] != "none" or item["scenario"]:
        return sentences(item["suggested"])
    return [f"Fix in {item['where']}: {item['title']}" if item["where"] else f"Fix: {item['title']}"]


def answer_summary(doc, picks):
    """The structured summary of the developer's answers, sent in chat as written:

        ## Review Findings: User Answer
        ### R-01: Fix
        #### Action items:
        <one item as a line, several as a bullet list>
        #### User Note:
        <the developer's note, as written>

    `picks` is {finding id: (box, note)}, box fix, accept or reject. Action items only where something is done (Fix);
    the note only where the developer wrote one."""
    lines = [ANSWERS_HEADING]
    for item in readable(doc):
        box, note = picks[item["id"]]
        lines.append(f"### {item['id']}: {BOX_WORDS[box]}")
        if box == "fix":
            items = action_items(item)
            lines.append("#### Action items:")
            lines += items if len(items) == 1 else [f"- {i}" for i in items]
        note = str(note or "").strip()
        if note:
            lines += ["#### User Note:", note]
    return "\n".join(lines)


def picks_of(doc, choice=None, answers=None):
    """{finding id: (box, note)} from a chat answer (`choice` fix or accept, the same for every finding) or a done
    board form's `answers` ({qid: {k: [box], note}})."""
    ids = [f["id"] for f in doc.get("findings") or []]
    if choice:
        if choice not in ("fix", "accept"):
            raise ValueError(f"a chat answer is fix or accept, not {choice!r}")
        return {i: (choice, "") for i in ids}
    answers = answers or {}
    out, missing, unreasoned = {}, [], []
    for i in ids:
        a = answers.get(i) if isinstance(answers.get(i), dict) else {}
        box = (a.get("k") or [""])[0] if isinstance(a.get("k"), list) else ""
        if box not in BOX_WORDS:
            missing.append(i)
            continue
        out[i] = (box, a.get("note") or "")
        if box == "reject" and not out[i][1].strip():
            unreasoned.append(i)
    if missing:
        raise ValueError("the form has no box for " + ", ".join(missing) + ": read the form again (ArtifactData get "
                         "of forms/<id>) once the developer pressed Done")
    if unreasoned:
        raise ValueError("the form rejects " + ", ".join(unreasoned) + " without a reason: a Reject needs its note; read the "
                         "form again (ArtifactData get of forms/<id>) once the developer wrote it")
    return out


def answers_in(data):
    """The `answers` map ({qid: {k, note}}) anywhere in a form document or an ArtifactData result, or None."""
    if isinstance(data, dict):
        found = data.get("answers")
        if isinstance(found, dict) and all(isinstance(v, dict) for v in found.values()):
            return found
        data = list(data.values())
    if isinstance(data, list):
        for value in data:
            found = answers_in(value)
            if found is not None:
                return found
    if isinstance(data, str) and '"answers"' in data:
        try:
            return answers_in(json.loads(data))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- the board

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def active_intent(project_dir):
    """The active intent's directory name, or "" when the project has none."""
    try:
        with open(os.path.join(project_dir, "aidlc", "active-space"), encoding="utf-8") as f:
            space = f.read().strip()
        with open(os.path.join(project_dir, "aidlc", "spaces", space, "intents", "active-intent"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def form_id(doc, project_dir="", now=None):
    """`<intent>-<stage>[-<unit>]-findings-<YYYYMMDDTHHMM>` for AI-DLC, `code-review-<YYYYMMDDTHHMM>` otherwise."""
    stamp = (now or now_utc()).strftime("%Y%m%dT%H%M").lower()  # form ids are [a-z0-9._-]+
    if doc.get("source") == "code-review":
        return f"code-review-{stamp}"
    parts = [active_intent(project_dir) or "aidlc", doc.get("stage") or slug(doc.get("stage_name", "")) or "stage",
             doc.get("unit") or "", "findings", stamp]
    return slug("-".join(p for p in parts if p))


def boxes(code):
    return [
        {"k": "fix", "t": "Fix", "hint": "Fixed now" if code else "Fixed before approval", "tone": "ink"},
        {"k": "accept", "t": "Accept", "hint": "Carried as a known risk", "tone": "muted"},
        {"k": "reject", "t": "Reject", "hint": "Not applicable; write why in the note", "tone": "warn",
         "note": {"required": True, "label": "Why does this not apply?"}},
    ]


def groups(code):
    """The sections of the form's list: what holds the work up, then what can be carried."""
    if code:
        return [{"k": "blocking", "t": "Confirmed", "hint": "The review reproduced these"},
                {"k": "carried", "t": "Possible", "hint": "Not confirmed by the review"}]
    return [{"k": "blocking", "t": "Blocking", "hint": "Approval waits for these"},
            {"k": "carried", "t": "Can be carried", "hint": "Not blocking"}]


def block(label, text):
    text = re.sub(r"\n\s*\n+", "\n", str(text or "").strip())
    return f"**{label}:** {text}" if text else ""


def why(f, code):
    """Why the review suggests what it suggests, in plain words. The card starts undecided: this is only the reason."""
    if code:
        return ("Confirmed by the review, so it is worth fixing" if f.get("blocking") else
                "Possible, not confirmed by the review, so it can be carried")
    sev = f.get("severity") or "Unrated"
    return (f"{sev}: it blocks approval until it is fixed or rejected" if f.get("blocking") else
            f"{sev}: it can be carried as a known risk")


def card(item, f, code, reviewer=""):
    """One board card. `ctx` holds the plain words for a page that draws only it. The optional `plain` (what the
    finding means, under the title), `action` (the suggested action), `refs` and `detail` (ctx without the two) are
    for a page that draws them apart (question-forms § 5)."""
    detail = [block("Where", item["where"])]
    if code:
        detail.append(block("What goes wrong", item["scenario"]))
    detail = [b for b in detail if b]
    who = reviewer or ("Code review" if code else "AI review")
    return {
        "n": item["n"], "text": item["title"] or item["id"],
        "ctx": "\n\n".join(b for b in [block("What's wrong", item["what"]), block("Suggested", item["suggested"])] + detail if b),
        "kind": "card", "group": "blocking" if f.get("blocking") else "carried",
        "severity": f.get("severity") or (("Confirmed" if f.get("blocking") else "Possible") if code else "Unrated"),
        **({"blocking": "Blocking" if code else "Blocks approval"} if f.get("blocking") else {}),
        **({"plain": item["rest"]} if item["rest"] else {}), "action": item["suggested"],
        "detail": "\n\n".join(detail), "refs": item["refs"],
        "from": ", ".join(p for p in (who, f.get("severity"), f.get("category")) if p),
        "proposed": {"k": "fix" if f.get("blocking") else "accept", "why": why(f, code)},
        "outcomes": {"fix": "Fixed now, in the code." if code else "Goes into Request Changes; fixed, then reviewed again.",
                     "accept": "Carried as a known risk; no change.",
                     "reject": "Not applicable; your note says why."},
    }


def ids_lib():
    """The shared id map (aidlc_ids.py beside this file, a copy of shared/aidlc-ids/aidlc_ids.py), or None."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aidlc_ids.py")
    spec = importlib.util.spec_from_file_location("aidlc_ids", path)
    if spec is None or not os.path.isfile(path):
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def card_text(c):
    """Every text a card shows, for the ids it mentions."""
    refs = " ".join(f"{r.get('label', '')} {r.get('tip', '')}" for r in c.get("refs") or [])
    return "\n".join(str(c.get(k) or "") for k in ("text", "plain", "action", "ctx", "detail", "from")) + "\n" + refs


def ids_for(doc, cards, project_dir):
    """The form's `ids` map ({id: {kind, title, text, doc, line}}) for the ids the cards mention, from the project's
    id map (synced first), each defined nearest the reviewed document; ({}, why) when there is none."""
    lib = ids_lib()
    if lib is None:
        return {}, "aidlc_ids.py is missing"
    project = lib.project_dir(project_dir or None)
    folder = lib.intent_dir(project)
    if not folder or not os.path.isdir(folder):
        return {}, "no active AI-DLC intent"
    lib.sync(folder)
    near = []
    if doc.get("artifact"):
        art = doc["artifact"] if os.path.isabs(doc["artifact"]) else os.path.join(project, doc["artifact"])
        near += [art, os.path.dirname(art)]
    return lib.refs(folder, "\n\n".join(card_text(c) for c in cards), near), ""


def board(doc, fid, title, out_dir, now=None, project_dir=""):
    """Write forms.json, cards/<qid>.json and writes.json for one ArtifactData batch; returns a summary dict.
    The form's `ids` maps every id the cards mention to its definition, for the page's tooltips and links."""
    if not doc.get("findings"):
        raise ValueError("there are no open findings, so there is nothing to sort")
    if incomplete(doc):
        raise ValueError(incomplete(doc))
    code = doc.get("source") == "code-review"
    out = os.path.abspath(out_dir)
    os.makedirs(os.path.join(out, "cards"), exist_ok=True)
    row = {"title": title, "status": "open", "createdAt": (now or now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "view": "board", "boxes": boxes(code), "groups": groups(code)}
    if doc.get("stage_name") and not code:
        row["stage"] = doc["stage_name"]
    if doc.get("artifact"):
        row["file"] = doc["artifact"]
    cards = [(f["id"], card(item, f, code, doc.get("reviewer", ""))) for item, f in zip(readable(doc), doc["findings"])]
    try:
        ids, why = ids_for(doc, [c for _, c in cards], project_dir)
    except Exception as exc:  # noqa: BLE001 - the board is written without tooltips rather than not at all
        ids, why = {}, f"the id map could not be read ({exc})"
    if ids:
        row["ids"] = ids
    writes = [{"op": "set", "collection": "forms", "doc_id": fid, "file_path": os.path.join(out, "forms.json")}]
    dump(os.path.join(out, "forms.json"), row)
    for qid, c in cards:
        path = os.path.join(out, "cards", re.sub(r"[^A-Za-z0-9._-]", "_", qid) + ".json")
        dump(path, c)
        writes.append({"op": "set", "collection": f"forms/{fid}/questions", "doc_id": qid, "file_path": path})
    dump(os.path.join(out, "writes.json"), writes, indent=2)
    result = {"id": fid, "cards": len(cards), "writes": os.path.join(out, "writes.json"), "ids": len(ids)}
    if why:
        result["ids_note"] = why
    return result


def dump(path, data, indent=2):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------- the guard's saved findings

def state_dir():
    return os.environ.get("REVIEW_FINDINGS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "review-findings")


def recorded(findings_file):
    """(chat choice, form answers) the guard recorded beside a saved findings file (`<session>.json`)."""
    state_file = re.sub(r"\.findings$", "", findings_file) + ".json"
    try:
        with open(state_file, encoding="utf-8") as f:
            pend = (json.load(f) or {}).get("pending") or {}
    except (OSError, ValueError):
        raise ValueError("no recorded answer beside this findings file: pass --choice fix|accept or --form FILE") from None
    if pend.get("answer") in ("fix", "accept"):
        return pend["answer"], None
    form = pend.get("form") or {}
    if pend.get("answer") == "form" and form.get("done") and isinstance(form.get("answers"), dict):
        return None, form["answers"]
    if pend.get("answer") == "form":
        raise ValueError("the form is not read as done yet: read forms/<id> with ArtifactData get once the developer "
                         "pressed Done")
    raise ValueError("the developer has not answered the Findings question yet")


def session_findings(session):
    """Where the guard saves a session's pending findings (`<state dir>/<session>.findings`)."""
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session or "default"))
    return os.path.join(state_dir(), sid + ".findings")


# ---------------------------------------------------------------- command line

def read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_findings(path):
    doc = json.loads(read(path))
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        raise ValueError(f"{path} is not a findings document (parse a brief, a review or a ReportFindings input first)")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--brief")
    src.add_argument("--review")
    src.add_argument("--report")
    p.add_argument("--stage", help="the stage slug (a brief names only the stage's title)")
    p.add_argument("--unit")
    for name in ("summary", "question"):
        sub.add_parser(name).add_argument("--findings", required=True)
    a = sub.add_parser("answers")
    a.add_argument("--findings", required=True)
    pick = a.add_mutually_exclusive_group()
    pick.add_argument("--choice", choices=("fix", "accept"), help="the chat answer, for every finding")
    pick.add_argument("--form", help="the done form's document (or the ArtifactData get result) as JSON")
    d = sub.add_parser("dialog")
    which = d.add_mutually_exclusive_group(required=True)
    which.add_argument("--findings")
    which.add_argument("--session", help="the session id: reads the findings the guard saved for it")
    g = sub.add_parser("suggest")
    g.add_argument("--findings", required=True)
    g.add_argument("--set", required=True, help='JSON {"<finding id>": "<suggested action>"}')
    b = sub.add_parser("board")
    b.add_argument("--findings", required=True)
    b.add_argument("--id")
    b.add_argument("--title")
    b.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    b.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "parse":
            if args.brief:
                doc = parse_brief(read(args.brief), args.stage)
            elif args.review:
                doc = parse_review(read(args.review), args.stage)
            else:
                doc = parse_report(json.loads(read(args.report)))
            if args.unit:
                doc["unit"] = args.unit
            print(json.dumps(doc, indent=2, ensure_ascii=False))
        elif args.cmd == "summary":
            doc = load_findings(args.findings)
            if incomplete(doc):
                raise ValueError(incomplete(doc))
            print(summary(doc))
        elif args.cmd == "answers":
            doc = load_findings(args.findings)
            choice, answers = args.choice, None
            if args.form:
                answers = answers_in(json.loads(read(args.form)))
                if answers is None:
                    raise ValueError(f"{args.form} holds no form answers")
            elif not choice:
                choice, answers = recorded(args.findings)
            print(answer_summary(doc, picks_of(doc, choice, answers)))
        elif args.cmd == "dialog":
            path = args.findings or session_findings(args.session)
            doc = load_findings(path)
            if incomplete(doc):
                raise ValueError(incomplete(doc))
            if not doc["findings"]:
                raise ValueError("there are no open findings")
            print(json.dumps(dialog(doc, os.path.abspath(path)), ensure_ascii=False))
        elif args.cmd == "suggest":
            doc = load_findings(args.findings)
            done = suggest(doc, json.loads(args.set))
            if done:
                dump(args.findings, doc, indent=1)
            print(json.dumps({"set": done}))
        elif args.cmd == "question":
            doc = load_findings(args.findings)
            if incomplete(doc):
                raise ValueError(incomplete(doc))
            print(json.dumps(triage(doc), indent=2, ensure_ascii=False))
        else:
            doc = load_findings(args.findings)
            code = doc.get("source") == "code-review"
            title = args.title or "Review findings · " + ("code review" if code else doc.get("stage_name") or doc.get("stage") or "review")
            result = board(doc, args.id or form_id(doc, args.project_dir), title, args.out, project_dir=args.project_dir)
            print(json.dumps(result))
    except (OSError, ValueError) as why:
        print(f"findings.py: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
