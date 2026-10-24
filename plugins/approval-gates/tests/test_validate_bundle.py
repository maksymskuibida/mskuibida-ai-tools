"""Tests for scripts/validate_bundle.py: the schema subset, the contract's rules, and the order a page shows.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from bundle_helpers import NODE, SCRIPTS, render

sys.path.insert(0, SCRIPTS)
import validate_bundle  # noqa: E402

ID = "260101-bakery-preorder-u2-pickup-slots-plan-v1-20260101T0900"


def row(rid, label="medium", **extra):
    return dict({"id": rid, "title": f"Row {rid}", "label": label, "body": "Plain words.", "refs": []}, **extra)


def plan_bundle():
    return {
        "schema": "aidlc-gate-bundle/1", "page": "plan", "id": ID, "createdAt": "2026-01-01T09:00:00Z",
        "header": {"project": "Bakery", "intent": "260101-bakery-preorder", "unit": "u2-pickup-slots", "unitName": "Pick-up slots",
                   "title": "U2 · Pick-up slots", "lede": "Customers pick a slot.", "status": "Plan approval · answer in chat",
                   "revision": 1, "revisions": [{"n": 1, "note": "first draft"}], "facts": [{"label": "Look first", "value": "1 row"}]},
        "sections": [
            {"key": "assumptions", "kind": "assumptions", "title": "Assumptions", "short": "Assumptions",
             "rows": [row("A-1", "high", lookFirst=True, refs=[{"label": "FD-Q1", "tip": "Your answer A", "target": "#fd-q1"}]), row("A-2", "low")]},
            {"key": "findings", "kind": "findings", "title": "Findings", "short": "Findings",
             "rows": [row("FD R-02", "medium", coveredBy={"text": "Step 1 settles it", "settled": True},
                          refs=[{"label": "Step 1", "tip": "The slot rules", "target": "#step-1"}])]},
            {"key": "tests", "kind": "tests", "title": "Tests", "short": "Tests", "rows": [row("T-1", "critical")]},
        ],
        "plan": {"steps": [{"n": 1, "title": "Slot rules", "layer": "logic", "files": 2, "subs": [{"text": "Rules."}],
                            "implements": [{"label": "SR1", "tip": "Slots of 15 minutes", "target": "path:aidlc/x.md#SR1"}]}]},
        "answers": [{"key": "fd-answers", "stage": "functional-design", "title": "Functional Design", "file": "x.md",
                     "questions": [{"id": "Q1", "anchor": "fd-q1", "text": "Moving an order", "answer": "A", "proposed": "B"}]}],
    }


def end_bundle():
    b = plan_bundle()
    b.update(page="unit-end", id=ID.replace("-plan-", "-unit-end-"))
    del b["plan"]
    b["answers"] = []
    b["sections"] = [
        {"key": "changes", "kind": "changes", "title": "Changed", "short": "Changed", "asApproved": True, "rows": []},
        {"key": "unverified", "kind": "unverified", "title": "Not verified", "short": "Not verified", "rows": [row("V-1", "high", lookFirst=True)]},
        {"key": "built", "kind": "built", "title": "Built", "short": "Built", "rows": [row("B-1", "core"), row("B-2", "minor")],
         "map": {"nodes": [{"id": "a", "title": "Rules", "weight": "core", "target": "#B-1"}, {"id": "b", "title": "List", "weight": "main"}],
                 "edges": [{"from": "a", "to": "b"}]}},
    ]
    b["design"] = {"bundle": ID, "rows": [{"id": "A-1", "title": "Row A-1", "label": "high"}]}
    return b


class TestValid(unittest.TestCase):
    def test_a_plan_bundle_holds(self):
        self.assertEqual(validate_bundle.validate(plan_bundle()), [])

    def test_a_unit_end_bundle_holds(self):
        self.assertEqual(validate_bundle.validate(end_bundle()), [])

    def test_the_command_line(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(plan_bundle(), f)
        self.addCleanup(os.remove, f.name)
        done = subprocess.run([sys.executable, os.path.join(SCRIPTS, "validate_bundle.py"), f.name, "--order"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(done.stdout.strip(), "ok: assumptions → plan → findings → tests → answers")
        b = plan_bundle()
        b["sections"][0]["rows"][0]["label"] = "urgent"
        with open(f.name, "w", encoding="utf-8") as out:
            json.dump(b, out)
        done = subprocess.run([sys.executable, os.path.join(SCRIPTS, "validate_bundle.py"), f.name], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("urgent", done.stdout)


class TestSchema(unittest.TestCase):
    def problems(self, change, base=plan_bundle):
        b = base()
        change(b)
        return validate_bundle.validate(b)

    def assertProblem(self, change, text, base=plan_bundle):
        found = self.problems(change, base)
        self.assertTrue(any(text in p for p in found), f"no problem mentions {text!r}: {found}")

    def test_unknown_fields_are_refused(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(colour="red"), "unknown field `colour`")
        self.assertProblem(lambda b: b.update(extra=1), "unknown field `extra`")

    def test_required_fields(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].pop("label"), "`label` is missing")
        self.assertProblem(lambda b: b["header"].pop("lede"), "`lede` is missing")

    def test_a_label_outside_the_set(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(label="urgent"), "is not one of")
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(label=None), "is not one of")

    def test_a_title_is_one_line_with_no_ellipsis(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(title="Two\nlines"), "does not match")
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(title="Cut off…"), "does not match")
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(title="x" * 161), "longer than 160")

    def test_a_reference_needs_a_tip_and_a_target_of_a_known_form(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0]["refs"][0].pop("tip"), "`tip` is missing")
        self.assertProblem(lambda b: b["sections"][0]["rows"][0]["refs"][0].update(target="NR1"), "does not match")

    def test_the_schema_value(self):
        self.assertProblem(lambda b: b.update(schema="aidlc-gate-bundle/2"), "must be")


class TestRules(TestSchema):
    def test_plan_page_needs_a_plan_and_no_design(self):
        self.assertProblem(lambda b: b.pop("plan"), "needs `plan`")
        self.assertProblem(lambda b: b.update(design={"bundle": "x", "rows": []}), "no `design`")

    def test_unit_end_page_needs_the_design_and_no_plan(self):
        self.assertProblem(lambda b: b.pop("design"), "needs `design`", end_bundle)
        self.assertProblem(lambda b: b.update(plan=plan_bundle()["plan"]), "no `plan`", end_bundle)

    def test_section_kinds_belong_to_their_page(self):
        self.assertProblem(lambda b: b["sections"][0].update(kind="built"), "does not belong on a plan page")
        self.assertProblem(lambda b: b["sections"][1].update(kind="assumptions"), "does not belong on a unit-end page", end_bundle)

    def test_section_keys_are_unique_and_not_reserved(self):
        self.assertProblem(lambda b: b["sections"][1].update(key="assumptions"), "used twice")
        self.assertProblem(lambda b: b["sections"][1].update(key="answers"), "reserved")

    def test_built_rows_use_weights_and_others_severity(self):
        self.assertProblem(lambda b: b["sections"][2]["rows"][0].update(label="high"), "core, main or minor", end_bundle)
        self.assertProblem(lambda b: b["sections"][0]["rows"][1].update(label="core"), "belongs on built rows")

    def test_look_first_only_on_critical_and_high(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][1].update(lookFirst=True), "critical and high rows only")

    def test_ids_are_unique(self):
        self.assertProblem(lambda b: b["sections"][1]["rows"].append(row("A-1")), "used twice")
        self.assertProblem(lambda b: b["sections"][1]["rows"].append(row("A 1")), "used twice")  # the same anchor

    def test_internal_targets_resolve(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0]["refs"][0].update(target="#nowhere"), "names nothing")
        self.assertProblem(lambda b: b["sections"][1]["rows"][0]["refs"][0].update(target="#step-9"), "names nothing")
        for target in ("#fd-q1", "#step-1", "#FD-R-02", "#plan", "#answers", "#tests", "#fd-answers"):
            b = plan_bundle()
            b["sections"][0]["rows"][0]["refs"][0]["target"] = target
            self.assertEqual(validate_bundle.validate(b), [], target)

    def test_a_question_anchor_may_not_be_a_row_anchor(self):
        self.assertProblem(lambda b: b["answers"][0]["questions"][0].update(anchor="a-1") or b["sections"][0]["rows"][0].update(id="a-1"), "names a question")

    def test_steps_keep_build_order(self):
        def two(b):
            b["plan"]["steps"].append(dict(copy.deepcopy(b["plan"]["steps"][0]), n=3))
        self.assertProblem(two, "numbered 1, 2, 3")

    def test_revisions(self):
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(rev=2, revNote="x"), "after this revision")
        def v2(b):
            b["header"].update(revision=2, revisions=[{"n": 1, "note": "first draft"}, {"n": 2, "note": "after notes"}])
            b["id"] = ID.replace("-v1-", "-v2-")
        self.assertEqual(self.problems(v2), [])
        self.assertProblem(lambda b: (v2(b), b["sections"][0]["rows"][0].update(rev=2)), "says what changed in revNote")
        self.assertProblem(lambda b: (v2(b), b["plan"]["steps"][0]["subs"][0].update(rev=2)), "carries rev 2 too")
        self.assertProblem(lambda b: b["header"].update(revision=2), "revisions 1 to 2")
        self.assertProblem(lambda b: b["sections"][0]["rows"][0].update(revNote="x"), "go with rev")

    def test_the_id_names_page_and_revision(self):
        self.assertProblem(lambda b: b.update(id=ID.replace("-v1-", "-v4-")), "does not name page plan and revision v1")

    def test_as_approved_and_map_rules(self):
        self.assertProblem(lambda b: b["sections"][0].update(rows=[row("D-1")]), "holds no rows", end_bundle)
        self.assertProblem(lambda b: b["sections"][1].update(asApproved=True), "changes section only", end_bundle)
        self.assertProblem(lambda b: b["sections"][1].update(map=b["sections"][2]["map"]), "built section only", end_bundle)
        self.assertProblem(lambda b: b["sections"][2]["map"]["edges"].append({"from": "a", "to": "z"}), "both ends", end_bundle)
        self.assertProblem(lambda b: b["sections"][2]["map"]["nodes"][0].update(target="#B-9"), "names nothing", end_bundle)


def sections(*specs):
    """[(key, kind, [labels], looks)] → sections."""
    out = []
    for key, kind, labels, looks in specs:
        out.append({"key": key, "kind": kind, "rows": [{"id": f"{key}-{i}", "label": lab, "lookFirst": i < looks} for i, lab in enumerate(labels)]})
    return out


class TestOrder(unittest.TestCase):
    def order(self, secs, plan=True, answers=True, design=False):
        b = {"sections": secs, "answers": [{"key": "x"}] if answers else []}
        if plan:
            b["plan"] = {"steps": []}
        if design:
            b["design"] = {"rows": []}
        return validate_bundle.order(b)

    def test_top_label_then_look_first_then_count(self):
        got = self.order(sections(("low", "assumptions", ["low"], 0), ("crit", "visible", ["critical"], 0),
                                  ("high2", "findings", ["high", "high"], 0), ("high1", "narrows", ["high"], 1)))
        self.assertEqual(got, ["crit", "high1", "high2", "plan", "low", "answers"])

    def test_plan_comes_first_when_nothing_is_critical_or_high(self):
        got = self.order(sections(("a", "assumptions", ["medium"], 0), ("b", "findings", ["low"], 0)))
        self.assertEqual(got, ["plan", "a", "b", "answers"])

    def test_tests_come_after_every_other_section_however_important(self):
        got = self.order(sections(("tests", "tests", ["critical"], 1), ("a", "assumptions", ["low"], 0)))
        self.assertEqual(got, ["plan", "a", "tests", "answers"])

    def test_unit_end_puts_the_design_last(self):
        got = self.order(sections(("built", "built", ["core"], 0), ("changes", "changes", ["medium"], 0)), plan=False, answers=False, design=True)
        self.assertEqual(got, ["built", "changes", "design"])

    def test_rows_sort_by_label_then_look_first(self):
        rows = [{"id": "a", "label": "low"}, {"id": "b", "label": "high"}, {"id": "c", "label": "high", "lookFirst": True}, {"id": "d", "label": "critical"}]
        self.assertEqual([r["id"] for r in validate_bundle.sort_rows(rows)], ["d", "c", "b", "a"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_orders_like_the_contract(self):
        for b in (plan_bundle(), end_bundle()):
            self.assertEqual(render(b)["order"], validate_bundle.order(b))
        b = plan_bundle()
        b["sections"][0]["rows"] = [row("A-1", "low"), row("A-2", "medium")]
        b["sections"][1]["rows"][0]["refs"] = []
        b["sections"][2]["rows"][0]["label"] = "low"
        self.assertEqual(render(b)["order"], validate_bundle.order(b))
        self.assertEqual(validate_bundle.order(b)[0], "plan")


if __name__ == "__main__":
    unittest.main()
