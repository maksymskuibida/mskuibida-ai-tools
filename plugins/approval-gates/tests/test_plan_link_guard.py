"""Tests for the test-plan link guard of hooks/gate_guard.py: the hint after the plan is written, the refusal of every
question until the link was sent, the plan written again, and the Stop hook.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import time
import unittest

from test_gate_guard import Case, URL, INTENT, gate_question

PLAN = f"{INTENT}-u1-test-v1-20260101T0900"
PLAN2 = f"{INTENT}-u1-test-v2-20260101T0930"
BUNDLE = f"{INTENT}-u1-unit-end-v2-20260101T0900"


def plan_write(plan_id=PLAN, url=URL, extra=()):
    writes = [{"op": "set", "collection": "plans", "doc_id": plan_id, "data": {"title": "Plan", "sections": []}}]
    writes += list(extra)
    return {"action": "batch", "url": url, "writes": writes}


def test_plan_question(labels=("Do the agent step for A", "Change the plan")):
    return gate_question("Ready for section A?", header="Test plan", labels=labels)


class TestPlanLink(Case):
    def publish_plan(self, plan_id=PLAN, **kw):
        call = plan_write(plan_id, **kw)
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 0, err)
        code, out, err = self.post("ArtifactData", call, {"ok": True})
        self.assertEqual(code, 0, err)
        return out

    def ask_plan(self, **kw):
        return self.pre("AskUserQuestion", test_plan_question(**kw))

    def test_the_hint_names_the_link_and_the_one_response(self):
        text = self.context(self.publish_plan())
        self.assertIn(f"`{URL}#{PLAN}`", text)
        self.assertIn("text block in a message of its own", text)
        self.assertIn("SAME response", text)
        self.assertIn("never end the turn on the link alone", text)
        self.assertNotIn("unit-end page", text)
        self.assertEqual(list(self.state_of()["plans"]), [PLAN])

    def test_the_hint_with_a_unit_end_page_in_the_same_batch_names_both_links(self):
        bundle = {"op": "set", "collection": "bundles", "doc_id": BUNDLE, "data": {"title": "Unit"}}
        # the unit-end page counts for the claimed Unit under the unit-end rhythm
        import json, os
        with open(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"), "w", encoding="utf-8") as f:
            json.dump({"unit": "u1", "gate_rhythm": "unit-end"}, f)
        call = plan_write(extra=[bundle])
        code, out, err = self.post("ArtifactData", call, {"ok": True})
        self.assertEqual(code, 0, err)
        text = self.context(out)
        self.assertIn(f"`{URL}#{BUNDLE}`", text)
        self.assertIn(f"`{URL}#{PLAN}`", text)
        self.assertIn("both links", text)
        self.assertIn("the test-plan ask above, not the unit-end Approval question", text)

    def test_a_failed_write_records_nothing(self):
        code, out, _err = self.post("ArtifactData", plan_write(), {"is_error": True})
        self.assertEqual((code, out.strip()), (0, ""))
        self.assertIsNone(self.state_of())

    def test_an_update_of_the_plan_is_not_a_publish(self):
        call = {"action": "update", "url": URL, "collection": "plans", "doc_id": PLAN, "data": {"agentDone": ["A"]}}
        self.assertEqual(self.post("ArtifactData", call, {"ok": True})[1].strip(), "")

    def test_the_question_is_refused_before_the_link_and_passes_after_it(self):
        self.publish_plan()
        code, _out, err = self.ask_plan()
        self.assertEqual(code, 2)
        self.assertIn(f"**Read:** {URL}#{PLAN}", err)
        self.said("thinking about it", block="thinking")
        self.assertEqual(self.ask_plan()[0], 2)
        self.said(f"Test plan: **Read:** {URL}#{PLAN}")
        code, _out, err = self.ask_plan()
        self.assertEqual((code, err), (0, ""))

    def test_any_question_is_refused_while_the_link_is_pending(self):
        self.publish_plan()
        for q in (gate_question("Which one?", header="Pick", labels=("A", "B")), test_plan_question(("Section A completed, go on", "Change the plan"))):
            self.assertEqual(self.pre("AskUserQuestion", q)[0], 2)

    def test_a_link_sent_before_the_write_does_not_count(self):
        self.said(f"{URL}#{PLAN}")
        time.sleep(0.05)
        self.publish_plan()
        self.assertEqual(self.ask_plan()[0], 2)

    def test_the_link_in_a_user_message_or_tool_call_does_not_count(self):
        self.publish_plan()
        self.said(f"{URL}#{PLAN}", kind="user")
        self.said(f"{URL}#{PLAN}", block="tool_use")
        self.assertEqual(self.ask_plan()[0], 2)

    def test_a_plan_published_again_needs_its_link_again(self):
        self.publish_plan()
        self.said(f"**Read:** {URL}#{PLAN}")
        self.assertEqual(self.ask_plan()[0], 0)
        time.sleep(0.05)
        self.publish_plan()  # the same plan written again
        code, _out, err = self.ask_plan()
        self.assertEqual(code, 2)
        self.assertIn(f"{URL}#{PLAN}", err)
        self.said(f"**Read:** {URL}#{PLAN}")
        self.assertEqual(self.ask_plan()[0], 0)
        self.publish_plan(PLAN2)  # a revised plan has a new id
        code, _out, err = self.ask_plan()
        self.assertEqual(code, 2)
        self.assertIn(f"{URL}#{PLAN2}", err)

    def test_a_session_without_a_plan_is_not_affected(self):
        self.assertEqual(self.pre("AskUserQuestion", gate_question("Which?", header="Pick", labels=("A", "B")))[0], 0)

    def test_the_stop_hook_blocks_once_when_the_link_was_never_sent(self):
        self.publish_plan()
        code, out, _err = self.stop()
        self.assertEqual(code, 0)
        self.assertIn('"block"', out)
        self.assertIn(f"{URL}#{PLAN}", out)
        self.assertEqual(self.stop()[1].strip(), "")

    def test_the_stop_hook_is_quiet_after_the_link_or_when_already_active(self):
        self.publish_plan()
        self.assertEqual(self.stop(active=True)[1].strip(), "")
        self.said(f"**Read:** {URL}#{PLAN}")
        self.said("Ready for section A?", block="ask")
        self.assertEqual(self.stop()[1].strip(), "")

    def test_the_refusal_says_a_link_only_response_ends_the_turn(self):
        self.publish_plan()
        err = self.ask_plan()[2]
        self.assertIn("A response with only the link ends your turn and the developer has no question to answer", err)
        self.assertIn("the link text block AND this AskUserQuestion call", err)

    def test_a_link_only_ending_is_blocked_once_per_link_message_and_again_in_a_later_turn(self):
        self.publish_plan()
        self.assertEqual(self.ask_plan()[0], 2)
        self.said(f"**Read:** {URL}#{PLAN}")
        reason = json.loads(self.stop()[1])["reason"]
        self.assertIn("The link is sent; now ask the test-plan question", reason)
        self.assertIn("Do not write the link again", reason)
        self.assertEqual(self.stop()[1].strip(), "")           # the same link message: once
        self.said(f"**Read:** {URL}#{PLAN}")                   # a later turn, same plan
        self.assertIn("now ask", self.stop()[1])
        self.said("Ready for section A?", block="ask")
        self.assertEqual(self.stop()[1].strip(), "")           # link and question: allowed

    def test_a_plan_written_again_can_block_the_stop_again(self):
        self.publish_plan()
        self.assertIn("block", self.stop()[1])
        self.publish_plan()
        self.assertIn("block", self.stop()[1])


if __name__ == "__main__":
    unittest.main()
