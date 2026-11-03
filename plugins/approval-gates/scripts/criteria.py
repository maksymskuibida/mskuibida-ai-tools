#!/usr/bin/env python3
"""What a per-stage gate is judged against: the criteria the agent checks the stage by, gathered by a script.

gate_bundle.py draft calls `gather(...)` and writes the result as `criteria.json`; the agent gives every criterion a
verdict (holds, fails, n/a) in judgment.json, and the page shows them under "Rules checked".

    criterion: {key, origin, title, text, source}
      origin  stage    the engine's own definition of the stage (`.claude/aidlc-common/stages/<phase>/<slug>.md`):
                       its Constraints, and the bullets of the steps that say what the stage writes
              review   the reviewer's checklist (`.claude/agents/<reviewer>.md`): its Core Review Questions and the
                       "What to Check" subsection named after the stage
              rule     the project's settled rules (the stage graph's `rules_in_context`, else the space's
                       `memory/{org,team,project}.md` and `memory/phases/<phase>.md`): every NEVER / ALWAYS / MUST
                       bullet and every bullet under a Forbidden or Mandated heading
              earlier  what an earlier stage settled: one per document the stage consumes that an earlier stage wrote
      key     `<origin>-<n>` (`earlier-<artifact>` for an earlier stage), stable for one draft
      source  `path:<project-relative file>#L<line>`

Nothing is clipped: a criterion's text is the source's words, whole. Every source is optional; a project with none of
them gets no criteria and the agent judges the stage on its documents alone. Standard library only.
"""

import os
import re

STAGE_SECTIONS = re.compile(r"constraint|generate|artifact|output|completeness", re.I)
RULE_WORD = re.compile(r"^(?:\*\*)?(NEVER|ALWAYS|MUST)\b")
RULE_HEADING = re.compile(r"forbidden|mandated|rules?\b|must", re.I)
MAX_STAGE, MAX_REVIEW, MAX_RULES = 30, 30, 80
ORIGINS = ("stage", "review", "rule", "earlier")


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def strip_frontmatter(text):
    """(body, offset in lines) of a file that may open with a `---` YAML block."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[:end + 4]
            return text[end + 4:], head.count("\n")
    return text, 0


def frontmatter_value(text, key):
    found = re.search(r"^" + re.escape(key) + r":\s*(\S.*)$", text.split("\n---", 1)[0] if text.startswith("---") else "", re.M)
    return found.group(1).strip().strip("\"'") if found else ""


def bullets(lines, start):
    """[(line number, text)] of the top-level bullets and numbered items of `lines` (1-based numbers from `start`); a
    continuation line indented under a bullet joins it, a nested bullet joins it as a sentence."""
    out, fence = [], False
    for n, line in enumerate(lines, start):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        top = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        if top:
            out.append([n, top.group(1).strip()])
            continue
        if out and line.startswith((" ", "\t")) and line.strip():
            out[-1][1] += " " + re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line.strip())
            continue
        if not line.strip() and out:
            out[-1].append("end")
    return [(n, " ".join(t.split())) for n, t, *_ in out]


def paragraphs(lines, start):
    """[(line number, text)] of the plain paragraphs (not bullets, headings, tables or code)."""
    out, cur, fence = [], None, False
    for n, line in enumerate(lines, start):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            cur = None
            continue
        if fence or not s or s.startswith(("#", "|", "-", "*", ">")) or re.match(r"^\d+[.)]\s", s):
            cur = None
            continue
        if cur is None:
            cur = [n, s]
            out.append(cur)
        else:
            cur[1] += " " + s
    return [(n, t) for n, t in out]


def sections(text, level):
    """[(heading, first line number of the body, body lines)] for every heading of `level` (`##` or `###`)."""
    out, cur = [], None
    marker = "#" * level + " "
    deeper = "#" * (level - 1) + " " if level > 1 else None
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith(marker):
            cur = [line[len(marker):].strip(), n + 1, []]
            out.append(cur)
            continue
        if cur is not None and re.match(r"^#{1,%d}\s" % (level - 1), line):
            cur = None
            continue
        if cur is not None:
            cur[2].append(line)
    return [(h, s, b) for h, s, b in out]


def title_of(text):
    """The criterion's name: a bold lead (`**rules.md**: …`), else its first sentence, whole."""
    bold = re.match(r"^\*\*([^*]+)\*\*:?\s*", text)
    if bold:
        return bold.group(1).strip().rstrip(":")
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return first.strip()


def plain(text):
    return re.sub(r"\s+", " ", re.sub(r"`([^`]*)`", r"\1", text)).strip()


def stage_file(project, phase, slug):
    base = os.path.join(project, ".claude", "aidlc-common", "stages")
    first = os.path.join(base, phase or "", slug + ".md")
    if phase and os.path.isfile(first):
        return first
    try:
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name, slug + ".md")
            if os.path.isfile(path):
                return path
    except OSError:
        pass
    return None


def from_stage(project, path):
    text = read(path)
    if not text:
        return [], ""
    reviewer = frontmatter_value(text, "reviewer")
    body, offset = strip_frontmatter(text)
    out = []
    for heading, start, lines in sections(body, 2) + sections(body, 3):
        if not STAGE_SECTIONS.search(heading) or re.search(r"execution modes", heading, re.I):
            continue
        found = bullets(lines, start + offset)
        if re.search(r"constraint", heading, re.I):
            found = paragraphs(lines, start + offset) + found
        for n, t in found:
            out.append((n, t))
    seen, unique = set(), []
    for n, t in sorted(out):
        if t not in seen and len(t) > 12:
            seen.add(t)
            unique.append((n, t))
    rel = os.path.relpath(path, project)
    return [{"origin": "stage", "title": plain(title_of(t)), "text": t, "source": f"path:{rel}#L{n}"}
            for n, t in unique[:MAX_STAGE]], reviewer


def from_reviewer(project, reviewer, stage_name):
    if not reviewer:
        return []
    path = os.path.join(project, ".claude", "agents", reviewer + ".md")
    text = read(path)
    if not text:
        return []
    rel = os.path.relpath(path, project)
    out = []
    for heading, start, lines in sections(text, 2):
        if re.search(r"core review questions", heading, re.I):
            out += bullets(lines, start)
    want = re.sub(r"[^a-z0-9]+", " ", stage_name.lower()).strip()
    for heading, start, lines in sections(text, 3):
        if re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip() == want:
            out += bullets(lines, start)
    return [{"origin": "review", "title": plain(title_of(t)), "text": t, "source": f"path:{rel}#L{n}"}
            for n, t in out[:MAX_REVIEW]]


def rule_files(project, space, phase, graph_stage):
    """The graph's `rules_in_context` and the active space's memory files (the graph may name another space's copy), each once."""
    paths = [r.get("path") for r in (graph_stage or {}).get("rules_in_context") or [] if isinstance(r, dict) and r.get("path")]
    memory = os.path.join("aidlc", "spaces", space, "memory")
    paths += [os.path.join(memory, n) for n in ("org.md", "team.md", "project.md")]
    if phase:
        paths.append(os.path.join(memory, "phases", phase + ".md"))
    out, seen = [], set()
    for p in paths:
        full = os.path.realpath(os.path.join(project, p))
        if full not in seen and os.path.isfile(full):
            seen.add(full)
            out.append(os.path.join(project, p))
    return out


def from_rules(project, paths):
    out, seen = [], set()
    for path in paths:
        text = read(path)
        if not text:
            continue
        rel = os.path.relpath(path, project)
        heading = ""
        for n, line in enumerate(text.splitlines(), 1):
            found = re.match(r"^#{1,4}\s+(.*)$", line)
            if found:
                heading = found.group(1)
                continue
            item = re.match(r"^[-*]\s+(.*)$", line)
            if not item:
                continue
            t = " ".join(item.group(1).split())
            if (RULE_WORD.match(t) or RULE_HEADING.search(heading)) and t not in seen:
                seen.add(t)
                out.append({"origin": "rule", "title": plain(title_of(t) if t.startswith("**") else t), "text": t, "source": f"path:{rel}#L{n}"})
    return out[:MAX_RULES]


def from_earlier(project, root, stage_folder, graph, graph_stage):
    """One criterion per document the stage consumes that an earlier stage of the intent wrote."""
    out, names = [], []
    for c in (graph_stage or {}).get("consumes") or []:
        name = c.get("artifact") if isinstance(c, dict) else c
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    if not names:
        return []
    found = {}
    here = os.path.abspath(stage_folder)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("audit", "reviews")]
        if os.path.abspath(dirpath) == here:
            continue
        for name in names:
            for ext in (".md", ".json"):
                if name + ext in filenames and name not in found:
                    found[name] = os.path.join(dirpath, name + ext)
    for name in names:
        path = found.get(name)
        if not path:
            continue
        slug = os.path.basename(os.path.dirname(path))
        stage = ((graph or {}).get(slug) or {}).get("name") or " ".join(w.capitalize() for w in slug.split("-"))
        rel = os.path.relpath(path, project)
        out.append({"key": "earlier-" + re.sub(r"[^a-z0-9-]+", "-", name.lower()), "origin": "earlier",
                    "title": f"Agrees with {stage}: {os.path.basename(path)}",
                    "text": f"What {stage} settled in {os.path.basename(path)} still holds in this stage: nothing it decided "
                            "is contradicted, dropped or quietly changed.",
                    "source": f"path:{rel}#L1"})
    return out


def gather(project, root, space, phase, slug, stage_name, stage_folder, graph=None, graph_stage=None):
    """Every criterion for this stage, keyed and in origin order: stage, review, rule, earlier."""
    path = stage_file(project, phase, slug)
    stage, reviewer = from_stage(project, path) if path else ([], "")
    reviewer = (graph_stage or {}).get("reviewer") or reviewer
    found = {"stage": stage, "review": from_reviewer(project, reviewer, stage_name),
             "rule": from_rules(project, rule_files(project, space, phase, graph_stage)),
             "earlier": from_earlier(project, root, stage_folder, graph, graph_stage)}
    out = []
    for origin in ORIGINS:
        for n, c in enumerate(found[origin], 1):
            out.append(dict(c, key=c.get("key") or f"{origin}-{n}"))
    return out
