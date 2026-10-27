"""Tests for the Build and Test part of scripts/gate_bundle.py and contract/build-test.schema.json.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import shutil
import tempfile
import unittest

from test_gate_bundle import Case, bundle, load, record

validate_bundle = load("validate_bundle", "scripts", "validate_bundle.py")
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "build-and-test")


def parse(folder=FIXTURE):
    return bundle.parse_build_test(folder)


class TestParser(unittest.TestCase):
    def test_targets_with_their_unit_and_verdict(self):
        targets = parse()["targets"]
        self.assertEqual(len(targets), 18)
        first = targets[0]
        self.assertEqual(first, {"id": "u1:NFR2.1", "unit": "U1", "verdict": "Met", "source": "u1 performance-requirements, Targets",
                                 "expected": "read 200-item day, p95 ≤ 300 ms", "actual": "3.2 ms", "evidence": "AP test_speed.py", "owner": "build-and-test"})
        self.assertEqual({t["unit"] for t in targets}, {"U1", "U2", "U3", "U4", "U5", "U6", "Cross-repository"})

    def test_markup_is_stripped_and_an_escaped_pipe_stays_in_its_cell(self):
        by_id = {t["id"]: t for t in parse()["targets"]}
        self.assertNotIn("**", by_id["u3:NFR7.4"]["actual"])
        self.assertEqual(by_id["u1:NFR5.4"]["expected"], "a write and a read | at once, one stale")
        self.assertEqual(by_id["u1:NFR5.4"]["verdict"], "Unverified")

    def test_counts_come_from_the_targets(self):
        self.assertEqual(parse()["counts"], {"met": 14, "notMet": 2, "unverified": 2, "na": 0, "total": 18})

    def test_evidence_legend_reads_several_codes_on_one_line(self):
        legend = parse()["evidence"]
        self.assertEqual(set(legend), {"A", "AP", "W", "WT", "E", "SZ", "L", "H", "I"})
        self.assertEqual(legend["SZ"], "pnpm size: 203.1 of 300 KB")
        self.assertTrue(legend["H"].startswith("by hand"))

    def test_commands_and_their_outcome(self):
        commands = parse()["commands"]
        self.assertEqual([c["check"] for c in commands], ["Web build", "API install", "API lint", "API tests", "Web unit tests", "Web size"])
        self.assertTrue(all(c["ok"] for c in commands), "`0 failed` is not a failure")
        self.assertEqual(commands[2]["command"], "uv run ruff check .")

    def test_a_failed_command_is_not_ok(self):
        for result, ok in [("12 failed, 700 passed", False), ("0 failed", True), ("Error: boom", False), ("no errors", True),
                           ("timed out after 60 s", False), ("all checks passed", True)]:
            self.assertEqual(bundle.command_ok(result), ok, result)

    def test_coverage_names_the_repo_and_its_floor(self):
        self.assertEqual(parse()["coverage"], [{"repo": "API", "pct": 98.85, "floor": 80.0}, {"repo": "Web", "pct": 98.17, "floor": 80.0}])

    def test_instruction_files_do_not_add_commands(self):
        self.assertFalse(any(c.get("command") == "pnpm build" for c in parse()["commands"]))

    def test_columns_are_found_by_name_and_missing_ones_left_out(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "summary.md"), "w", encoding="utf-8") as f:
            f.write("### U9 Odd\n\n| Verdict | Target | Expected |\n|:-:|---|---|\n| not met | z:1 | fast |\n| `Met` | z:2 | |\n| Unclear | z:3 | x |\n")
        got = parse(tmp)
        self.assertEqual(got["targets"][0], {"id": "z:1", "unit": "U9", "verdict": "Not Met", "expected": "fast"})
        self.assertEqual(got["targets"][1], {"id": "z:2", "unit": "U9", "verdict": "Met"})
        self.assertEqual(got["targets"][2]["verdict"], "Unclear")
        self.assertEqual(got["counts"], {"met": 1, "notMet": 1, "unverified": 0, "na": 0, "total": 3})
        self.assertNotIn("commands", got)
        self.assertNotIn("evidence", got)

    def test_nothing_found_gives_none(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "notes.md"), "w", encoding="utf-8") as f:
            f.write("# Notes\n\nNo tables here.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
        self.assertIsNone(parse(tmp))


class TestSchema(unittest.TestCase):
    def test_the_parsed_fixture_holds_to_the_contract(self):
        self.assertEqual(validate_bundle.validate_build_test(parse()), [])

    def test_absent_is_fine(self):
        self.assertEqual(validate_bundle.validate_build_test(None), [])

    def problems(self, change):
        value = json.loads(json.dumps(parse()))
        change(value)
        return validate_bundle.validate_build_test(value)

    def test_problems_are_named(self):
        self.assertTrue(any("unknown field" in p for p in self.problems(lambda b: b.update(extra=1))))
        self.assertTrue(any("`id` is missing" in p for p in self.problems(lambda b: b["targets"][0].pop("id"))))
        self.assertTrue(any("must be boolean" in p for p in self.problems(lambda b: b["commands"][0].update(ok="yes"))))
        self.assertTrue(any("above 100" in p for p in self.problems(lambda b: b["coverage"][0].update(pct=140))))
        self.assertTrue(any("key" in p for p in self.problems(lambda b: b["evidence"].update(lower="x"))))
        self.assertTrue(any("`total` is missing" in p for p in self.problems(lambda b: b["counts"].pop("total"))))


class TestGateRow(Case):
    def setUp(self):
        super().setUp()
        folder = os.path.join(record(self.project), "construction", "build-and-test")
        shutil.copytree(FIXTURE, folder)

    def test_the_row_carries_build_test_for_this_stage(self):
        self.summary("--stage", "build-and-test", "--no-brief")
        row = self.gate()
        self.assertEqual(row["buildTest"]["counts"]["notMet"], 2)
        self.assertEqual(validate_bundle.validate_build_test(row["buildTest"]), [])
        self.assertEqual(row["phase"], "construction")

    def test_other_stages_get_none(self):
        self.summary("--stage", "user-stories", "--no-brief")
        self.assertNotIn("buildTest", self.gate())

    def test_without_tables_the_field_is_left_out(self):
        folder = os.path.join(record(self.project), "construction", "build-and-test")
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        with open(os.path.join(folder, "build-and-test-summary.md"), "w", encoding="utf-8") as f:
            f.write("# Summary\n\nAll fine.\n")
        self.summary("--stage", "build-and-test", "--no-brief")
        self.assertNotIn("buildTest", self.gate())

    def test_the_validator_cli_checks_a_row(self):
        self.summary("--stage", "build-and-test", "--no-brief")
        self.assertEqual(validate_bundle.main([os.path.join(self.out, "gate.json"), "--build-test"]), 0)


if __name__ == "__main__":
    unittest.main()
