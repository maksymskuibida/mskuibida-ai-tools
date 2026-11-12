"""Synthetic records for dev/preview.py: a made-up neighbourhood bakery's pre-order app, written the way the AI-DLC stages
write their files, long enough to look like a real gate (dozens of items, long documents, 40+ targets). Nothing here is a
real project; every name, number and sentence is invented. Standard library only.

    documents(stage, produces, rnd)      {key: text} for every file a stage produces, in round 1, 2 or 3
    build_and_test(rnd)                  the Build and Test files: 48 targets over four Units, one target in two files that disagree

A round after the first edits the same files the way a revision would: a section reworded, a section added, a section removed,
a row or an item added or taken away."""

import json
import zlib

LOAVES = ["sourdough", "rye", "seeded spelt", "focaccia", "baguette", "cinnamon bun", "olive loaf", "milk bread", "pretzel", "cardamom knot"]
ACTORS = ["Customer", "Baker", "Counter", "Server", "Store", "Notifier"]
TOPICS = ["pick-up slots", "stock", "reservations", "the baker's list", "payments", "reminders", "allergens", "opening hours", "the order page",
          "sold-out marks", "loyalty stamps", "delivery windows", "refunds", "the day's bake plan"]
LAYERS = ["presentation", "application", "domain", "data", "infrastructure"]
UNITS = [("u1-core", "Core ordering"), ("u2-pickup-slots", "Pick-up slots"), ("u3-bakers-list", "The baker's list"), ("u4-reminders", "Reminders")]


def rnd_of(*parts):
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def pick(seq, *parts):
    return seq[rnd_of(*parts) % len(seq)]


def sentence(seed, n=1):
    out = []
    for i in range(n):
        s = rnd_of(seed, i)
        loaf, topic, actor = LOAVES[s % len(LOAVES)], TOPICS[(s >> 3) % len(TOPICS)], ACTORS[(s >> 6) % len(ACTORS)].lower()
        form = (s >> 9) % 6
        out.append([
            f"The {actor} sees {topic} for {loaf} as one short list, newest first.",
            f"A {loaf} order is held for {10 + (s >> 4) % 20} minutes while the {actor} confirms {topic}.",
            f"When {topic} change, the {actor} is told once and the list is drawn again without a reload.",
            f"{topic.capitalize()} never block an order that is already confirmed; they only stop new ones.",
            f"If the shop closes early, {topic} for {loaf} move to the next morning and the {actor} is told why.",
            f"Each {loaf} has its own limit of {4 + (s >> 5) % 12} a day, and {topic} read that limit, not a total.",
        ][form])
    return " ".join(out)


def para(seed, n=3):
    return sentence(seed, n)


def table(head, rows):
    return "| " + " | ".join(head) + " |\n|" + "|".join("---" for _ in head) + "|\n" + "".join("| " + " | ".join(str(c) for c in r) + " |\n" for r in rows)


def stage_title(slug):
    return " ".join(w.capitalize() for w in slug.split("-"))


# ---------------------------------------------------------------- one file in three rounds

def mutate(sections, rnd, seed):
    """Round 2: one section reworded, one added, the last removed. Round 3: one more of each on top."""
    out = [list(s) for s in sections]
    if rnd >= 2 and len(out) > 3:
        out[1][1] = out[1][1] + "\n\nChanged in round 2: " + para((seed, "r2"), 2)
        out.insert(2, ["Saturday pickups", para((seed, "sat"), 3) + "\n\n- A Saturday slot opens at 07:00.\n- The baker can close a Saturday slot by hand.\n"])
        out.pop()
    if rnd >= 3 and len(out) > 5:
        out[3][1] = para((seed, "r3"), 3)
        out.insert(4, ["Opening hours across midnight", para((seed, "mid"), 2) + "\n\n1. A late order made after 23:00 counts for the day after next.\n2. The list says so beside the order.\n"])
        out.pop(-2)
    return out


def render(title, intro, sections):
    return f"# {title}\n\n{intro}\n\n" + "".join(f"## {t}\n\n{b.rstrip()}\n\n" for t, b in sections)


def mermaid_flow(seed):
    return ("```mermaid\nflowchart LR\n  A[Customer opens the order page] --> B{Slot free?}\n  B -->|yes| C[Reserve the loaf]\n  B -->|no| D[Show the next free slot]\n"
            "  C --> E[(Order list)]\n  D --> B\n  E -.->|each morning| F[Baker's list]\n```\n")


def generic(slug, key, rnd, with_flow):
    seed = (slug, key)
    secs = []
    for i in range(9):
        topic = pick(TOPICS, seed, i)
        body = para((seed, i), 3)
        if i == 1:
            body += "\n\n" + table(["Item", "Limit", "Owner", "Note"], [[pick(LOAVES, seed, i, j), 4 + rnd_of(seed, i, j) % 20, pick(ACTORS, seed, j), sentence((seed, i, j))[:60]] for j in range(7)])
        if i == 2:
            body += "\n\n" + "\n".join(f"{n + 1}. {sentence((seed, i, n))}" for n in range(6))
        if i == 3 and with_flow:
            body += "\n\n" + mermaid_flow(seed)
        if i == 4:
            body += "\n\n" + "\n".join(f"- {sentence((seed, 'b', n))}" for n in range(8))
        if i == 5:
            body += "\n\n```text\n" + "\n".join(f"{pick(LOAVES, seed, n):<14} {4 + rnd_of(seed, n) % 20:>3}  {pick(ACTORS, seed, n, 'x')}  {sentence((seed, 'c', n))}" for n in range(6)) + "\n```\n"
        secs.append([f"{topic.capitalize()}" + ("" if i < 7 else f" ({i})"), body])
    secs = mutate(secs, rnd, seed)
    return render(f"{stage_title(slug)}: {stage_title(key)}", para((seed, "intro"), 2), secs)


# ---------------------------------------------------------------- the stages' own files

def questions(slug, rnd):
    qs = []
    for n in range(1, 7):
        s = (slug, "q", n)
        opts = [f"{c}) {sentence((s, c))[:90]}" for c in "ABCD"]
        qs.append(f"## Question {n}\n\nQ{n}: {sentence(s)}\n\n" + "\n".join(opts) + f"\nX) Other (describe after the [Answer]: tag)\n\n[Answer]: {pick('ABCD', s)}\n")
    return f"# {stage_title(slug)}: questions\n\n" + "\n".join(qs)


def requirements(rnd):
    frs = [(f"FR{i}", sentence(("fr", i))) for i in range(1, 15 + (3 if rnd >= 2 else 0))]
    nfrs = [(f"NFR{i}", sentence(("nfr", i))) for i in range(1, 9)]
    if rnd >= 3:
        frs = frs[:-2]
    return ("# Requirements\n\nThe bakery's customers reserve loaves for the next morning; the baker sees one pick-up list.\n\n## Functional requirements\n\n" +
            table(["ID", "Requirement", "Priority"], [[a, b, pick(["Must", "Should", "Could"], a)] for a, b in frs]) +
            "\n## Non-functional requirements\n\n" + "".join(f"- **{a}** {b}\n" for a, b in nfrs) + "\n## Out of scope\n\n- Delivery.\n- Gift cards.\n")


def stories(rnd):
    parts = ["# User stories\n"]
    n = 12 + (2 if rnd >= 2 else 0) - (1 if rnd >= 3 else 0)
    for i in range(1, n + 1):
        parts.append(f"### US{i}.1 {pick(TOPICS, 's', i).capitalize()}\n\nAs a {pick(['customer', 'baker', 'counter clerk'], i)}, I want {sentence(('us', i))[:110].lower()}\n\n" +
                     "".join(f"- AC{i}.1.{k} Given {pick(TOPICS, i, k)}, when {pick(ACTORS, i, k).lower()} acts, then {sentence((i, k, 'ac'))[:80].lower()}\n" for k in range(1, 4)))
    return "\n".join(parts)


def traceability(rnd, kind="stories"):
    rows = [{"id": f"FR{i}", "status": "OK", "target": f"US{i}.1"} for i in range(1, 13)]
    rows += [{"id": f"NFR{i}", "status": "OK", "target": f"US{i}.1; US{i + 1}.1"} for i in range(1, 5)]
    if rnd >= 2:
        rows.append({"id": "FR13", "status": "OK", "target": "US13.1"})
    if rnd >= 3:
        rows.pop(2)
    return json.dumps({"stage": kind, "coverage": rows}, indent=2)


def components(rnd):
    names = {"presentation": ["Order page", "Baker's page"], "application": ["Order service", "List service", "Reminder service"],
             "domain": ["Reservation rules", "Slot calendar", "Stock rules"], "data": ["Order store", "Stock store"], "infrastructure": ["Message queue", "Mail gateway"]}
    if rnd >= 2:
        names["application"].append("Allergen service")
    if rnd >= 3:
        names["data"].pop()
    rows, flat = [], [n for ns in names.values() for n in ns]
    for layer, ns in names.items():
        rows.append(f"  # ---- {layer.capitalize()} ----")
        for n in ns:
            deps = [d for d in flat if d != n and rnd_of(n, d) % 7 == 0][:2]
            rows.append(f"  - name: {n}\n    group: {layer}\n    summary: {sentence(('comp', n))[:100]}\n    responsibilities:\n      - {sentence(('r', n))[:90]}\n" +
                        ("    depends_on:\n" + "".join(f"      - component: {d}\n        interaction: calls it to read the day\n" for d in deps) if deps else ""))
    return "# Components\n\nThe pieces of the pre-order app and what each one depends on.\n\n```yaml\ncomponents:\n" + "\n".join(rows) + "\n```\n"


def unit_of_work(rnd):
    """unit-of-work.md: one `### U<n> Name` heading per Unit, what it owns under it. Units Generation's items are these."""
    units = [("U1", "Core ordering"), ("U2", "Pick-up slots"), ("U3", "The baker's list"), ("U4", "Reminders"), ("U5", "Stock"), ("U6", "Payments"), ("U7", "Allergens"), ("U8", "Loyalty stamps")]
    if rnd >= 2:
        units.append(("U9", "Saturday bake"))
    if rnd >= 3:
        units.pop(7)
    out = ["# Units of work", "", "How the pre-order app is cut into Units a team can build and ship one at a time.", "", "## Units", ""]
    for uid, name in units:
        out += [f"### {uid} {name}", "", sentence(("unit", uid)) + " " + sentence(("unit2", uid, rnd if uid == "U9" else 0)), "",
                f"- Owns: {pick(TOPICS, 'own', uid)}, {pick(TOPICS, 'own2', uid)}", f"- Depends on: {'none' if uid == 'U1' else 'U1'}", ""]
    return "\n".join(out)


def units_deps(rnd):
    u = [("U1", "Core ordering", []), ("U2", "Pick-up slots", ["U1"]), ("U3", "The baker's list", ["U1", "U2"]), ("U4", "Reminders", ["U2"]), ("U5", "Stock", ["U1"]),
         ("U6", "Payments", ["U1"]), ("U7", "Allergens", ["U5"]), ("U8", "Loyalty stamps", ["U6"])]
    if rnd >= 2:
        u.append(("U9", "Saturday bake", ["U3", "U5"]))
    return ("# Unit dependencies\n\n```yaml\nunits:\n" + "".join(f"  - name: {a}\n    kind: {b}\n    depends_on: [{', '.join(c)}]\n" for a, b, c in u) + "```\n")


def functional_spec(rnd):
    secs = [
        ["Slot rules", table(["ID", "Rule", "Source"], [[f"SR{i}", sentence(("sr", i)), f"FR{i}"] for i in range(1, 9)])],
        ["Workflows", "### WF1 Picking a slot\n\n" + "\n".join(f"{n}. {s}" for n, s in enumerate([
            "Customer -> Server: asks for the free slots of tomorrow", "Server -> Store: reads the day's orders", "Store -> Server: returns the count per slot",
            "Server -> Customer: shows the free slots", "Customer -> Server: picks a slot and a loaf", "Server -> Notifier: sends the confirmation"], 1))],
        ["Order states", table(["From", "To", "Event"], [["Draft", "Held", "customer picks a slot"], ["Held", "Confirmed", "customer pays"], ["Held", "Expired", "10 minutes pass"],
                                                       ["Confirmed", "Baked", "baker marks it"], ["Confirmed", "Cancelled", "customer cancels before 21:00"], ["Baked", "Collected", "customer collects"]])],
        ["How a slot is chosen", mermaid_flow("fs")],
        ["Assumptions & Open Questions", "".join(f"- [assumption] {sentence(('as', i))}\n" for i in range(5))],
    ]
    secs = mutate(secs, rnd, "fs")
    return render("Functional specification", para("fs-intro", 2), secs)


def entities(rnd):
    names = ["Customer", "Order", "OrderLine", "Loaf", "Slot", "StockDay"]
    rows = []
    for n in names:
        rel = {"Order": [("Customer", "many to one"), ("OrderLine", "one to many")], "OrderLine": [("Loaf", "many to one")], "Slot": [("Order", "one to many")], "StockDay": [("Loaf", "many to one")]}.get(n, [])
        rows.append(f"  - name: {n}\n    owner: ordering\n    summary: {sentence(('ent', n))[:90]}\n    attributes:\n      - name: id\n      - name: createdAt\n" +
                    ("    relationships:\n" + "".join(f"      - to: {t}\n        cardinality: {c}\n" for t, c in rel) if rel else ""))
    return "# Entities\n\n```yaml\nentities:\n" + "\n".join(rows) + "```\n"


def rules(rnd):
    rows = [f"  - id: BR{i // 4 + 1}.{i % 4 + 1}\n    statement: {sentence(('br', i))}\n    severity: {pick(['must', 'should'], i)}" for i in range(14 + (2 if rnd >= 2 else 0))]
    return "# Business rules\n\n```yaml\nrules:\n" + "\n".join(rows) + "\n```\n"


def code_plan(rnd, unit=False):
    steps = [f"{i}. {pick(['Reservation model', 'Order endpoint', 'Slot calendar', 'Stock check', 'Baker list query', 'Reminder job', 'Order page', 'List page'], i)}: "
             f"{sentence(('cp', i))[:80]} (implements FR{i}, US{i}.1)" for i in range(1, 15 + (2 if rnd >= 2 else 0))]
    if rnd >= 3:
        steps.pop(3)
    return "# Code generation plan\n\n" + "\n".join(steps) + "\n"


def decisions(rnd):
    n = 7 + (1 if rnd >= 2 else 0)
    return "# Decisions\n\n" + "".join(f"## ADR-{i:03d} {pick(TOPICS, 'adr', i).capitalize()}\n\n**Status:** accepted\n\n**Context.** {para(('adr', i), 2)}\n\n**Decision.** {sentence(('d', i))}\n\n" for i in range(1, n + 1))


def build_and_test(rnd):
    """(summary, results): 48 targets over four Units in the summary; u2:NFR7 is listed in the results file too, with another verdict."""
    out = ["# Build and Test Summary: bakery pre-order, first version\n\n## Target Verification Matrix\n\nEvidence codes: **A** the API tests, **AP** the speed tests, **W** the web tests, **H** by hand.\n"]
    verdicts = ["Met"] * 6 + ["Unverified", "Not Met", "N/A"]
    n = 0
    for ui, (slug, name) in enumerate(UNITS, 1):
        rows = []
        for k in range(1, 13):
            n += 1
            v = verdicts[rnd_of(ui, k, rnd if k % 5 == 0 else 1) % len(verdicts)]
            if rnd >= 2 and ui == 1 and k == 3:
                v = "Met"
            rows.append(f"| u{ui}:NFR{k} | u{ui} {pick(['performance', 'security', 'durability', 'usability'], ui, k)}-requirements, Targets | {sentence((ui, k, 'e'))[:70]} | "
                        f"{'passes' if v == 'Met' else ('no test' if v == 'Unverified' else sentence((ui, k, 'a'))[:40])} | {pick(['A', 'AP', 'W', 'H'], ui, k)} | build-and-test | {v} |")
        out.append(f"\n### U{ui} {name}\n\n| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |\n|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    summary = "".join(out)
    results = ("# Test results\n\n## Checks and tests\n\n| Check | Command | Result |\n|---|---|---|\n" +
               "".join(f"| {c} | `{cmd}` | {res} |\n" for c, cmd, res in [("API lint", "ruff check .", "all checks passed"), ("API tests", "pytest --cov", "412 passed, 0 failed"),
                                                                             ("Web tests", "vitest run", "208 passed, 2 failed"), ("Web size", "pnpm size", "203 KB gzip of 300 KB")]) +
               "\n## Targets seen again\n\n### U2 Pick-up slots\n\n| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |\n|---|---|---|---|---|---|---|\n"
               "| u2:NFR7 | u2 performance-requirements, Targets | list loads in 1 s | 1.4 s | AP | build-and-test | Not Met |\n")
    return summary, results


def build_instructions():
    return "# Build Instructions\n\n## Commands\n\n| Step | Command | Result |\n|---|---|---|\n| Build | `pnpm build` | dist |\n| Install | `uv sync` | environment ready |\n"


# ---------------------------------------------------------------- what a stage writes

def documents(slug, produces, rnd, unit=False):
    """{key: text}: the files a stage produces, each as its kind of file, in the round asked for."""
    keys = [k for k in produces if not k.endswith("-timestamp")] or [slug + "-summary"]
    out = {}
    for key in keys:
        if key.endswith("-questions"):
            out[key] = questions(slug, rnd)
        elif key == "traceability" or key == "cross-unit-traceability":
            out[key] = traceability(rnd, slug)
        elif key == "requirements":
            out[key] = requirements(rnd)
        elif key == "stories":
            out[key] = stories(rnd)
        elif key == "components":
            out[key] = components(rnd)
        elif key == "unit-of-work":
            out[key] = unit_of_work(rnd)
        elif key == "unit-of-work-dependency":
            out[key] = units_deps(rnd)
        elif key == "functional-spec":
            out[key] = functional_spec(rnd)
        elif key == "entities":
            out[key] = entities(rnd)
        elif key == "rules":
            out[key] = rules(rnd)
        elif key == "code-generation-plan":
            out[key] = code_plan(rnd)
        elif key == "decisions":
            out[key] = decisions(rnd)
        else:
            out[key] = generic(slug, key, rnd, with_flow=(rnd_of(slug, key) % 3 == 0))
    return out


def cut(text, n):
    """The text whole. The contract rejects a clipped text (one ending in an ellipsis), so the preview never hands a page a sentence cut mid-word;
    n is the length the earlier version clipped to, kept so a call reads the same."""
    return str(text)
