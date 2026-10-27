"""Tests for scripts/findings.py.
Run: python3 -m unittest discover -s plugins/review-findings/tests"""

import contextlib
import datetime
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def load(name, *parts):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", *parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


findings = load("findings", "scripts", "findings.py")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def by_id(doc):
    return {f["id"]: f for f in doc["findings"]}


class ParseBrief(unittest.TestCase):
    def setUp(self):
        self.doc = findings.parse_brief(fixture("brief-open.txt"), "domain-design")

    def test_open_findings_only(self):
        self.assertEqual([f["id"] for f in self.doc["findings"]], ["R-02", "R-03"])
        self.assertEqual(findings.counts(self.doc), (2, 1))

    def test_blocking_is_critical_or_major(self):
        found = by_id(self.doc)
        self.assertTrue(found["R-02"]["blocking"])
        self.assertFalse(found["R-03"]["blocking"])
        self.assertEqual((found["R-02"]["severity"], found["R-03"]["status"]), ("Major", "Unresolved"))

    def test_quotes_hydrate_the_rows(self):
        found = by_id(self.doc)["R-02"]
        self.assertEqual(found["where"], "domain-model.md > Cart aggregate, invariants list")  # not the cut table cell
        self.assertTrue(found["finding"].startswith("The `Cart` rule `checkout | expire` is ambiguous."))
        self.assertIn("A reader cannot tell what happens to reserved stock.", found["finding"])  # a second line
        self.assertEqual(found["action"], "State the winning event.\nAdd one line on what happens to reserved stock.")

    def test_a_finding_without_quotes_keeps_the_table_cell(self):
        found = by_id(self.doc)["R-03"]
        self.assertEqual(found["where"], "domain-model.md > Events")
        self.assertEqual(found["action"], "")
        self.assertTrue(found["finding"].startswith("The Events table lists"))

    def test_header_lines(self):
        self.assertEqual(self.doc["stage_name"], "Domain Design")
        self.assertEqual(self.doc["stage"], "domain-design")
        self.assertEqual(self.doc["artifact"],
                         "aidlc/spaces/default/intents/260101-demo-shop/inception/domain-design/domain-model.md")
        self.assertEqual(findings.parse_brief(fixture("brief-open.txt"))["stage"], "domain-design")  # slug of the name

    def test_no_open_findings(self):
        doc = findings.parse_brief(fixture("brief-none.txt"), "domain-design")
        self.assertEqual(doc["findings"], [])  # Accepted risk, Resolved and Rejected: <reason> are closed
        self.assertEqual(findings.counts(doc), (0, 0))

    def test_not_a_brief(self):
        self.assertEqual(findings.parse_brief("ok\n")["findings"], [])


class ParseReview(unittest.TestCase):
    def test_six_column_table(self):
        doc = findings.parse_review(fixture("review-07.md"), "domain-design")
        self.assertEqual([f["id"] for f in doc["findings"]], ["R-01", "R-03"])  # R-02 is Resolved
        first = doc["findings"][0]
        self.assertEqual((first["severity"], first["where"]), ("Critical", "domain-model.md > Payment"))
        self.assertEqual(first["action"], "Add an idempotency key to the capture command.")
        self.assertTrue(first["blocking"])
        self.assertEqual((doc["verdict"], doc["reviewer"], doc["iteration"]), ("NOT-READY", "aidlc-architect-agent", "2"))


class ParseReport(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(FIXTURES, "report-findings.json"), encoding="utf-8") as f:
            self.doc = findings.parse_report(json.load(f))

    def test_ids_and_blocking(self):
        self.assertEqual([f["id"] for f in self.doc["findings"]], ["F-01", "F-02", "F-03"])
        self.assertEqual([f["blocking"] for f in self.doc["findings"]], [True, False, False])
        self.assertEqual(self.doc["source"], "code-review")
        self.assertEqual(findings.counts(self.doc), (3, 1))

    def test_fields(self):
        first = self.doc["findings"][0]
        self.assertEqual((first["where"], first["severity"], first["title"]), ("src/cart.py:42", "Confirmed", "Discount applied before tax"))
        self.assertIn("108 instead of 110", first["scenario"])
        self.assertEqual(self.doc["findings"][2]["severity"], "Unrated")  # no verdict

    def test_list_input_and_empty(self):
        self.assertEqual(findings.parse_report([])["findings"], [])
        self.assertEqual(findings.parse_report({"findings": []})["findings"], [])
        self.assertEqual(len(findings.parse_report([{"file": "a.py", "summary": "x"}])["findings"]), 1)


class Summary(unittest.TestCase):
    def test_block(self):
        text = findings.summary(findings.parse_brief(fixture("brief-open.txt"), "domain-design"))
        lines = text.splitlines()
        self.assertEqual(lines[0], "**Review findings — Domain Design:** 2 open, 1 blocking")
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("1. **The `Cart` rule `checkout | expire` is ambiguous.** (Blocking, domain "
                                            "model › Cart aggregate, invariants list) Two events can fire"))
        self.assertEqual(lines[3], "   **Suggested:** State the winning event. Add one line on what happens to reserved stock.")
        self.assertTrue(lines[4].startswith("2. **The Events table lists"))
        self.assertTrue(lines[5].startswith("   **Suggested:** No change was named by the reviewer"))
        self.assertEqual(len(lines), 6)

    def test_no_ids_or_paths_in_the_sentences(self):
        for doc in (findings.parse_brief(fixture("brief-open.txt"), "domain-design"), report()):
            text = findings.summary(doc)
            self.assertNotRegex(text, r"\b[RF]-\d+\b")
            self.assertNotIn(".md", text)
            self.assertNotRegex(text, r"\.py:\d+")
            self.assertNotIn("| ID |", text)

    def test_the_rest_is_clipped(self):
        doc = {"source": "aidlc", "stage_name": "X", "findings": [
            {"id": "R-01", "severity": "Minor", "where": "w", "finding": "One. " + "A" * 300 + ".", "blocking": False,
             "title": "One."}]}
        line = findings.summary(doc).splitlines()[2]
        self.assertTrue(line.endswith("…"))
        self.assertEqual(findings.first_sentence("One. Two.", 140), "One.")
        self.assertEqual(findings.first_sentence("See requirements.md for more. Two.", 140), "See requirements.md for more.")

    def test_code_review_label(self):
        self.assertTrue(findings.summary(report()).startswith("**Review findings — code review:** 3 open, 1 blocking"))

    def test_none_open(self):
        self.assertEqual(findings.summary({"source": "aidlc", "stage_name": "X", "findings": []}),
                         "**Review findings — X:** 0 open, 0 blocking")


def report():
    with open(os.path.join(FIXTURES, "report-findings.json"), encoding="utf-8") as f:
        return findings.parse_report(json.load(f))


class PlainWords(unittest.TestCase):
    def doc(self, **extra):
        return {"source": "aidlc", "stage_name": "Domain Design", "findings": [
            dict({"id": "R-02", "severity": "Major", "blocking": True, "where": "domain-model.md > Cart aggregate ...",
                  "finding": "The rule clashes with R-04. See src/cart/rules.py:12 for the code.",
                  "action": "Align it with R-04 and R-01.", "title": "The rule clashes with R-04."}, **extra),
            {"id": "R-04", "severity": "Minor", "blocking": False, "where": "glossary.md", "finding": "Two names.",
             "action": "", "title": "Two names."}]}

    def test_ids_become_numbers_and_references(self):
        first, second = findings.readable(self.doc())
        self.assertEqual(first["title"], "The rule clashes with finding 2.")
        self.assertEqual(first["what"], "The rule clashes with finding 2. See rules.py for the code.")
        self.assertEqual(first["rest"], "See rules.py for the code.")
        self.assertEqual(first["suggested"], "Align it with finding 2 and an earlier finding.")
        self.assertEqual(first["suggested_by"], "reviewer")
        refs = {r["label"]: r for r in first["refs"]}
        self.assertEqual(refs["finding 2"]["target"], "#R-04")  # a card in the same form: a live link
        self.assertEqual(refs["an earlier finding"]["target"], "finding:R-01")  # closed: not in the form
        self.assertIn("R-01", refs["an earlier finding"]["tip"])
        self.assertEqual(refs["rules.py"], {"label": "rules.py", "tip": "src/cart/rules.py, line 12",
                                            "target": "path:src/cart/rules.py"})
        self.assertEqual(refs["domain model › Cart aggregate"]["tip"], "domain-model.md > Cart aggregate")
        self.assertEqual(first["where"], "domain model › Cart aggregate")
        self.assertEqual(second["where"], "glossary")

    def test_suggested_action_order(self):
        doc = self.doc()
        self.assertEqual(findings.needs_suggestion(doc), ["R-04"])
        self.assertTrue(findings.readable(doc)[1]["suggested"].startswith("No change was named"))
        self.assertEqual(findings.suggest(doc, {"R-04": "Pick one name.", "R-02": "Ignored: it has an action."}), ["R-04"])
        second = findings.readable(doc)[1]
        self.assertEqual((second["suggested"], second["suggested_by"]), ("Pick one name.", "model"))
        self.assertEqual(findings.needs_suggestion(doc), [])
        self.assertEqual(findings.readable(doc)[0]["suggested"], "Align it with finding 2 and an earlier finding.")

    def test_code_review_places_and_fallback(self):
        first = findings.readable(report())[0]
        self.assertEqual(first["title"], "Discount applied before tax")
        self.assertEqual(first["rest"], "The discount is applied before the tax is added. Totals come out too low.")
        self.assertEqual(first["where"], "in cart.py")
        self.assertEqual(first["refs"][0], {"label": "cart.py", "tip": "src/cart.py, line 42", "target": "path:src/cart.py"})
        self.assertEqual(first["suggested"], "Change it so that this no longer happens: a cart of 100 with a 10% discount "
                                             "and 20% tax totals 108 instead of 110.")


class Dialog(unittest.TestCase):
    def many(self, n, long=False):
        text = ("This sentence is long enough to wrap a few times in a narrow frame. " * (6 if long else 1)).strip()
        return {"source": "aidlc", "stage_name": "Domain Design", "findings": [
            {"id": f"R-{i:02d}", "severity": "Major" if i % 2 else "Minor", "blocking": bool(i % 2),
             "where": f"domain-model.md > Part {i}", "finding": f"Finding number {i} is wrong. {text}",
             "action": f"Do the change {i}. {text}", "title": f"Finding number {i} is wrong."} for i in range(1, n + 1)]}

    def test_markdown_fits_48_rows(self):
        for n, long in ((1, False), (2, True), (5, False), (12, True), (40, False)):
            with self.subTest(n=n, long=long):
                text = findings.dialog_markdown(self.many(n, long))
                self.assertLessEqual(findings.rows(text), findings.DIALOG_ROWS)
                self.assertIn("### 1 · Finding number 1 is wrong.", text)
                self.assertNotRegex(text, r"\bR-\d+\b")
                if n >= 12:
                    self.assertRegex(text, r"…and \d+ more findings\. Pick \*\*Open in form\*\*")

    def test_terminal_fits_12_rows(self):
        for n in (1, 2, 3, 9):
            with self.subTest(n=n):
                lines = findings.dialog_lines(self.many(n, True))
                self.assertLessEqual(sum(findings.rows(line) for line in lines), findings.TERMINAL_ROWS)
                self.assertTrue(lines[1].startswith("1. Finding number 1 is wrong. (blocking)"))
                for line in lines:
                    self.assertNotIn("`", line)
                    self.assertNotIn("**", line)
                if n == 9:
                    self.assertTrue(lines[-1].startswith("…and "))

    def test_brief(self):
        out = findings.dialog(findings.parse_brief(fixture("brief-open.txt"), "domain-design"), "/s/x.findings")
        self.assertEqual(out["findings"], "/s/x.findings")
        self.assertEqual(out["question"]["questions"][0]["header"], "Findings")
        self.assertEqual(out["needs_suggestion"], ["R-03"])
        self.assertIn("**Suggested:** State the winning event.", out["markdown"])
        self.assertIn("- **Blocking** · domain model › Cart aggregate, invariants list", out["markdown"])
        self.assertEqual([i["id"] for i in out["items"]], ["R-02", "R-03"])


class Triage(unittest.TestCase):
    def test_question_text(self):
        self.assertEqual(findings.question_text(3, 1), "3 review findings are open (1 blocking). What should I do with them?")
        self.assertEqual(findings.question_text(2, 0), "2 review findings are open (none blocking). What should I do with them?")
        self.assertEqual(findings.question_text(1, 1), "1 review finding is open (1 blocking). What should I do with them?")

    def test_options(self):
        blocking = findings.triage(findings.parse_brief(fixture("brief-open.txt"), "domain-design"))["questions"][0]
        self.assertEqual(blocking["header"], "Findings")
        self.assertEqual([o["label"] for o in blocking["options"]], ["Fix", "Open in form"])
        doc = {"source": "aidlc", "findings": [{"id": "R-01", "blocking": False}]}
        self.assertEqual([o["label"] for o in findings.triage(doc)["questions"][0]["options"]], ["Fix", "Accept", "Open in form"])


class Answers(unittest.TestCase):
    """The summary of the developer's answers, one fixture per case."""

    def setUp(self):
        self.brief = findings.parse_brief(fixture("brief-open.txt"), "domain-design")

    def test_fix_with_one_item_is_a_line(self):
        doc = findings.parse_review(fixture("review-07.md"), "domain-design")
        self.assertEqual(findings.answer_summary(doc, findings.picks_of(doc, "fix")) + "\n", fixture("answers-fix-one.md"))

    def test_fix_with_several_items_is_a_list(self):
        picks = findings.picks_of(self.brief, answers={"R-02": {"k": ["fix"], "note": ""}, "R-03": {"k": ["fix"], "note": ""}})
        self.assertEqual(findings.answer_summary(self.brief, picks) + "\n", fixture("answers-fix-several.md"))

    def test_accept_has_no_action_items(self):
        picks = findings.picks_of(self.brief, answers={"R-02": {"k": ["accept"]}, "R-03": {"k": ["accept"], "note": ""}})
        self.assertEqual(findings.answer_summary(self.brief, picks) + "\n", fixture("answers-accept.md"))

    def test_reject_without_a_reason_is_refused(self):
        for note in ("", "   ", None):
            with self.assertRaisesRegex(ValueError, "rejects R-02 without a reason"):
                findings.picks_of(self.brief, answers={"R-02": {"k": ["reject"], "note": note}, "R-03": {"k": ["accept"]}})

    def test_reject_with_a_note_quotes_it_as_written(self):
        note = "Checkout and expiry never run on the same cart:\nthe cart is locked while it checks out."
        picks = findings.picks_of(self.brief, answers={"R-02": {"k": ["reject"], "note": note}, "R-03": {"k": ["accept"]}})
        self.assertEqual(findings.answer_summary(self.brief, picks) + "\n", fixture("answers-reject-note.md"))

    def test_a_model_suggestion_is_the_action(self):
        findings.suggest(self.brief, {"R-03": "Use one name for the event. Rename it in the flow text."})
        text = findings.answer_summary(self.brief, findings.picks_of(self.brief, "fix"))
        self.assertTrue(text.endswith("### R-03: Fix\n#### Action items:\n- Use one name for the event.\n- Rename it in the flow text."))

    def test_a_card_without_a_box_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no box for R-03"):
            findings.picks_of(self.brief, answers={"R-02": {"k": ["fix"]}, "R-03": {"k": []}})
        with self.assertRaisesRegex(ValueError, "fix or accept"):
            findings.picks_of(self.brief, "reject")

    def test_answers_are_found_in_a_get_result(self):
        got = {"doc": {"id": "x", "data": {"status": "done", "answers": {"R-02": {"k": ["fix"], "note": "n"}}}}}
        self.assertEqual(findings.answers_in(got), {"R-02": {"k": ["fix"], "note": "n"}})
        self.assertEqual(findings.answers_in(json.dumps(got)), {"R-02": {"k": ["fix"], "note": "n"}})
        self.assertIsNone(findings.answers_in({"status": "done"}))

    def test_cli_form_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, form = os.path.join(tmp, "f.json"), os.path.join(tmp, "form.json")
            findings.dump(path, self.brief)
            findings.dump(form, {"status": "done", "answers": {"R-02": {"k": ["accept"]}, "R-03": {"k": ["accept"]}}})
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(findings.main(["answers", "--findings", path, "--form", form]), 0)
            self.assertEqual(out.getvalue(), fixture("answers-accept.md"))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(findings.main(["answers", "--findings", path]), 1)  # nothing recorded beside it
            self.assertIn("no recorded answer", err.getvalue())


class Board(unittest.TestCase):
    NOW = datetime.datetime(2026, 1, 5, 10, 7, 59, tzinfo=datetime.timezone.utc)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ids_dir = tempfile.TemporaryDirectory()  # the shared id map is kept out of the real ~/.claude
        self.addCleanup(ids_dir.cleanup)
        os.environ["AIDLC_IDS_DIR"] = ids_dir.name
        self.addCleanup(os.environ.pop, "AIDLC_IDS_DIR", None)
        self.doc = findings.parse_brief(fixture("brief-open.txt"), "domain-design")
        self.fid = "260101-demo-shop-domain-design-findings-20260105t1007"

    def made(self):
        findings.board(self.doc, self.fid, "Review findings · Domain Design", self.tmp.name, now=self.NOW)
        return (self.read("forms.json"), self.read("cards", "R-02.json"), self.read("cards", "R-03.json"),
                self.read("writes.json"))

    def read(self, *parts):
        with open(os.path.join(self.tmp.name, *parts), encoding="utf-8") as f:
            return json.load(f)

    def test_form_row(self):
        form = self.made()[0]
        self.assertEqual((form["view"], form["status"], form["createdAt"]), ("board", "open", "2026-01-05T10:07:59Z"))
        self.assertEqual(form["title"], "Review findings · Domain Design")
        self.assertEqual([b["k"] for b in form["boxes"]], ["fix", "accept", "reject"])
        self.assertEqual([b.get("tone") for b in form["boxes"]], ["ink", "muted", "warn"])
        self.assertEqual(form["boxes"][0]["hint"], "Fixed before approval")
        self.assertEqual(form["boxes"][2]["t"], "Reject")
        self.assertEqual(form["boxes"][2]["note"], {"required": True, "label": "Why does this not apply?"})
        self.assertNotIn("note", form["boxes"][0])
        self.assertFalse(any("sink" in b or "group" in b for b in form["boxes"]))  # the page lists cards, no columns
        self.assertEqual([(g["k"], g["t"]) for g in form["groups"]], [("blocking", "Blocking"), ("carried", "Can be carried")])
        self.assertTrue(form["file"].endswith("domain-model.md"))

    def test_cards(self):
        _, blocking, minor, _ = self.made()
        self.assertEqual((blocking["kind"], blocking["n"], minor["n"]), ("card", 1, 2))
        self.assertEqual(blocking["proposed"],
                         {"k": "fix", "why": "Major: it blocks approval until it is fixed or rejected"})
        self.assertEqual(minor["proposed"], {"k": "accept", "why": "Minor: it can be carried as a known risk"})
        self.assertEqual((blocking["group"], blocking["severity"], blocking["blocking"]), ("blocking", "Major", "Blocks approval"))
        self.assertEqual((minor["group"], minor["severity"]), ("carried", "Minor"))
        self.assertNotIn("blocking", minor)
        self.assertEqual(set(blocking["outcomes"]), {"fix", "accept", "reject"})
        self.assertEqual(blocking["from"], "AI review, Major")
        self.assertLessEqual(len(blocking["text"]), 90)
        self.assertEqual(blocking["text"], "The `Cart` rule `checkout | expire` is ambiguous.")

    def test_ctx_blocks_are_separated_by_blank_lines(self):
        _, blocking, minor, _ = self.made()
        blocks = blocking["ctx"].split("\n\n")
        self.assertEqual([b.split(":**")[0] for b in blocks], ["**What's wrong", "**Suggested", "**Where"])
        self.assertEqual([b.split(":**")[0] for b in minor["ctx"].split("\n\n")], ["**What's wrong", "**Suggested", "**Where"])
        self.assertIn("**Suggested:** No change was named by the reviewer", minor["ctx"])
        for b in blocks:
            self.assertNotIn("\n\n", b)
        self.assertNotIn(".md", blocking["ctx"])

    def test_plain_fields_for_the_page(self):
        _, blocking, minor, _ = self.made()
        self.assertTrue(blocking["plain"].startswith("Two events can fire on the same cart"))  # the title is not repeated
        self.assertNotIn("plain", minor)  # its finding is its title
        self.assertEqual(blocking["action"], "State the winning event. Add one line on what happens to reserved stock.")
        self.assertTrue(minor["action"].startswith("No change was named"))
        self.assertEqual(blocking["detail"], "**Where:** domain model › Cart aggregate, invariants list")
        self.assertEqual(blocking["refs"], [{"label": "domain model › Cart aggregate, invariants list",
                                             "tip": "domain-model.md > Cart aggregate, invariants list",
                                             "target": "doc:domain-model.md > Cart aggregate, invariants list"}])
        self.assertTrue(all(not r["target"].startswith("#") for r in minor["refs"]))

    def test_writes_json(self):
        writes = self.made()[3]
        self.assertEqual([(w["op"], w["collection"], w["doc_id"]) for w in writes], [
            ("set", "forms", self.fid),
            ("set", f"forms/{self.fid}/questions", "R-02"),
            ("set", f"forms/{self.fid}/questions", "R-03"),
        ])
        for w in writes:
            self.assertTrue(os.path.isabs(w["file_path"]) and os.path.isfile(w["file_path"]))
            self.assertNotIn("if_version", w)
            self.assertNotIn("data", w)

    def test_code_review_cards(self):
        with open(os.path.join(FIXTURES, "report-findings.json"), encoding="utf-8") as f:
            doc = findings.parse_report(json.load(f))
        findings.board(doc, "code-review-20260105t1007", "Review findings · code review", self.tmp.name, now=self.NOW)
        with open(os.path.join(self.tmp.name, "cards", "F-01.json"), encoding="utf-8") as f:
            card = json.load(f)
        with open(os.path.join(self.tmp.name, "forms.json"), encoding="utf-8") as f:
            form = json.load(f)
        self.assertEqual(card["from"], "Code review, Confirmed, correctness")
        self.assertIn("**What goes wrong:** A cart of 100", card["ctx"])
        self.assertEqual(card["detail"].split("\n\n")[0], "**Where:** in cart.py")
        self.assertEqual(card["refs"][0]["tip"], "src/cart.py, line 42")
        self.assertEqual(card["proposed"]["k"], "fix")
        self.assertEqual((card["group"], card["severity"], card["blocking"]), ("blocking", "Confirmed", "Blocking"))
        self.assertEqual([g["t"] for g in form["groups"]], ["Confirmed", "Possible"])
        self.assertNotIn("stage", form)

    def test_ids_the_cards_mention_get_the_forms_ids_map(self):
        project = os.path.join(self.tmp.name, "project")
        intent = os.path.join(project, "aidlc", "spaces", "default", "intents", "260101-demo-shop")
        stage = os.path.join(intent, "inception", "domain-design")
        os.makedirs(stage)
        for path, text in ((os.path.join(project, "aidlc", "active-space"), "default\n"),
                           (os.path.join(project, "aidlc", "spaces", "default", "intents", "active-intent"), "260101-demo-shop\n"),
                           (os.path.join(intent, "inception", "requirements.md"),
                            "# Requirements\n\n### FR1.4 — Cart totals\nThe cart shows its total with tax.\n"),
                           (os.path.join(stage, "domain-model.md"), "# Domain model\n\n## Cart aggregate\n")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        doc = dict(self.doc, artifact=os.path.relpath(os.path.join(stage, "domain-model.md"), project))
        doc["findings"] = [dict(doc["findings"][0], finding="The rule breaks FR1.4 and FR9.9. " + doc["findings"][0]["finding"])]
        out = os.path.join(self.tmp.name, "board")
        result = findings.board(doc, self.fid, "t", out, now=self.NOW, project_dir=project)
        with open(os.path.join(out, "forms.json"), encoding="utf-8") as f:
            form = json.load(f)
        self.assertEqual(result["ids"], 1)
        self.assertEqual(set(form["ids"]), {"FR1.4"})  # FR9.9 is defined nowhere: the page shows it as not defined
        self.assertEqual((form["ids"]["FR1.4"]["kind"], form["ids"]["FR1.4"]["title"]), ("Functional requirement", "Cart totals"))
        self.assertEqual(form["ids"]["FR1.4"]["doc"], os.path.join("inception", "requirements.md"))

    def test_outside_an_aidlc_project_the_form_has_no_ids(self):
        empty = os.path.join(self.tmp.name, "plain")
        os.makedirs(empty)
        result = findings.board(self.doc, self.fid, "t", os.path.join(self.tmp.name, "b"), now=self.NOW, project_dir=empty)
        self.assertEqual((result["ids"], result["ids_note"]), (0, "no active AI-DLC intent"))
        with open(os.path.join(self.tmp.name, "b", "forms.json"), encoding="utf-8") as f:
            self.assertNotIn("ids", json.load(f))

    def test_no_findings_is_an_error(self):
        with self.assertRaises(ValueError):
            findings.board({"source": "aidlc", "findings": []}, "x", "t", self.tmp.name)

    def test_form_id_pattern(self):
        project = os.path.join(FIXTURES, "project")
        self.assertEqual(findings.form_id(self.doc, project, self.NOW), self.fid)
        self.assertEqual(findings.form_id(dict(self.doc, unit="u1-core"), project, self.NOW),
                         "260101-demo-shop-domain-design-u1-core-findings-20260105t1007")
        self.assertEqual(findings.form_id({"source": "code-review"}, project, self.NOW), "code-review-20260105t1007")
        for fid in (self.fid, findings.form_id({"source": "code-review"}, "", self.NOW)):
            self.assertRegex(fid, r"^[a-z0-9._-]+$")


class Cli(unittest.TestCase):
    def setUp(self):
        ids_dir = tempfile.TemporaryDirectory()  # `board` syncs the shared id map: keep it out of the real ~/.claude
        self.addCleanup(ids_dir.cleanup)
        os.environ["AIDLC_IDS_DIR"] = ids_dir.name
        self.addCleanup(os.environ.pop, "AIDLC_IDS_DIR", None)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = findings.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_parse_summary_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_cli("parse", "--brief", os.path.join(FIXTURES, "brief-open.txt"), "--stage", "domain-design")
            self.assertEqual(code, 0)
            path = os.path.join(tmp, "findings.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
            self.assertIn("2 open, 1 blocking", self.run_cli("summary", "--findings", path)[1])
            self.assertEqual(json.loads(self.run_cli("question", "--findings", path)[1])["questions"][0]["header"], "Findings")
            code, out, _ = self.run_cli("board", "--findings", path, "--project-dir", os.path.join(FIXTURES, "project"),
                                        "--out", os.path.join(tmp, "board"))
            self.assertEqual(code, 0)
            result = json.loads(out)
            self.assertEqual(result["cards"], 2)
            self.assertRegex(result["id"], r"^260101-demo-shop-domain-design-findings-\d{8}t\d{4}$")
            self.assertTrue(os.path.isfile(result["writes"]))

    def test_a_cut_off_brief_builds_no_form_summary_or_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "findings.json")
            code, out, _ = self.run_cli("parse", "--brief", os.path.join(FIXTURES, "brief-cut.txt"), "--stage", "domain-design")
            self.assertEqual(code, 0)
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
            for argv in (("summary", "--findings", path), ("question", "--findings", path),
                         ("board", "--findings", path, "--out", os.path.join(tmp, "board"))):
                with self.subTest(command=argv[0]):
                    code, out, err = self.run_cli(*argv)
                    self.assertEqual((code, out), (1, ""))
                    self.assertIn("cut off", err)
                    self.assertIn("unpiped as the only command", err)
                    self.assertIn("R-02, R-03", err)
            self.assertFalse(os.path.exists(os.path.join(tmp, "board")))

    def test_board_refuses_a_finding_without_text(self):
        doc = findings.parse_brief(fixture("brief-open.txt"), "domain-design")
        doc["findings"][1]["finding"] = "  "
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "cut off.*R-03"):
            findings.board(doc, "x", "t", tmp)

    def test_dialog_and_suggest(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["REVIEW_FINDINGS_DIR"] = tmp
            self.addCleanup(os.environ.pop, "REVIEW_FINDINGS_DIR", None)
            path = findings.session_findings("abc/def")
            self.assertEqual(path, os.path.join(tmp, "abc_def.findings"))
            findings.dump(path, findings.parse_brief(fixture("brief-open.txt"), "domain-design"))
            code, out, _ = self.run_cli("dialog", "--session", "abc/def")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["needs_suggestion"], ["R-03"])
            code, out, _ = self.run_cli("suggest", "--findings", path, "--set", '{"R-03": "Use one name for the event."}')
            self.assertEqual((code, json.loads(out)), (0, {"set": ["R-03"]}))
            out = json.loads(self.run_cli("dialog", "--findings", path)[1])
            self.assertEqual(out["needs_suggestion"], [])
            self.assertIn("**Suggested:** Use one name for the event.", out["markdown"])
            self.assertEqual(self.run_cli("dialog", "--session", "nobody")[0], 1)

    def test_errors_exit_one(self):
        code, _, err = self.run_cli("summary", "--findings", os.path.join(FIXTURES, "brief-open.txt"))
        self.assertEqual(code, 1)
        self.assertIn("findings.py:", err)


if __name__ == "__main__":
    unittest.main()
