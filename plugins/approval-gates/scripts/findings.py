#!/usr/bin/env python3
"""Review findings at an AI-DLC approval gate: parse them, keep the model's titles and suggested actions, and lay out
the ones the agent could not fix for certain as cards on the gate's page (moved here from the review-findings plugin).

  parse --brief FILE [--stage S] [--unit U]
                            the open findings of the text `aidlc engine review-brief review --stage S` prints
  parse --review FILE       the open findings of a readable `reviews/review-NN.md` (the 6-column `### Findings` table)
  suggest --findings FILE --set JSON
                            record a cheap model's suggested action ({"<id>": "…"}, or "none" for nothing to change) on
                            findings that have no required action
  titles --findings FILE --set JSON
                            record a short title per finding ({"<id>": "…"}); a title that is empty, over the limit or
                            has an unbalanced backtick is refused with what to fix
  cards --findings FILE     the `findings` field of the gate row, as JSON (gate_bundle.py --findings writes it for you)

A findings document is JSON:
  {"source": "aidlc", "stage": "<slug>", "unit"?, "stage_name": "Domain Design", "artifact": "<path>",
   "findings": [{"id", "severity", "where", "finding", "action", "status", "blocking", "title", "suggested"?, "short"?}],
   "carried"?: [{"id", "answer"}]}
`findings` holds the OPEN findings only (Status New or Unresolved). Blocking is severity Critical or Major.
`carried` are open findings the developer sorted Accept or Reject in an earlier round (the guard's memory).

`-` as a file reads stdin. Standard library only; the guard hook imports this file by path.
"""

import argparse
import datetime
import json
import os
import re
import sys

BLOCKING_SEVERITIES = {"critical", "major"}
OPEN_STATUSES = {"new", "unresolved"}
FINDING_ID = re.compile(r"^[A-Za-z]+-\d+$")
QUOTE = re.compile(r"^>\s*([A-Za-z]+-\d+)\s+(Finding|Where|Required action):\s*(.*)$")
FIELD_NAMES = {"finding": "finding", "where": "where", "required action": "action"}
TITLE_TARGET = 70  # a card title aims at this many characters ...
TITLE_LIMIT = 100  # ... and never exceeds this many


# ---------------------------------------------------------------- text helpers

def one_line(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clip(text, limit):
    text = one_line(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


SPAN = re.compile(r"`[^`]+`|\*\*[^*]+\*\*|\[[^\]]*\]\([^)]*\)")


def spans(text):
    """The (start, end) of every inline-code span, bold span and link in a text: a cut never falls inside one."""
    return [m.span() for m in SPAN.finditer(text)]


def whole_phrase(text):
    """True when a text has no unbalanced backtick."""
    return text.count("`") % 2 == 0


def boundaries(text, covered):
    """The cut points of a one-line text outside every span, as (position, kind), kind sentence | clause | word:
    the title is text[:position]; what follows starts at a word."""
    out = []
    for i, ch in enumerate(text):
        if i == 0 or any(a < i < b for a, b in covered):
            continue
        before = text[i - 1]
        if ch == " ":
            if before in ".!?" and re.match(r"[A-Z0-9`\"'(*\[]", text[i + 1:i + 2]):
                out.append((i - 1, "sentence", i))
            elif before in ",;:":
                out.append((i - 1, "clause", i))
            elif text[i:i + 3] == " — " or text[i:i + 3] == " – ":
                out.append((i, "clause", i + 3))
            else:
                out.append((i, "word", i))
    return out


def split_title(text, target=TITLE_TARGET, limit=TITLE_LIMIT):
    """(title, rest) of a finding without a model's title. The title is a whole phrase: a sentence when one ends within
    `limit`, else up to the last clause or word boundary within `target` (the first one past it within `limit`).
    It is never cut inside a code span, bold span or link, so its backticks balance, and the rest starts at a word.
    With no good cut (a long span first, or no space) the title is the first words without backticks, ending in
    "…", and `rest` is the whole text. A single sentence that fits `limit` is its own title and has no rest."""
    text = one_line(text)
    cuts = [c for c in boundaries(text, spans(text)) if c[0] <= limit]
    sentence = [c for c in cuts if c[1] == "sentence" and c[0] >= 3]
    if sentence:
        end, _, start = sentence[0]
        return text[:end + 1].rstrip(), text[start:].strip()  # the title keeps its full stop
    if len(text) <= limit:
        return text, ""
    for kinds in (("clause",), ("word",)):
        fitting = [c for c in cuts if c[1] in kinds and c[0] >= 15]
        before = [c for c in fitting if c[0] <= target]
        after = [c for c in fitting if c[0] > target]
        # a span across the target pushes the cut before it, or past it when that still fits and the front is short
        pick = before[-1] if before and (before[-1][0] >= 25 or not after) else (after[0] if after else None)
        if pick:
            end, kind, start = pick
            title = text[:end].rstrip(" ,;:—–")
            if kind == "word":
                return title + "…", text
            return title, text[start:].strip()
    bare = text.replace("`", "")
    head = bare[:target + 1]
    space = head.rfind(" ")
    return (head[:space] if space > 15 else bare[:target]).rstrip(" ,;:—–.") + "…", text


def refuse_title(title):
    """Why a model's short title is not accepted, in words that say what to fix; "" when it is."""
    title = one_line(title)
    if not title:
        return "empty: write a short title"
    if len(title) > TITLE_LIMIT:
        return f"too long: {len(title)} > {TITLE_LIMIT} characters; aim for {TITLE_TARGET} or fewer, a whole phrase"
    if not whole_phrase(title):
        return "unbalanced backtick: close every `code` span or leave the code out"
    if title.endswith(("…", "...")):
        return "ends in an ellipsis: write a whole phrase, not a cut one"
    return ""


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
            "title": split_title(finding)[0]}


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
FINDING_REF = re.compile(r"(?<![\w-])R-\d+(?![\w-])")
FILE_LINE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*([\w-][\w.-]*\.[A-Za-z]\w*)):(\d+)(?:-\d+)?(?![\w:])")
DOC_EXT = re.compile(r"\.(?:md|markdown|txt)$", re.I)
NOT_WORTH = "none"
NOT_WORTH_LINE = "Nothing to change: the model judged this not worth fixing."
NO_ACTION = "No change was named by the reviewer: decide on the page whether to fix, accept or reject it."


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
    `title` is the model's short title, else a whole sentence or clause cut by `split_title` (never inside a code span),
    `rest` the card's body (the whole finding with a model's title, else what follows the cut), `what` the whole finding, `suggested` the reviewer's required action, else the one the mod's model wrote, else a fixed line."""
    code = doc.get("source") == "code-review"
    found = doc.get("findings") or []
    numbers = {f.get("id"): n for n, f in enumerate(found, 1)}
    out = []
    for n, f in enumerate(found, 1):
        refs = []
        where, ref = place(f, code)
        add(refs, ref)
        what = plain(f.get("finding"), numbers, refs)
        short = one_line(f.get("short"))
        if short and not refuse_title(short):
            title, rest = plain(short, numbers, refs), what  # a model's title: the body is the whole finding
        else:
            title, rest = split_title(what)
        action = one_line(f.get("action"))
        model = one_line(f.get("suggested"))
        skip = not action and model.rstrip(". ").lower() == NOT_WORTH
        suggested, by = ((plain(action, numbers, refs), "reviewer") if action else
                         (NOT_WORTH_LINE, "skip") if skip else
                         (plain(model, numbers, refs), "model") if model else ("", "none"))
        if not suggested:
            scenario = one_line(f.get("scenario"))
            word = scenario.split(" ", 1)[0]
            scenario = scenario[:1].lower() + scenario[1:] if word[:1].isupper() and word[1:] == word[1:].lower() else scenario
            suggested = f"Change it so that this no longer happens: {scenario}" if code and scenario else NO_ACTION
        out.append({"id": f.get("id"), "n": n, "title": title, "rest": rest, "what": what, "suggested": suggested,
                    "suggested_by": by, "where": where, "blocking": bool(f.get("blocking")),
                    "has_action": by in ("reviewer", "model"),
                    "scenario": plain(f.get("scenario"), numbers, refs) if f.get("scenario") else "", "refs": refs})
    return out


def needs_suggestion(doc):
    """The ids of the open findings that have neither a required action nor a model's suggestion yet."""
    return [f["id"] for f in doc.get("findings") or [] if not one_line(f.get("action")) and not one_line(f.get("suggested"))]


def needs_title(doc):
    """The ids of the open findings that have no model-written short title yet."""
    return [f["id"] for f in doc.get("findings") or [] if refuse_title(f.get("short"))]


def reopens(doc):
    """How many open findings of a stage review are proposed Fix (blocking: Request Changes re-opens the stage).
    A code review never re-opens anything: its Fix is a cheap in-code change."""
    if doc.get("source") == "code-review":
        return 0
    return counts(doc)[1]


def proposal(item, doc):
    """The proposed pick for a finding: blocking is Fix; once a stage is re-opened anyway, so is every minor finding
    that has a real action to take. Returns "fix" or "accept"."""
    if item["blocking"] or (reopens(doc) and item["has_action"]):
        return "fix"
    return "accept"


def suggest(doc, suggestions):
    """Set the model's suggested action on the findings that have no required action; returns the ids set.
    A finding with the reviewer's own action keeps it, and an empty or over-long suggestion is ignored."""
    done = []
    for f in doc.get("findings") or []:
        text = one_line((suggestions or {}).get(f.get("id")))
        if text and len(text) <= 400 and not one_line(f.get("action")):  # "none" marks it not worth fixing
            f["suggested"] = text
            done.append(f["id"])
    return done


def titles(doc, given):
    """Store the model's short title per finding ({"<id>": "…"}): (ids set, {id: why refused}). A refused title is not
    stored, and the message says what to fix so the agent writes it again. An id that is not an open finding is refused."""
    known = {f.get("id"): f for f in doc.get("findings") or []}
    done, refused = [], {}
    for fid, raw in (given or {}).items():
        if fid not in known:
            refused[fid] = "not an open finding of this review"
            continue
        why = refuse_title(raw)
        if why:
            refused[fid] = why
            continue
        known[fid]["short"] = one_line(raw)
        known[fid]["title"] = one_line(raw)
        done.append(fid)
    return done, refused


# ---------------------------------------------------------------- the gate page

ANSWERED_WORDS = {"accept": "accepted", "reject": "rejected"}
PICKS = ("fix", "accept", "reject")


def answered_line(doc):
    """One line naming the findings the developer sorted in an earlier round of the same stage (and Unit) that the
    engine still lists as open ("Already answered: R-07, R-08 (accepted)"); "" when there are none."""
    groups = {}
    for item in doc.get("carried") or []:
        groups.setdefault(ANSWERED_WORDS.get(item.get("answer"), str(item.get("answer"))), []).append(item["id"])
    if not groups:
        return ""
    return "Already answered: " + "; ".join(f"{', '.join(ids)} ({word})" for word, ids in groups.items())


def why(f, reopen=0):
    """Why the page suggests what it suggests, in plain words. A card starts unsorted: this is only the reason."""
    sev = f.get("severity") or "Unrated"
    if f.get("blocking"):
        return f"{sev}: it blocks approval until it is fixed or rejected"
    if reopen:
        return (f"{sev}: the stage is re-opened anyway for {reopen} blocking finding{'s' if reopen != 1 else ''}, "
                "so fixing this now costs little")
    return f"{sev}: it can be carried as a known risk"


def missing_for_page(doc):
    """What the page cannot show yet, as one line per problem: no finding text (a cut-off brief), no suggested action."""
    out = []
    if incomplete(doc):
        out.append(incomplete(doc))
    lacking = needs_suggestion(doc)
    if lacking:
        out.append(f"no suggested action for {', '.join(lacking)}: have a cheap model write one (a Haiku subagent) and "
                   "record it with `findings.py suggest --findings <file> --set '{\"<id>\": \"<action>\"}'` (\"none\" when "
                   "nothing needs to change)")
    return out


def cards(doc):
    """The gate row's `findings` field: {stage, unit?, artifact?, open, blocking, items[], carried[]}. Each item is one
    card the developer sorts on the page (Fix, Accept, Reject with a note; Accept only when it does not block)."""
    problems = missing_for_page(doc)
    if problems:
        raise ValueError("; ".join(problems))
    total, blocking = counts(doc)
    reopen = reopens(doc)
    items = []
    for item, f in zip(readable(doc), doc.get("findings") or []):
        items.append({
            "id": f["id"], "n": item["n"], "title": item["title"] or f["id"],
            **({"plain": item["rest"]} if item["rest"] else {}),
            "action": item["suggested"], "actionBy": item["suggested_by"],
            **({"where": item["where"]} if item["where"] else {}),
            "severity": f.get("severity") or "Unrated", "blocking": bool(f.get("blocking")),
            "proposed": proposal(item, doc), "why": why(f, reopen if not f.get("blocking") and item["has_action"] else 0),
            "refs": item["refs"],
        })
    out = {"stage": doc.get("stage", ""), "stageName": doc.get("stage_name", ""), "open": total, "blocking": blocking,
           "items": items, "carried": [{"id": c["id"], "answer": c["answer"]} for c in doc.get("carried") or []]}
    for key in ("unit", "artifact"):
        if doc.get(key):
            out[key] = doc[key]
    return out


def picks_in(row):
    """{finding id: {pick, note}} the page saved on a gate row (the `findingPicks` field of an ArtifactData get result,
    or of the row itself); only valid picks."""
    data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else row
    raw = (data or {}).get("findingPicks") if isinstance(data, dict) else None
    out = {}
    for fid, value in (raw or {}).items() if isinstance(raw, dict) else []:
        if isinstance(value, dict) and value.get("pick") in PICKS:
            out[str(fid)] = {"pick": value["pick"], "note": one_line(value.get("note"))}
    return out


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def dump(path, data, indent=2):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------- command line

def read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_findings(path):
    doc = json.loads(read(path))
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        raise ValueError(f"{path} is not a findings document (parse a brief or a review first)")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--brief")
    src.add_argument("--review")
    p.add_argument("--stage", help="the stage slug (a brief names only the stage's title)")
    p.add_argument("--unit")
    g = sub.add_parser("suggest")
    g.add_argument("--findings", required=True)
    g.add_argument("--set", required=True, help='JSON {"<finding id>": "<suggested action>"}')
    t = sub.add_parser("titles")
    t.add_argument("--findings", required=True)
    t.add_argument("--set", required=True, help='JSON {"<finding id>": "<short title>"}')
    sub.add_parser("cards").add_argument("--findings", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "parse":
            doc = parse_brief(read(args.brief), args.stage) if args.brief else parse_review(read(args.review), args.stage)
            if args.unit:
                doc["unit"] = args.unit
            print(json.dumps(doc, indent=2, ensure_ascii=False))
        elif args.cmd == "suggest":
            doc = load_findings(args.findings)
            done = suggest(doc, json.loads(args.set))
            if done:
                dump(args.findings, doc, indent=1)
            print(json.dumps({"set": done, "still_missing": needs_suggestion(doc)}))
        elif args.cmd == "titles":
            doc = load_findings(args.findings)
            done, refused = titles(doc, json.loads(args.set))
            if done:
                dump(args.findings, doc, indent=1)
            print(json.dumps({"set": done, "refused": refused, "still_missing": needs_title(doc)}, ensure_ascii=False))
            if refused:
                print("findings.py: refused titles, write them again: " + "; ".join(f"{k}: {v}" for k, v in refused.items()),
                      file=sys.stderr)
                return 1
        else:
            print(json.dumps(cards(load_findings(args.findings)), indent=2, ensure_ascii=False))
    except (OSError, ValueError) as why_not:
        print(f"findings.py: {why_not}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
