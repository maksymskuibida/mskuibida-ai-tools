"""Tests for the review findings at a gate (hooks/findings_round.py through hooks/gate_guard.py, scripts/findings.py,
gate_bundle.py --findings): no Findings question; what the agent cannot fix for certain goes on the gate page as cards
the developer sorts; the agent reads the sort back.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_helpers import JUDGED  # noqa: E402

from test_gate_guard import HERE, PLUGIN, URL, INTENT, Case, gate_question

BRIEFS = os.path.join(HERE, "fixtures", "findings")
FINDINGS_PY = os.path.join(PLUGIN, "scripts", "findings.py")
STAGE = "user-stories"
BRIEF_CMD = f"aidlc engine review-brief review --stage {STAGE} --why first"
Q = "User Stories complete. How would you like to proceed?"


def brief(name="brief-open.txt"):
    with open(os.path.join(BRIEFS, name), encoding="utf-8") as f:
        return f.read()


class FindingsCase(Case):
    def print_brief(self, name="brief-open.txt", cmd=BRIEF_CMD, **kw):
        code, out, err = self.post("Bash", {"command": cmd}, {"stdout": brief(name), "stderr": ""}, **kw)
        self.assertEqual(code, 0, err)
        return self.context(out) if out.strip() else ""

    def findings_file(self, session="s1"):
        return os.path.join(self.state, session + ".findings.json")

    def suggest(self, values):
        done = subprocess.run([sys.executable, FINDINGS_PY, "suggest", "--findings", self.findings_file(), "--set",
                               json.dumps(values)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def gate_row(self, gate_id, cards=None):
        folder = os.path.join(self.tmp, "gate-%d" % self.counter)
        self.counter += 1
        os.makedirs(folder)
        path = os.path.join(folder, "gate.json")
        row = dict({"title": "User Stories", "status": "open", "round": 1}, **JUDGED)
        if cards is not None:
            row["findings"] = cards
        with open(path, "w", encoding="utf-8") as f:
            json.dump(row, f)
        return {"action": "batch", "url": URL, "writes": [{"op": "set", "collection": "gates", "doc_id": gate_id, "file_path": path}]}

    def cards(self):
        done = subprocess.run([sys.executable, FINDINGS_PY, "cards", "--findings", self.findings_file()], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def open_with_page(self):
        """The gate opens, the brief lists R-02 (Major) and R-03 (Minor, no action), the suggestion is written, and the page
        goes out with both cards and its link."""
        self.open_gate()
        self.print_brief()
        self.suggest({"R-03": "Use one name for the order event."})
        gate_id = f"{INTENT}-{STAGE}-20260101T0900"
        call = self.gate_row(gate_id, self.cards())
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 0, err)
        code, out, err = self.post("ArtifactData", call, {"ok": True})
        self.assertIn("2 finding card(s)", self.context(out))
        self.said(f"**Read:** {URL}#{gate_id}")
        return gate_id

    def answer_gate(self, answer):
        question = gate_question(Q)
        self.assertEqual(self.ask(Q)[0], 0)
        return self.post("AskUserQuestion", question, {"answers": {Q: answer}})

    def read_page(self, gate_id, picks):
        return self.post("ArtifactData", {"action": "get", "collection": "gates", "doc_id": gate_id, "url": URL},
                         {"document": {"title": "x", "findingPicks": picks}})

    def report(self, result, extra=""):
        return self.pre("Bash", {"command": f"aidlc engine orchestrate report --stage {STAGE} --result {result}{extra}"})


class TestTheBrief(FindingsCase):
    def test_open_findings_become_a_round_with_no_findings_question(self):
        said = self.print_brief()
        self.assertIn("2 review finding(s) of user-stories are open (1 blocking): R-02, R-03", said)
        self.assertIn("There is no Findings question", said)
        self.assertIn("Fix now every finding you can fix for certain", said)
        self.assertIn("--findings " + self.findings_file(), said)
        self.assertIn('model: \\"haiku\\"'.replace("\\", ""), said)
        rnd = self.state_of()["findings"]
        self.assertEqual((rnd["ids"], rnd["blocking"]), (["R-02", "R-03"], ["R-02"]))

    def test_a_piped_brief_is_refused_in_shape(self):
        code, _out, err = self.pre("Bash", {"command": BRIEF_CMD + " | head -40"})
        self.assertEqual(code, 2)
        self.assertIn("pipes or redirects", err)
        code, _out, err = self.pre("Bash", {"command": BRIEF_CMD + " > /tmp/brief.txt"})
        self.assertEqual(code, 2)
        self.assertEqual(self.pre("Bash", {"command": BRIEF_CMD + " 2>/dev/null"})[0], 0)

    def test_a_cut_off_brief_holds_the_gate_until_printed_again(self):
        self.open_gate()
        self.print_brief("brief-cut.txt")
        self.publish()
        code, _out, err = self.ask(Q)
        self.assertEqual(code, 2)
        self.assertIn("the review brief was cut off", err)
        self.assertIn("as the only command", err)
        self.print_brief()
        self.assertFalse(self.state_of()["findings"].get("truncated"))

    def test_a_brief_with_no_open_finding_opens_nothing(self):
        self.assertEqual(self.print_brief("brief-none.txt"), "")
        self.assertIsNone(self.state_of() and self.state_of()["findings"])

    def test_a_ready_review_pass_settles_the_round(self):
        self.print_brief()
        cmd = f"aidlc engine log review --stage {STAGE} --reviewer r --iteration 2 --verdict READY | head -c 800"
        code, out, err = self.post("Bash", {"command": cmd}, {"stdout": '{"event": "REVIEW_COMPLETED"}'})
        self.assertIn("came back READY", self.context(out))
        self.assertIsNone(self.state_of()["findings"])

    def test_a_not_ready_pass_leaves_the_round(self):
        self.print_brief()
        cmd = f"aidlc engine log review --stage {STAGE} --reviewer r --iteration 2 --verdict NOT_READY"
        self.post("Bash", {"command": cmd}, {"stdout": '{"event": "REVIEW_COMPLETED"}'})
        self.assertEqual(self.state_of()["findings"]["ids"], ["R-02", "R-03"])


class TestThePage(FindingsCase):
    def test_cards_need_a_cheap_models_suggestion_where_the_reviewer_named_none(self):
        self.print_brief()
        done = subprocess.run([sys.executable, FINDINGS_PY, "cards", "--findings", self.findings_file()], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no suggested action for R-03", done.stderr)
        self.assertEqual(self.suggest({"R-03": "Use one name."})["still_missing"], [])
        cards = self.cards()
        self.assertEqual([(c["id"], c["blocking"], c["proposed"], c["actionBy"]) for c in cards["items"]],
                         [("R-02", True, "fix", "reviewer"), ("R-03", False, "fix", "model")])

    def test_a_gate_row_without_the_cards_is_refused(self):
        self.open_gate()
        self.print_brief()
        call = self.gate_row(f"{INTENT}-{STAGE}-20260101T0900")
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 2)
        self.assertIn("R-02, R-03 of the review are not on the page", err)
        self.assertIn("--findings " + self.findings_file(), err)

    def test_the_approval_question_waits_for_a_page_with_the_cards(self):
        self.open_gate()
        gate_id = self.publish()
        self.print_brief()  # printed after the page went out
        code, _out, err = self.ask(Q)
        self.assertEqual(code, 2)
        self.assertIn("are not on a gate page published since the brief was printed", err)

    def test_the_agent_never_writes_the_developers_sort(self):
        call = {"action": "update", "collection": "gates", "doc_id": f"{INTENT}-{STAGE}-20260101T0900", "url": URL,
                "data": {"findingPicks": {"R-02": {"pick": "accept"}}}}
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 2)
        self.assertIn("`findingPicks`", err)


class TestTheSort(FindingsCase):
    def test_reports_wait_until_the_sort_was_read(self):
        gate_id = self.open_with_page()
        code, out, err = self.answer_gate("Request Changes")
        self.assertIn(f"read gates/{gate_id}", self.context(out))
        code, _out, err = self.report("rejected", " --reason 'x'")
        self.assertEqual(code, 2)
        self.assertIn("was not read since they answered", err)
        self.assertIn(f'`doc_id: "{gate_id}"`', err)

    def test_a_fix_card_is_request_changes_and_named_in_the_reason(self):
        gate_id = self.open_with_page()
        self.answer_gate("Approve")
        out = self.read_page(gate_id, {"R-02": {"pick": "fix", "note": "checkout wins"}, "R-03": {"pick": "accept"}})[1]
        self.assertIn("Fix R-02; Accept R-03; Reject none", self.context(out))
        code, _out, err = self.report("approved")
        self.assertEqual(code, 2)
        self.assertIn("sorted R-02 Fix", err)
        code, _out, err = self.report("rejected", " --reason 'see the page'")
        self.assertEqual(code, 2)
        self.assertIn("does not name the Fix finding(s) R-02", err)
        self.assertEqual(self.report("rejected", " --reason 'R-02: state the winning event (checkout wins)'")[0], 0)

    def test_a_blocking_card_is_never_accepted(self):
        gate_id = self.open_with_page()
        self.answer_gate("Approve")
        self.read_page(gate_id, {"R-03": {"pick": "accept"}})
        code, _out, err = self.report("approved")
        self.assertEqual(code, 2)
        self.assertIn("R-02 block(s) approval", err)
        self.read_page(gate_id, {"R-02": {"pick": "reject", "note": "not our cart"}, "R-03": {"pick": "accept"}})
        self.assertEqual(self.report("approved")[0], 0)

    def test_a_reject_card_goes_on_the_rejected_report(self):
        gate_id = self.open_with_page()
        self.answer_gate("Request Changes")
        self.read_page(gate_id, {"R-02": {"pick": "fix"}, "R-03": {"pick": "reject", "note": "deliberate"}})
        code, _out, err = self.report("rejected", " --reason 'R-02: state it'")
        self.assertEqual(code, 2)
        self.assertIn("--reject-finding", err)
        extra = " --reason 'R-02: state it' --reject-finding 'aidlc/x/domain-model.md#R-03=deliberate'"
        self.assertEqual(self.report("rejected", extra)[0], 0)

    def test_the_sort_is_found_however_the_read_result_nests_it(self):
        gate_id = self.open_with_page()
        self.answer_gate("Request Changes")
        text = 'Document gates/x (version 3):\n' + json.dumps({"doc": {"data": {"findingPicks": {"R-02": {"pick": "fix"}}}}})
        self.post("ArtifactData", {"action": "get", "collection": "gates", "doc_id": gate_id, "url": URL}, text)
        self.assertEqual(self.state_of()["findings"]["picks"], {"R-02": {"pick": "fix", "note": ""}})

    def test_a_typed_answer_is_recorded(self):
        self.open_with_page()
        code, out, _err = self.answer_gate("Fix all")
        self.assertIn("typed Fix for every finding", self.context(out))
        self.assertEqual(self.state_of()["findings"]["typed"], "fix")
        self.assertEqual(self.report("rejected", " --reason 'x'")[0], 2)
        self.assertEqual(self.report("rejected", " --reason 'R-02: a; R-03: b'")[0], 0)

    def test_a_typed_prompt_is_recorded_too_and_accept_skips_the_blocking_finding(self):
        self.open_with_page()
        out = self.prompt("<system-reminder>x</system-reminder> accept all.")[1]
        self.assertIn("R-02 block(s) approval and cannot be accepted", self.context(out))
        self.assertEqual(self.report("approved")[0], 2)

    def test_accepted_and_rejected_findings_are_not_asked_again_in_the_next_round(self):
        gate_id = self.open_with_page()
        self.answer_gate("Request Changes")
        self.read_page(gate_id, {"R-02": {"pick": "fix"}, "R-03": {"pick": "accept"}})
        self.post("Bash", {"command": f"aidlc engine orchestrate report --stage {STAGE} --result rejected --reason 'R-02: x'"},
                  {"stdout": "ok"})
        self.assertIsNone(self.state_of()["findings"])
        said = self.print_brief()
        self.assertIn("Already answered: R-03 (accepted)", said)
        self.assertEqual(self.state_of()["findings"]["ids"], ["R-02"])

    def test_the_approved_report_clears_the_round_and_the_memory(self):
        gate_id = self.open_with_page()
        self.answer_gate("Approve")
        self.read_page(gate_id, {"R-02": {"pick": "reject", "note": "n"}, "R-03": {"pick": "accept"}})
        self.post("Bash", {"command": f"aidlc engine orchestrate report --stage {STAGE} --result approved"}, {"stdout": "ok"})
        self.assertIsNone(self.state_of()["findings"])
        self.print_brief()
        self.assertEqual(self.state_of()["findings"]["ids"], ["R-02", "R-03"])


class TestReviewFindingsStepsAside(FindingsCase):
    def test_the_hook_says_it_handles_findings(self):
        self.print_brief()
        with open(os.path.join(self.state, "findings-owner.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["plugin"], "approval-gates")


if __name__ == "__main__":
    unittest.main()
