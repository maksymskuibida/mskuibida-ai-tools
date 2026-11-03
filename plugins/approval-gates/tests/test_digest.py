"""Tests for scripts/digest.py: the per-stage gate's items one by one, what is settled, the trace, and the rule that
nothing the stage leaves uncovered is left unhandled in silence.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import digest  # noqa: E402

REQS = """# Requirements

| ID | Requirement | Source |
|---|---|---|
| FR2.1 | A customer picks a slot of 15 minutes | interview |
| NFR3 | Every text keeps 4.5:1 contrast | checklist |

## Decisions

### ADR-004: Slots live in the bakery's time zone
The server clock decides; FR2.1 depends on it.

- **BR1.2** A full slot refuses a reservation.

```mermaid
flowchart LR
  FR9 --> X
```
"""
IDS = {"FR2.1": {"doc": "inception/requirements-analysis/requirements.md"},
       "NFR3": {"doc": "construction/u2/nfr-requirements/nfr.md"},
       "BR1.2": {"doc": "construction/u2/functional-design/rules.md"}}
STAGE = "construction/u2/functional-design"


def docs(*extra):
    return [{"key": "requirements", "title": "Requirements", "text": REQS}, *extra]


def trace(rows):
    return {"key": "traceability", "title": "Traceability", "text": json.dumps({"coverage": rows})}


class TestItems(unittest.TestCase):
    def test_tables_headings_and_bullets_become_items(self):
        got = {i["id"]: i for i in digest.build(docs(), IDS, STAGE)["items"]}
        self.assertEqual(sorted(got), ["ADR-004", "BR1.2", "FR2.1", "NFR3"])
        self.assertEqual((got["FR2.1"]["kind"], got["FR2.1"]["title"], got["FR2.1"]["body"]),
                         ("requirement", "A customer picks a slot of 15 minutes", "Source: interview"))
        self.assertEqual(got["ADR-004"]["kind"], "decision")
        self.assertEqual(got["ADR-004"]["mentions"], ["FR2.1"], "how a decision relates to the rest")
        self.assertNotIn("FR9", got, "a diagram's text is not an item")

    def test_what_an_earlier_stage_defines_is_settled(self):
        got = {i["id"]: i for i in digest.build(docs(), IDS, STAGE)["items"]}
        self.assertTrue(got["FR2.1"]["settled"] and got["NFR3"]["settled"])
        self.assertNotIn("settled", got["BR1.2"], "defined in this stage")
        self.assertEqual(digest.build(docs(), IDS, STAGE)["settled"], 2)


class TestNothingUnhandledInSilence(unittest.TestCase):
    def test_a_covered_row_links_to_what_covers_it(self):
        out = digest.build(docs(trace([{"id": "BR1.2", "status": "OK", "target": "ADR-004"}])), IDS, STAGE)
        br = next(i for i in out["items"] if i["id"] == "BR1.2")
        self.assertEqual(br["coveredBy"]["link"], {"kind": "doc", "target": "#item-ADR-004", "label": "ADR-004"})
        self.assertEqual(out["trace"], [{"from": "BR1.2", "to": "ADR-004", "ok": True}])

    def test_an_uncovered_row_is_refused_until_linked_or_reasoned(self):
        rows = docs(trace([{"id": "FR7", "status": "MISSING", "target": ""}]))
        with self.assertRaises(ValueError) as caught:
            digest.build(rows, IDS, STAGE)
        self.assertIn("FR7", str(caught.exception))
        given = {"FR7": {"text": "later", "acceptanceReason": {"text": "Moves to U5 with the refunds.", "by": "agent"}}}
        fr7 = next(i for i in digest.build(rows, IDS, STAGE, given)["items"] if i["id"] == "FR7")
        self.assertEqual(fr7["coveredBy"]["acceptanceReason"]["by"], "agent")

    def test_a_requirement_of_a_traced_stage_that_no_row_covers_needs_handling(self):
        rows = [{"key": "spec", "title": "Spec", "text": "| ID | Requirement |\n|---|---|\n| FR8 | Refunds within a day |\n"},
                trace([{"id": "FR2.1", "status": "OK", "target": "spec"}])]
        with self.assertRaises(ValueError) as caught:
            digest.build(rows, {}, STAGE)
        self.assertIn("FR8", str(caught.exception))
        given = {"FR8": {"settled": True, "link": {"kind": "unit", "target": "unit:u5-refunds"}}}
        self.assertTrue(digest.build(rows, {}, STAGE, given)["items"][0]["coveredBy"]["settled"])

    def test_a_developers_reason_quotes_them(self):
        rows = docs(trace([{"id": "FR7", "status": "MISSING"}]))
        with self.assertRaises(ValueError):
            digest.build(rows, IDS, STAGE, {"FR7": {"acceptanceReason": {"text": "Max said so", "by": "developer"}}})

    def test_a_stage_without_traceability_asks_nothing(self):
        self.assertEqual(digest.build(docs(), IDS, STAGE)["trace"], [])


if __name__ == "__main__":
    unittest.main()
