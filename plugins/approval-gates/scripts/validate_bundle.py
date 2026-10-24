#!/usr/bin/env python3
"""Check a gate bundle against its contract.

    validate_bundle.py <bundle.json> [--order]

The contract is `contract/gate-bundle.schema.json` (the shape) and `contract/README.md` (the cross-field rules).
This script reads the schema file itself, so the two cannot drift: it interprets the subset of JSON Schema that
file uses (type, const, enum, pattern, minLength, maxLength, minimum, maximum, required, properties,
additionalProperties: false, items, minItems, maxItems and local $ref), then checks the rules a schema cannot say:

  - a plan page has `plan` and no `design`; a unit-end page has `design` and no `plan`;
  - each page uses only its own section kinds, and every section key is unique and not plan/answers/design;
  - rows of a `built` section are labelled core, main or minor; every other row critical, high, medium or low;
  - "look first" only on critical or high rows;
  - every id and anchor (rows, steps `step-<n>`, questions, sections) is unique; every `#` target resolves;
  - steps are numbered 1, 2, 3 … in build order;
  - a revision mark is at most the bundle's revision and carries a note; `revisions` lists 1 … revision;
  - `asApproved` only on a changes section, and only with no rows; a map only on a built section.

Exit 0 and print `ok` (with --order, the section order a renderer shows), or exit 1 and print one problem per line.
Standard library only.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(os.path.dirname(HERE), "contract", "gate-bundle.schema.json")

SEVERITY = ("critical", "high", "medium", "low")
WEIGHT = ("core", "main", "minor")
RANK = {"critical": 0, "high": 1, "core": 1, "medium": 2, "main": 2, "low": 3, "minor": 3}
PAGE_KINDS = {
    "plan": {"narrows", "assumptions", "findings", "visible", "tests", "other"},
    "unit-end": {"changes", "unverified", "built", "other"},
}
RESERVED_KEYS = {"plan", "answers", "design"}
PLAN_RANK = 1.5  # the code plan sits below any section whose top label is critical or high, above the rest


def anchor(text):
    """The anchor of a shown id: every run outside [A-Za-z0-9._-] becomes one hyphen."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")


# ---------------------------------------------------------------- the schema subset

def load_schema(path=SCHEMA_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def type_ok(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    return False


def resolve(root, ref):
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def check_schema(value, schema, root, where, out):
    if "$ref" in schema:
        check_schema(value, resolve(root, schema["$ref"]), root, where, out)
        return
    if "const" in schema and value != schema["const"]:
        out.append(f"{where}: must be {json.dumps(schema['const'])}")
        return
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {json.dumps(value)} is not one of {', '.join(map(str, schema['enum']))}")
        return
    kind = schema.get("type")
    if kind and not any(type_ok(value, k) for k in ([kind] if isinstance(kind, str) else kind)):
        out.append(f"{where}: must be {kind if isinstance(kind, str) else ' or '.join(kind)}")
        return
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{where}: must not be empty" if schema["minLength"] == 1 else f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where}: longer than {schema['maxLength']} characters ({len(value)})")
        if "pattern" in schema and value and not re.search(schema["pattern"], value):
            out.append(f"{where}: {json.dumps(value[:60])} does not match {schema['pattern']}")
    if type_ok(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: at most {schema['maxItems']} items ({len(value)})")
        if "items" in schema:
            for i, item in enumerate(value):
                check_schema(item, schema["items"], root, f"{where}[{i}]", out)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                out.append(f"{where}: `{name}` is missing")
        props = schema.get("properties", {})
        for name, item in value.items():
            if name in props:
                check_schema(item, props[name], root, f"{where}.{name}", out)
            elif schema.get("additionalProperties") is False:
                out.append(f"{where}: unknown field `{name}`")


# ---------------------------------------------------------------- the cross-field rules

def all_rows(bundle):
    for s in bundle.get("sections") or []:
        for r in s.get("rows") or []:
            yield s, r


def anchors_of(bundle):
    """{anchor: what} for everything a `#` target may name; duplicates are reported by check_rules."""
    found = {}
    for s in bundle.get("sections") or []:
        found.setdefault(s.get("key", ""), "section")
        for r in s.get("rows") or []:
            found.setdefault(anchor(r.get("id", "")), "row")
    if bundle.get("plan"):
        found.setdefault("plan", "section")
        for st in bundle["plan"].get("steps") or []:
            found.setdefault(f"step-{st.get('n')}", "step")
    if bundle.get("answers") is not None:
        found.setdefault("answers", "section")
        for g in bundle.get("answers") or []:
            found.setdefault(g.get("key", ""), "answer group")
            for q in g.get("questions") or []:
                found.setdefault(q.get("anchor", ""), "question")
    if bundle.get("design"):
        found.setdefault("design", "section")
    return found


def every_ref(bundle):
    for s, r in all_rows(bundle):
        for i, ref in enumerate(r.get("refs") or []):
            yield f"row {r.get('id')} ref {i + 1}", ref
    for st in (bundle.get("plan") or {}).get("steps") or []:
        for i, ref in enumerate(st.get("implements") or []):
            yield f"step {st.get('n')} implements {i + 1}", ref


def check_rules(bundle):
    out = []
    page = bundle.get("page")
    header = bundle.get("header") or {}
    revision = header.get("revision") or 1

    if page == "plan":
        if not bundle.get("plan"):
            out.append("a plan page needs `plan` (the code plan's steps)")
        if "design" in bundle:
            out.append("a plan page has no `design`; that belongs to the unit-end page")
    elif page == "unit-end":
        if "design" not in bundle:
            out.append("a unit-end page needs `design` (the approved plan page, folded)")
        if "plan" in bundle:
            out.append("a unit-end page has no `plan`; the approved steps live in `design`")
    if page and bundle.get("id") and f"-{page}-v{revision}-" not in bundle["id"]:
        out.append(f"id {bundle['id']} does not name page {page} and revision v{revision}")

    numbers = [r.get("n") for r in header.get("revisions") or []]
    if numbers != list(range(1, revision + 1)):
        out.append(f"header.revisions must list revisions 1 to {revision} in order (found {numbers})")

    seen_keys, seen_ids = set(), {}
    for s in bundle.get("sections") or []:
        key, kind = s.get("key"), s.get("kind")
        if key in RESERVED_KEYS:
            out.append(f"section key `{key}` is reserved")
        if key in seen_keys:
            out.append(f"section key `{key}` is used twice")
        seen_keys.add(key)
        if page in PAGE_KINDS and kind not in PAGE_KINDS[page]:
            out.append(f"section {key}: kind `{kind}` does not belong on a {page} page")
        if s.get("asApproved"):
            if kind != "changes":
                out.append(f"section {key}: asApproved is for a changes section only")
            if s.get("rows"):
                out.append(f"section {key}: asApproved means the design stays as approved, so it holds no rows")
        if s.get("map") and kind != "built":
            out.append(f"section {key}: a map belongs on a built section only")
        for r in s.get("rows") or []:
            rid, label = r.get("id"), r.get("label")
            a = anchor(rid or "")
            if a in seen_ids:
                out.append(f"row id {rid} is used twice (also in {seen_ids[a]})")
            seen_ids[a] = key
            if kind == "built" and label not in WEIGHT:
                out.append(f"row {rid}: a built row is labelled core, main or minor, not {label}")
            if kind != "built" and label not in SEVERITY:
                out.append(f"row {rid}: label {label} belongs on built rows; use critical, high, medium or low")
            if r.get("lookFirst") and label not in ("critical", "high"):
                out.append(f"row {rid}: look first is for critical and high rows only")
            check_rev(f"row {rid}", r, revision, out)

    steps = (bundle.get("plan") or {}).get("steps") or []
    if [st.get("n") for st in steps] != list(range(1, len(steps) + 1)):
        out.append("plan steps must be numbered 1, 2, 3 … in build order")
    for st in steps:
        check_rev(f"step {st.get('n')}", st, revision, out)
        for i, sub in enumerate(st.get("subs") or []):
            if sub.get("rev") and sub["rev"] > revision:
                out.append(f"step {st.get('n')} sub-step {i + 1}: rev {sub['rev']} is after this revision ({revision})")
        if any(sub.get("rev") == revision for sub in st.get("subs") or []) and revision > 1 and st.get("rev") != revision:
            out.append(f"step {st.get('n')}: a sub-step changed in v{revision}, so the step carries rev {revision} too")

    groups = set()
    for g in bundle.get("answers") or []:
        if g.get("key") in groups:
            out.append(f"answer group `{g.get('key')}` is used twice")
        groups.add(g.get("key"))

    names = anchors_of(bundle)
    named = [("section", s.get("key")) for s in bundle.get("sections") or []]
    named += [("answer group", g.get("key")) for g in bundle.get("answers") or []]
    named += [("question", q.get("anchor")) for g in bundle.get("answers") or [] for q in g.get("questions") or []]
    taken = {a: f"row in {k}" for a, k in seen_ids.items()}
    for what, value in named:
        if value in taken:
            out.append(f"anchor `{value}` names a {what} and a {taken[value]}")
        taken[value] = what
    for where, ref in every_ref(bundle):
        target = str(ref.get("target", ""))
        if target.startswith("#") and target[1:] not in names:
            out.append(f"{where}: #{target[1:]} names nothing in this bundle")

    for s in bundle.get("sections") or []:
        m = s.get("map")
        if not m:
            continue
        ids = {n.get("id") for n in m.get("nodes") or []}
        for n in m.get("nodes") or []:
            t = n.get("target")
            if t and t[1:] not in names:
                out.append(f"section {s.get('key')} map node {n.get('id')}: {t} names nothing in this bundle")
        for e in m.get("edges") or []:
            if e.get("from") not in ids or e.get("to") not in ids:
                out.append(f"section {s.get('key')} map edge {e.get('from')} → {e.get('to')}: both ends must be nodes")
    return out


def check_rev(where, item, revision, out):
    rev = item.get("rev")
    if rev is None:
        if item.get("revNote") or item.get("revKind"):
            out.append(f"{where}: revNote and revKind go with rev")
        return
    if rev > revision:
        out.append(f"{where}: rev {rev} is after this revision ({revision})")
    if not item.get("revNote"):
        out.append(f"{where}: a row marked v{rev} says what changed in revNote")


def validate(bundle, schema=None):
    """[problem, ...]; empty when the bundle holds to the contract."""
    schema = schema or load_schema()
    out = []
    check_schema(bundle, schema, schema, "bundle", out)
    if isinstance(bundle, dict):
        try:
            out.extend(check_rules(bundle))
        except (AttributeError, TypeError) as why:  # a shape error the schema pass already reported
            if not out:
                out.append(f"bundle: cannot be checked ({why})")
    return out


# ---------------------------------------------------------------- the order a renderer shows

def section_score(rows):
    if not rows:
        return (9, 0, 0)
    top = min(RANK.get(r.get("label"), 3) for r in rows)
    return (top, -sum(1 for r in rows if r.get("lookFirst")), -sum(1 for r in rows if RANK.get(r.get("label"), 3) == top))


def sort_rows(rows):
    """Rows by label rank, then look first; stable otherwise."""
    return sorted(rows, key=lambda r: (RANK.get(r.get("label"), 3), 0 if r.get("lookFirst") else 1))


def order(bundle):
    """The keys of the sections in the order the page shows them, `plan`, `answers` and `design` included.

    Sections by importance (top label, then how many look-first rows, then how many rows at the top label). The code
    plan ranks below any section whose top label is critical or high and above the rest, so it comes first when nothing
    else is critical or high. Tests come after every other section; the person's answers are the very last section,
    except on the unit-end page, where the approved design comes last."""
    ranked, tests = [], []
    for i, s in enumerate(bundle.get("sections") or []):
        (tests if s.get("kind") == "tests" else ranked).append((section_score(s.get("rows") or []), i, s.get("key")))
    if bundle.get("plan"):
        ranked.append(((PLAN_RANK, 0, 0), -1, "plan"))
    keys = [k for _score, _i, k in sorted(ranked)] + [k for _score, _i, k in sorted(tests)]
    if bundle.get("answers"):
        keys.append("answers")
    if bundle.get("design"):
        keys.append("design")
    return keys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="validate_bundle.py", description="Check a gate bundle against its contract.")
    ap.add_argument("bundle")
    ap.add_argument("--order", action="store_true", help="also print the section order a renderer shows")
    args = ap.parse_args(argv)
    try:
        with open(args.bundle, encoding="utf-8") as f:
            bundle = json.load(f)
    except (OSError, ValueError) as why:
        print(f"validate_bundle.py: cannot read {args.bundle}: {why}", file=sys.stderr)
        return 1
    problems = validate(bundle)
    if problems:
        print("\n".join(problems))
        return 1
    print("ok" + (": " + " → ".join(order(bundle)) if args.order else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
