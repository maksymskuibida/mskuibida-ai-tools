"""A two-round requirements-analysis gate, written from scratch for the revision tests: the shape of a real gate row
(evaluation, criteria, digest items, a covered requirements document with ## sections and tables, a review copy) for a
made-up bakery, round 1 and its revision round 2.

Round 2 against round 1: FR1.2 and FR2.2 reworded, FR2.3 removed, a new "Opening hours" section with FR3.1 and FR3.2,
"Assumptions" reworded, the evaluation's count of requirements eight -> nine and a criterion's note rewritten, the
summary extended, and review-02 in place of review-01. sample() is what gate_page_env.js serves."""

import copy

INTENT = "260101-bakery-preorder"
STAGE = "requirements-analysis"
PATH = f"aidlc/spaces/default/intents/{INTENT}/inception/{STAGE}/"

FR = {
    "FR1.1": ("A customer reserves a loaf for the next morning before 18:00.", "Must"),
    "FR1.2": ("A customer picks a pickup slot of 15 minutes.", "Must"),
    "FR1.3": ("A customer cancels a reservation until 20:00 the evening before.", "Should"),
    "FR2.1": ("The baker sees tomorrow's reservations as one list sorted by slot.", "Must"),
    "FR2.2": ("The baker marks a product sold out.", "Must"),
    "FR2.3": ("The baker prints the list for the morning shift.", "Could"),
}
FR_2 = dict(FR)
FR_2["FR1.2"] = ("A customer picks a pickup slot of 15 minutes, and a slot takes at most 12 orders.", "Must")
FR_2["FR2.2"] = ("The baker marks a product sold out by its short name, and writing the whole list again never clears that mark.", "Must")
del FR_2["FR2.3"]
HOURS = {
    "FR3.1": ("Opening hours are in the shop's time zone; a slot starts on the minute the shop opens and ends a minute before it closes.", "Must"),
    "FR3.2": ("Two opening windows that overlap count as one.", "Should"),
}
NFR = {
    "NFR1": "The order page loads in under two seconds on a phone over a mobile network.",
    "NFR2": "A reservation survives a restart of the server.",
}


def table(rows):
    return "| ID | Requirement | Priority |\n|---|---|---|\n" + "".join(f"| {k} | {t} | {p} |\n" for k, (t, p) in rows.items())


def requirements(round_two):
    fr = FR_2 if round_two else FR
    parts = ["# Requirements: Bakery pre-order\n",
             "## Intent analysis\n\nA small bakery takes pre-orders for bread so that the morning bake matches what people"
             " will collect. Customers order on a phone; the baker reads one list at five in the morning.\n",
             "## Functional requirements\n\n" + table(fr)]
    if round_two:
        parts.append("## Opening hours\n\n" + table(HOURS))
    parts.append("## Non-functional requirements\n\n| ID | Requirement |\n|---|---|\n" + "".join(f"| {k} | {t} |\n" for k, t in NFR.items()))
    parts.append("## Assumptions\n\n- One shop and one oven.\n- " + (
        "Every customer has a phone number; the shop's time zone is the only one that counts." if round_two
        else "Every customer has a phone number.") + "\n")
    parts.append("## Constraints\n\n- No payment online in this intent.\n- The baker's list must print on A4.\n")
    parts.append("## Out of scope\n\n- Delivery.\n- Cakes made to order.\n")
    return "\n".join(parts)


def review(n, verdict, rows):
    body = "".join(f"| R-0{i} | {sev} | {text} | {status} |\n" for i, (sev, text, status) in enumerate(rows, 1))
    return (f"## Review\n\n**Verdict:** {verdict}\n**Reviewer:** product lead\n**Iteration:** {n}\n\n"
            "## Findings\n\n| ID | Severity | Finding | Status |\n|---|---|---|---|\n" + body)


REVIEW_1 = review(1, "NOT-READY", [("Major", "The sold-out mark is not defined against a whole-list write.", "New"),
                                   ("Minor", "Slot capacity is not stated.", "New")])
REVIEW_2 = review(2, "READY", [("Major", "The sold-out mark is not defined against a whole-list write.", "Resolved"),
                               ("Minor", "Slot capacity is not stated.", "Resolved"),
                               ("Minor", "Opening hours across midnight are not covered.", "Accepted")])

SUMMARY = {
    "FR1.1": ("A customer reserves bread for tomorrow until six in the evening.", "high"),
    "FR1.2": ("A customer picks a quarter-hour pickup slot.", "high"),
    "FR1.3": ("A reservation can be cancelled until eight the evening before.", "medium"),
    "FR2.1": ("The baker reads tomorrow's orders as one list by slot.", "high"),
    "FR2.2": ("The baker can mark a product sold out.", "medium"),
    "FR2.3": ("The baker can print the list.", "low"),
    "FR3.1": ("Slots follow the shop's local opening hours, to the minute.", "medium"),
    "FR3.2": ("Overlapping opening windows merge.", "low"),
    "NFR1": ("The order page is quick on a phone.", "medium"),
    "NFR2": ("Reservations are kept across restarts.", "high"),
}
SUMMARY_2 = dict(SUMMARY, **{"FR1.2": ("A customer picks a quarter-hour slot, twelve orders at most.", "high"),
                            "FR2.2": ("Sold out is set per product and no list write clears it.", "high")})


def items(round_two):
    fr = dict(FR_2, **HOURS) if round_two else FR
    said = SUMMARY_2 if round_two else SUMMARY
    out = [{"key": k, "id": k, "kind": "requirement", "doc": "requirements", "title": t, "summary": said[k][0], "label": said[k][1]}
           for k, (t, _p) in fr.items()]
    out += [{"key": k, "id": k, "kind": "nfr", "doc": "requirements", "title": t, "summary": said[k][0], "label": said[k][1],
             **({"unchanged": True} if round_two else {})} for k, t in NFR.items()]
    if round_two:
        for i in out:
            if i["id"] in ("FR1.1", "FR1.3", "FR2.1"):
                i["unchanged"] = True
    return out


CRITERIA = [
    {"key": "stage-1", "origin": "stage", "title": "Every requirement is testable", "text": "Every requirement is testable.",
     "source": "path:stage.md#L3", "verdict": "holds", "note": "Each row says what a test would check."},
    {"key": "review-1", "origin": "review", "title": "Is anything implied but never stated?", "text": "Is anything implied but never stated?",
     "source": "path:reviewer.md#L9", "verdict": "fails", "note": "Slot capacity and the sold-out mark are implied and never stated."},
    {"key": "rule-1", "origin": "rule", "title": "NEVER hard-code user-facing copy", "text": "NEVER hard-code user-facing copy.",
     "source": "path:memory/project.md#L2", "verdict": "n/a"},
]


def criteria(round_two):
    c = copy.deepcopy(CRITERIA)
    if round_two:
        c[1].update(verdict="holds", note="Slot capacity and the sold-out mark are now stated in FR1.2 and FR2.2.")
    return c


def evaluation(round_two):
    n = "nine" if round_two else "eight"
    e = {"verdict": "ready" if round_two else "risks",
         "decides": f"Approving fixes the {n} requirements a customer and the baker rely on, and what is left for later.",
         "lookFirst": [{"text": "FR2.2: what writing the whole product list does to a sold-out mark.",
                        "why": "It was the one major finding" + (", and the answer is new in this round." if round_two else "."),
                        "sources": ["FR2.2", "review-1" if not round_two else "FR2.2"]}],
         "solid": [{"text": "Every requirement names who does what and when.", "sources": ["stage-1"]}],
         "risks": [{"text": "Opening hours across midnight are left open." if round_two else "Slot capacity is not stated, so a slot can overfill.",
                    "severity": "medium", "sources": ["FR3.1" if round_two else "FR1.2"]}],
         "gaps": [] if round_two else [{"text": "Slot capacity is implied and never stated.", "sources": ["review-1"]}],
         "conflicts": []}
    return e


def row(round_two):
    when = "2026-01-02T10:00:00Z" if round_two else "2026-01-01T10:00:00Z"
    r = {"title": "Approve Requirements Analysis", "stage": STAGE, "stageName": "Requirements Analysis", "phase": "inception",
         "intent": INTENT, "round": 2 if round_two else 1, "why": "revision" if round_two else "first", "status": "open",
         "createdAt": when, "project": "Bakery pre-order: bread reserved the evening before, collected in the morning.",
         "summary": "Wrote the requirements from your answers." + (" In this round: slot capacity in FR1.2, the sold-out"
                                                                     " mark in FR2.2, a new Opening hours section, and the"
                                                                     " print list dropped." if round_two else ""),
         "documents": [{"key": "requirements", "title": "Requirements", "kind": "markdown", "covered": True, "path": PATH + "requirements.md"},
                       {"key": "review-02" if round_two else "review-01", "title": "Review 02" if round_two else "Review 01",
                        "kind": "review", "covered": False, "path": PATH + "reviews/review-0" + ("2" if round_two else "1") + ".md"}],
         "evaluation": evaluation(round_two), "criteria": criteria(round_two),
         "digest": {"items": items(round_two), "trace": [], "settled": 0},
         "options": [{"k": "approve", "t": "Approve"}, {"k": "changes", "t": "Request Changes"}]}
    return r


def documents(round_two):
    rk = "review-02" if round_two else "review-01"
    return {"requirements": {"key": "requirements", "title": "Requirements", "kind": "markdown", "n": 1, "path": PATH + "requirements.md",
                             "text": requirements(round_two)},
            rk: {"key": rk, "title": "Review 02" if round_two else "Review 01", "kind": "review", "n": 2,
                 "path": PATH + "reviews/" + rk + ".md", "text": REVIEW_2 if round_two else REVIEW_1}}


def sample():
    return {"id": f"{INTENT}-{STAGE}-20260102T1000", "row": row(True), "documents": documents(True),
            "others": [{"id": f"{INTENT}-{STAGE}-20260101T1000", "row": row(False), "documents": documents(False)}]}
