"""A two-round Build and Test gate for a made-up bakery, written for the batch-1 tests (one list of targets, a read mark
for every separate thing, round changes on every structured block). Everything is synthetic.

Round 1: targets u1:NFR1 (Not Met), u1:NFR2 (Unverified), u1:NFR3 (Met), u2:NFR4 (N/A), u1:NFR6 (Met in one file, Not Met in
another: the sources disagree); findings R-01, R-02 to sort; criteria; a digest item NFR1 that is also the target u1:NFR1.
Round 2: u1:NFR2's actual reworded, u1:NFR3 removed, u1:NFR5 new, u1:NFR1 unchanged; finding R-01 reworded, R-02 gone,
R-03 new; the review brief extended; one criterion's note rewritten; the evaluation's decides line unchanged.
sample(round_two) is what gate_page_env.js serves (round two with round one in `others`)."""

import copy
import json

INTENT = "260101-bakery-preorder"
STAGE = "build-and-test"

TARGETS = [
    {"id": "u1:NFR1", "unit": "U1", "verdict": "Not Met", "source": "u1 performance, Targets", "expected": "order page p95 under 2 s on a phone", "actual": "3.1 s p95", "evidence": "AP load.py"},
    {"id": "u1:NFR2", "unit": "U1", "verdict": "Unverified", "source": "u1 durability, Targets", "expected": "a reservation survives a restart", "actual": "not run", "evidence": ""},
    {"id": "u1:NFR3", "unit": "U1", "verdict": "Met", "source": "u1 security, Targets", "expected": "no secret in the bundle", "actual": "none found", "evidence": "AP scan.py"},
    {"id": "u2:NFR4", "unit": "U2", "verdict": "N/A", "source": "u2 ops, Targets", "expected": "backup nightly", "actual": "owned by operations", "evidence": ""},
    {"id": "u1:NFR6", "unit": "U1", "verdict": "Not Met", "source": "u1 perf, Targets", "expected": "list loads in 1 s", "actual": "1.4 s", "evidence": "AP list.py",
     "disagree": [{"verdict": "Not Met", "file": "test-results.md"}, {"verdict": "Met", "file": "build-and-test-summary.md"}]},
]
TARGETS_2 = copy.deepcopy(TARGETS)
TARGETS_2[1]["actual"] = "ran after a restart: reservation kept in 9 of 10 runs"
del TARGETS_2[2]
TARGETS_2.append({"id": "u1:NFR5", "unit": "U1", "verdict": "Unverified", "source": "u1 perf, Targets", "expected": "slot list under 500 ms", "actual": "not measured", "evidence": ""})


def counts(ts):
    c = {"met": 0, "notMet": 0, "unverified": 0, "na": 0}
    for t in ts:
        c[{"Met": "met", "Not Met": "notMet", "Unverified": "unverified", "N/A": "na"}[t["verdict"]]] += 1
    c["total"] = len(ts)
    return c


def findings(round_two):
    items = [
        {"id": "R-01", "severity": "Major", "blocking": True, "title": "The sold-out mark is lost on a whole-list write", "plain": "Writing the list again clears the mark.",
         "action": "Keep the mark per product.", "where": "functional design", "actionBy": "reviewer"},
        {"id": "R-02", "severity": "Minor", "blocking": False, "title": "Slot capacity is not stated", "plain": "", "action": "State the capacity.", "where": "requirements"},
    ]
    if round_two:
        items[0] = dict(items[0], title="The sold-out mark is lost when the whole list is written again", action="Keep the mark per product and test it.")
        del items[1]
        items.append({"id": "R-03", "severity": "Minor", "blocking": False, "title": "Opening hours across midnight", "plain": "", "action": "Say what happens.", "where": "requirements"})
    return {"items": items, "blocking": sum(1 for i in items if i["blocking"]), "carried": []}


def brief(round_two):
    rows = [("R-01", "Major", "functional design", "Unresolved"), ("R-02", "Minor", "requirements", "New")]
    if round_two:
        rows = [("R-01", "Major", "functional design", "Unresolved"), ("R-03", "Minor", "requirements", "New")]
    head = ("**Stage:** build-and-test\n**Review outcome:** " + ("two findings are still open" if round_two else "findings are open") +
            "\n**Why now:** the stage finished\n\n| ID | Severity | Where | Status |\n|---|---|---|---|\n")
    body = "".join(f"| {a} | {b} | {c} | {d} |\n" for a, b, c, d in rows)
    quotes = "\n".join(f"> {a} Finding: the finding text of {a}{' (round two)' if round_two else ''}\n> {a} Required action: act on {a}" for a, *_ in rows)
    return head + body + "\n" + quotes + "\n"


def summary_doc(targets):
    rows = "".join(f"| {t['verdict']} | {t['id'].split(':')[1]} | {t['expected']} | {t['actual']} |\n" for t in targets)
    return ("# Build and test summary\n\n## Results\n\nAll commands ran.\n\n### U1 Bakery\n\n"
            "| Verdict | Target ID | Expected | Actual |\n|---|---|---|---|\n" + rows + "\n## Notes\n\n- One shop.\n")


def results_doc():
    return "# Test results\n\n## Commands\n\n| Check | Command | Result |\n|---|---|---|\n| API tests | pytest | 40 passed |\n"


def items(round_two):
    out = [
        {"key": "NFR1", "id": "NFR1", "kind": "nfr", "doc": "build-and-test-summary", "title": "The order page loads in under two seconds", "summary": "The order page is quick on a phone.", "label": "high"},
        {"key": "FR1", "id": "FR1", "kind": "requirement", "doc": "build-and-test-summary", "title": "A customer reserves bread", "summary": "Reserve bread.", "label": "medium"},
        {"key": "FR2", "id": "FR2", "kind": "requirement", "doc": "build-and-test-summary", "title": "The baker reads the list", "summary": "Baker reads the list.", "label": "low"},
    ]
    if round_two:
        out[1] = dict(out[1], title="A customer reserves bread until six", summary="Reserve until six.")
        out[2] = dict(out[2], unchanged=True, lookFirst=True)  # presentation only: must not unread FR2
        out.append({"key": "FR3", "id": "FR3", "kind": "requirement", "doc": "build-and-test-summary", "title": "A customer cancels", "summary": "Cancel.", "label": "low"})
    return out


CRITERIA = [
    {"key": "stage-1", "origin": "stage", "title": "Every target has a verdict", "text": "Every target has a verdict.", "source": "path:stage.md#L3", "verdict": "holds", "note": "Each row has one."},
    {"key": "review-1", "origin": "review", "title": "Are the known limits recorded?", "text": "Are the known limits recorded?", "source": "path:reviewer.md#L9", "verdict": "fails", "note": "NFR1 is not met and not recorded."},
]


def row(round_two):
    ts = TARGETS_2 if round_two else TARGETS
    crit = copy.deepcopy(CRITERIA)
    if round_two:
        crit[1].update(note="NFR1 is not met; record it as a known limit.", source="path:reviewer.md#L19")  # a moved line is not a change
    return {"title": "Approve Build and Test", "stage": STAGE, "stageName": "Build and Test", "phase": "construction", "intent": INTENT,
            "round": 2 if round_two else 1, "why": "revision" if round_two else "first", "status": "open",
            "createdAt": "2026-01-02T10:00:00Z" if round_two else "2026-01-01T10:00:00Z", "project": "Bakery pre-order.",
            "summary": "Built and tested." + (" Round two re-ran the restart test." if round_two else ""),
            "brief": brief(round_two), "review": {"verdict": "NOT-READY", "reviewer": "qa lead", "iteration": 2 if round_two else 1},
            "findings": findings(round_two),
            "buildTest": {"counts": counts(ts), "targets": ts, "commands": [{"check": "API tests", "command": "pytest", "result": "40 passed", "ok": True}]},
            "documents": [{"key": "build-and-test-summary", "title": "Build and test summary", "kind": "markdown", "covered": True, "path": "aidlc/x/build-and-test-summary.md"},
                          {"key": "test-results", "title": "Test results", "kind": "markdown", "covered": True, "path": "aidlc/x/test-results.md"}],
            "evaluation": {"verdict": "risks", "decides": "Approving accepts the known limits.",
                           "lookFirst": [{"text": "NFR1 misses its target.", "why": "It is not met.", "sources": ["NFR1"]}],
                           "solid": [{"text": "Every target has a verdict.", "sources": ["stage-1"]}], "risks": [], "gaps": [], "conflicts": []},
            "criteria": crit, "digest": {"items": items(round_two), "trace": [], "settled": 0},
            "options": [{"k": "approve", "t": "Approve"}, {"k": "changes", "t": "Request Changes"}]}


def documents(round_two):
    ts = TARGETS_2 if round_two else TARGETS
    return {"build-and-test-summary": {"key": "build-and-test-summary", "title": "Build and test summary", "kind": "markdown", "n": 1, "path": "aidlc/x/build-and-test-summary.md", "text": summary_doc(ts)},
            "test-results": {"key": "test-results", "title": "Test results", "kind": "markdown", "n": 2, "path": "aidlc/x/test-results.md", "text": results_doc()}}


def sample(round_two=True):
    first = {"id": f"{INTENT}-{STAGE}-20260101T1000", "row": row(False), "documents": documents(False)}
    if not round_two:
        return dict(first, others=[])
    return {"id": f"{INTENT}-{STAGE}-20260102T1000", "row": row(True), "documents": documents(True), "others": [first]}


if __name__ == "__main__":
    import sys
    print(json.dumps(sample(len(sys.argv) < 2)))
