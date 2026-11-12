"""The developer is always shown the page's link, as visible text, before an AI-DLC Approval question: with no recorded
publication too (the u20-timeline session: after a restart the session id changed, the state was empty and the unit-end
question went out with no link anywhere the developer could see).
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import datetime
import json
import os
import unittest

from test_gate_guard import INTENT, URL, Case, gate_question
from test_unit_rhythm_guard import UNIT, UnitCase

OTHER_URL = "https://claude.ai/artifact/zzz999"


class VisibleCase(UnitCase):
    def raw(self, entry):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        entry = dict({"isSidechain": False, "uuid": "r%d" % self.counter, "timestamp": stamp}, **entry)
        self.counter += 1
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def wrote_in_transcript(self, doc_id, url=URL):
        """The ArtifactData call that wrote the bundle, as the transcript holds it; no PostToolUse hook ran for it."""
        self.raw({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "ArtifactData", "input": {"action": "batch", "url": url, "writes": [
                {"op": "set", "collection": "bundles", "doc_id": doc_id, "file_path": "/tmp/x.json"}]}}]}})

    def tool_result(self, text):
        self.raw({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": text}]}})

    def developer_says(self, text, meta=False):
        self.raw(dict({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}},
                      **({"isMeta": True} if meta else {})))

    def end_ask(self, **kw):
        return self.pre("AskUserQuestion", gate_question("Code Generation is complete. How would you like to proceed?",
                                                         header="Unit-end", labels=("Approve", "Request Changes", "Test first")), **kw)

    @property
    def link(self):
        return f"{URL}#{self.end_id}"


class TestNoRecordedPublication(VisibleCase):
    def test_no_state_and_no_link_is_refused_with_steps(self):
        self.assertIsNone(self.state_of())
        code, _out, err = self.end_ask()
        self.assertEqual(code, 2)
        self.assertIn("no text message of yours since the developer's last message carries the page's link", err)
        self.assertIn("anywhere in the text you write before the question", err)
        self.assertIn("2. Put nothing after the question", err)
        self.assertIn("3. Then call AskUserQuestion", err)
        self.assertIn("Artifact", err)

    def test_the_unit_end_header_alone_makes_it_an_approval_question(self):
        question = gate_question("Done?", header="Unit-end", labels=("Yes", "No"))
        self.assertEqual(self.pre("AskUserQuestion", question)[0], 2)

    def test_other_questions_are_not_held(self):
        question = gate_question("Which database?", header="Database", labels=("Postgres", "SQLite"))
        self.assertEqual(self.pre("AskUserQuestion", question), (0, "", ""))

    def test_the_link_is_found_in_the_transcript_without_a_state_file(self):
        self.wrote_in_transcript(self.end_id)
        self.assertIsNone(self.state_of())
        code, _out, err = self.end_ask()
        self.assertEqual(code, 2)
        self.assertIn(self.link, err)
        self.assertIn("restarted", err)

    def test_the_newest_bundle_of_the_unit_and_page_is_the_link(self):
        older = f"{INTENT}-{UNIT}-unit-end-v1-20260101T0900"
        self.wrote_in_transcript(older)
        self.wrote_in_transcript(self.end_id)
        self.wrote_in_transcript(f"{INTENT}-{UNIT}-plan-v9-{self.now}")  # a plan page is not the unit-end page
        self.wrote_in_transcript(f"{INTENT}-u9-other-unit-end-v9-{self.now}")  # another Unit's
        err = self.end_ask()[2]
        self.assertIn(self.link, err)
        self.assertNotIn(older, err)

    def test_the_link_is_found_in_another_sessions_state(self):
        self.write_bundle(self.end_id)  # recorded in the state of session s1
        self.assertIsNotNone(self.state_of("s1"))
        code, _out, err = self.end_ask(session="s2")  # the restarted session has a new id and no state
        self.assertIsNone(self.state_of("s2"))
        self.assertEqual(code, 2)
        self.assertIn(self.link, err)
        self.said(self.link)
        self.assertEqual(self.end_ask(session="s2"), (0, "", ""))

    def test_the_correct_link_in_visible_text_before_the_question_passes_with_no_state(self):
        self.wrote_in_transcript(self.end_id)
        self.said(f"Unit-end page v1:\n{self.link}")
        self.assertIsNone(self.state_of())
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_the_correct_link_passes_with_a_state_file_too(self):
        self.write_bundle(self.end_id)
        self.assertIsNotNone(self.state_of())
        self.assertEqual(self.end_ask()[0], 2)
        self.said(f"Unit-end page v1:\n{self.link}")
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_only_the_artifact_is_known_so_a_link_to_it_for_this_unit_is_needed(self):
        self.wrote_in_transcript(f"{INTENT}-{UNIT}-plan-v1-{self.now}")  # a plan page: no exact unit-end page on record
        code, _out, err = self.end_ask()
        self.assertEqual(code, 2)
        self.assertIn(f"{URL}#<the row id you wrote>", err)
        self.said(f"{URL}#{INTENT}-u9-other-unit-end-v1-{self.now}")
        self.assertEqual(self.end_ask()[0], 2)  # a link to another Unit's page does not do
        self.said(f"{URL}#{INTENT}-{UNIT}-unit-end-v3-{self.now}")
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_the_plan_question_wants_the_plan_page(self):
        plan_id = f"{INTENT}-{UNIT}-plan-v1-{self.now}"
        self.wrote_in_transcript(plan_id)
        self.wrote_in_transcript(self.end_id)
        question = gate_question("Approve the code plan?", labels=("Approve Plan", "Request Changes"))
        err = self.pre("AskUserQuestion", question)[2]
        self.assertIn(f"{URL}#{plan_id}", err)


class TestInvisibleWays(VisibleCase):
    """Each way of 'sending' the link the developer cannot see, with the link on record and with it not."""

    def setUp(self):
        super().setUp()
        self.wrote_in_transcript(self.end_id)

    def refused(self, why):
        code, _out, err = self.end_ask()
        self.assertEqual(code, 2)
        self.assertIn(why, err)
        self.assertIn(self.link, err)
        self.assertIn("anywhere in the text you write before the question", err)
        return err

    def test_the_link_only_in_thinking(self):
        self.said(f"I will show {self.link}", block="thinking")
        self.refused("only in your thinking, and thinking is not output")

    def test_the_link_only_in_a_tool_call_or_a_tool_result(self):
        self.refused("only in a tool call or a tool result")  # the ArtifactData call itself holds the id
        self.tool_result(f"Published. Send the developer the link `{self.link}`")
        self.refused("only in a tool call or a tool result")

    def test_the_link_in_bash_output_or_an_artifact_open(self):
        self.said(self.link, block="tool_use")
        self.refused("only in a tool call or a tool result")

    def test_the_link_after_the_question_in_the_same_response(self):
        self.said("question", block="ask")
        self.said(f"Here is the page: {self.link}")
        self.refused("written after an AskUserQuestion call in the same response")

    def test_text_that_only_refers_to_the_link(self):
        self.said("I've saved the v6 page. Please check the linked artifact.")
        self.refused("only refers to the page")
        self.said("See the page above.")
        self.refused("only refers to the page")

    def test_a_markdown_link_to_another_address(self):
        self.said(f"[{self.link}](https://example.com/elsewhere)")
        self.refused("target is not the page's URL")

    def test_a_markdown_link_with_the_right_target_counts(self):
        self.said(f"[the unit-end page]({self.link})")
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_a_link_cut_short_does_not_count(self):
        self.said(self.link[:-3])
        self.assertEqual(self.end_ask()[0], 2)

    def test_the_link_of_an_earlier_message_of_the_developer_turn_counts(self):
        self.said(f"Page:\n{self.link}")
        self.said("Now the question.")
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_a_link_from_before_the_developers_last_message_must_be_sent_again(self):
        self.said(f"Page:\n{self.link}")
        self.developer_says("I don't see the form")
        self.refused("since the developer's last message")
        self.said(self.link)
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_a_message_injected_by_the_harness_is_not_the_developer(self):
        self.said(f"Page:\n{self.link}")
        self.developer_says("Stop hook feedback:\nsomething", meta=True)
        self.developer_says("Your response above was cut off mid-stream. Resume directly from where it stops.")
        self.developer_says("<task-notification>\n<task-id>x</task-id>\n</task-notification>")
        self.tool_result("ok")
        self.assertEqual(self.end_ask(), (0, "", ""))

    def test_a_subagents_text_does_not_count(self):
        self.said(self.link, sidechain=True)
        self.assertEqual(self.end_ask()[0], 2)


class TestAnyPosition(VisibleCase):
    """The link counts wherever it sits in a visible text block before the question."""

    def setUp(self):
        super().setUp()
        self.wrote_in_transcript(self.end_id)

    def test_first_middle_and_last_line_and_inside_a_sentence(self):
        for text in (f"{self.link}\nThe rest.", f"Intro.\n{self.link}\nMore.", f"Intro.\nMore.\n{self.link}",
                     f"The unit-end page is at {self.link}, please read it.", f"[the page]({self.link}) is ready"):
            with self.subTest(text=text):
                self.developer_says("go on")
                self.said(text)
                self.assertEqual(self.end_ask(), (0, "", ""))

    def test_a_link_to_another_gate_does_not_count(self):
        self.said(f"{URL}#{INTENT}-u9-other-unit-end-v1-{self.now}")
        self.assertEqual(self.end_ask()[0], 2)

    def test_the_refusal_shows_what_was_found_and_asks_for_no_position(self):
        self.said("I will ask now.", block="thinking")
        self.said("Here is the summary, no link.")
        err = self.end_ask()[2]
        self.assertIn("Found since the developer's last message: 1 visible text block(s), none holding the page's link", err)
        self.assertIn("1 thinking block(s)", err)
        self.assertIn("Nothing will make this pass later; write the link as text now.", err)
        self.assertNotIn("first line", err)
        self.assertNotIn("nothing else on that line", err)

    def test_the_hook_context_alone_is_named_as_not_seen(self):
        self.tool_result(f"gates is published. Send the developer the link `{self.link}`")
        err = self.end_ask()[2]
        self.assertIn("hook context", err)
        self.assertIn("0 visible text block(s)", err)


class TestPerStageApprovalToo(Case):
    def wrote_gate(self, gate_id):
        self.raw({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "ArtifactData", "input": {"action": "batch", "url": URL, "writes": [
                {"op": "set", "collection": "gates", "doc_id": gate_id, "file_path": "/tmp/x.json"}]}}]}})

    def raw(self, entry):
        self.said("x", block="tool_use")
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"isSidechain": False, "timestamp": "2099-01-01T00:00:00.000Z"}, **entry)) + "\n")

    def test_a_per_stage_gate_with_no_page_on_record_is_told_to_publish(self):
        code, _out, err = self.ask("Stage complete. How would you like to proceed?")
        self.assertEqual(code, 2)
        self.assertIn("Publish them first", err)

    def test_a_per_stage_gate_with_the_page_on_record_but_no_state_wants_the_visible_link(self):
        gate_id = f"{INTENT}-user-stories-20260101T0900"
        self.wrote_gate(gate_id)
        code, _out, err = self.ask("Stage complete. How would you like to proceed?")
        self.assertEqual(code, 2)
        self.assertIn("anywhere in the text you write before the question", err)
        self.assertIn(f"{URL}#{gate_id}", err)

    def test_a_per_stage_gate_with_the_link_in_the_text_passes(self):
        self.open_gate()
        self.publish()
        self.assertEqual(self.ask("Stage complete. How would you like to proceed?"), (0, "", ""))

    def test_a_per_stage_link_found_without_a_state_file(self):
        gate_id = f"{INTENT}-user-stories-20260101T0900"
        self.wrote_gate(gate_id)
        self.said(f"{URL}#{gate_id}")
        self.assertEqual(self.ask("Stage complete. How would you like to proceed?"), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
