"""scripts/diagrams.py: the diagrams a stage's records give, derived the same way every time, offered only when the structure is
really there. Synthetic records only (a made-up bakery).
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import diagrams  # noqa: E402


def doc(key, text, kind="markdown"):
    return {"key": key, "text": text, "kind": kind}


TRACE = json.dumps({"coverage": [{"id": "FR1", "status": "OK", "target": "US1.1"}, {"id": "FR2", "status": "OK", "target": "US1.2"},
                                  {"id": "NFR1", "status": "GAP", "target": "US1.1"}]})


class TestTrace(unittest.TestCase):
    def test_a_traceability_file_becomes_a_ribbon_from_requirements_to_stories(self):
        got = diagrams.build([doc("traceability", TRACE)])
        self.assertEqual([d["kind"] for d in got], ["trace"])
        d = got[0]
        self.assertEqual(d["doc"], "traceability")
        self.assertEqual([c["key"] for c in d["cols"]], ["requirement", "story"])
        self.assertEqual(sorted(n["id"] for n in d["nodes"]), ["FR1", "FR2", "NFR1", "US1.1", "US1.2"])
        self.assertEqual(sorted(map(tuple, d["edges"])), [("FR1", "US1.1"), ("FR2", "US1.2"), ("NFR1", "US1.1")])
        self.assertTrue(next(n for n in d["nodes"] if n["id"] == "NFR1")["ok"] is False, "a coverage row that is not OK marks its box")
        self.assertIn("3 links", d["alt"])

    def test_the_same_records_give_the_same_diagram(self):
        a, b = diagrams.build([doc("traceability", TRACE)]), diagrams.build([doc("traceability", TRACE)])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_a_table_source_column_and_a_step_that_implements_give_more_columns(self):
        rules = "| ID | Rule | Source |\n|---|---|---|\n| SR1 | Slots | FR1 |\n| SR2 | Full | FR2; FR1 |\n"
        plan = "# Plan\n\n1. Slot rules (implements SR1, FR1)\n2. Order endpoint (implements SR2)\n"
        got = diagrams.build([doc("functional-spec", rules), doc("code-generation-plan", plan)])
        d = next(x for x in got if x["kind"] == "trace")
        self.assertEqual([c["key"] for c in d["cols"]], ["requirement", "rule", "step"])
        self.assertIn(["SR1", "Step 1"], d["edges"])
        self.assertIn(["FR1", "SR2"], d["edges"])

    def test_a_yaml_entry_that_implements_is_a_link(self):
        yaml_doc = "```yaml\nrules:\n  - id: BR1.1\n    implements: [FR1]\n  - id: BR1.2\n    implements: [FR1, FR2]\n```\n"
        d = next(x for x in diagrams.build([doc("rules", yaml_doc)]) if x["kind"] == "trace")
        self.assertEqual(sorted(map(tuple, d["edges"])), [("FR1", "BR1.1"), ("FR1", "BR1.2"), ("FR2", "BR1.2")])

    def test_too_little_structure_gives_no_ribbon(self):
        one = json.dumps({"coverage": [{"id": "FR1", "status": "OK", "target": "US1.1"}]})
        self.assertEqual(diagrams.build([doc("traceability", one)]), [])
        same_column = json.dumps({"coverage": [{"id": "FR1", "status": "OK", "target": "FR2"}, {"id": "FR2", "status": "OK", "target": "FR3"}]})
        self.assertEqual(diagrams.build([doc("traceability", same_column)]), [])
        self.assertEqual(diagrams.build([doc("requirements", "# Requirements\n\nFR1 and US1.1 are mentioned in prose only.\n")]), [])

    def test_a_big_trace_is_capped_and_says_so(self):
        rows = [{"id": f"FR{i}", "status": "OK", "target": f"US{i}.1"} for i in range(1, 80)]
        d = diagrams.build([doc("traceability", json.dumps({"coverage": rows}))])[0]
        self.assertEqual(len(d["nodes"]), diagrams.MAX_NODES)
        self.assertEqual(d["more"], 158 - diagrams.MAX_NODES)
        self.assertTrue(all(a in {n["id"] for n in d["nodes"]} and b in {n["id"] for n in d["nodes"]} for a, b in d["edges"]))


class TestLayers(unittest.TestCase):
    COMPONENTS = ("```yaml\ncomponents:\n  - name: OrderPage\n    group: presentation\n    depends_on: [{component: OrderService}]\n"
                  "  - name: OrderService\n    group: application\n    depends_on: [{component: SlotRules}, {component: OrderStore}]\n"
                  "  - name: SlotRules\n    group: domain\n  - name: OrderStore\n    group: data\n```\n")

    def test_components_with_groups_become_layers_in_the_order_of_a_layered_design(self):
        d = diagrams.build([doc("components", self.COMPONENTS)])[0]
        self.assertEqual(d["kind"], "layers")
        self.assertEqual(d["map"], "components")
        self.assertEqual([l["name"] for l in d["layers"]], ["presentation", "application", "domain", "data"])
        self.assertIn(["OrderService", "SlotRules"], d["edges"])

    def test_one_layer_is_not_a_layered_diagram(self):
        one = self.COMPONENTS.replace("presentation", "x").replace("application", "x").replace("domain", "x").replace("data", "x")
        self.assertEqual(diagrams.build([doc("components", one)]), [])

    def test_units_become_build_layers(self):
        units = "```yaml\nunits:\n  - name: U1\n    depends_on: []\n  - name: U2\n    depends_on: [U1]\n  - name: U3\n    depends_on: [U1, U2]\n```\n"
        d = diagrams.build([doc("unit-of-work-dependency", units)])[0]
        self.assertEqual(d["map"], "units")
        self.assertEqual([[i["id"] for i in l["items"]] for l in d["layers"]], [["U1"], ["U2"], ["U3"]])


class TestSequencesAndStates(unittest.TestCase):
    def test_a_from_to_table_about_states_is_a_state_diagram(self):
        t = "| From | To | Event |\n|---|---|---|\n| Draft | Held | picks a slot |\n| Held | Confirmed | pays |\n| Held | Expired | 10 minutes |\n"
        d = diagrams.build([doc("functional-spec", t)])[0]
        self.assertEqual(d["kind"], "states")
        self.assertEqual(d["states"], ["Draft", "Held", "Confirmed", "Expired"])
        self.assertEqual(d["transitions"][1], {"from": "Held", "to": "Confirmed", "text": "pays"})

    def test_a_from_to_table_about_callers_is_a_sequence(self):
        t = "| From | To | Message |\n|---|---|---|\n| Customer | Server | asks for slots |\n| Server | Store | reads the day |\n"
        d = diagrams.build([doc("functional-spec", t)])[0]
        self.assertEqual((d["kind"], d["actors"]), ("sequence", ["Customer", "Server", "Store"]))

    def test_numbered_steps_with_arrows_are_a_sequence_and_a_plain_flow_is_a_chain(self):
        arrows = "## Picking\n\n1. Customer -> Server: asks\n2. Server -> Store: reads\n3. Store -> Server: answers\n"
        self.assertEqual(diagrams.build([doc("spec", arrows)])[0]["kind"], "sequence")
        chain = "## Workflow\n\n1. Open the list.\n2. Pick a slot.\n3. Pay.\n4. Get a mail.\n"
        d = diagrams.build([doc("spec", chain)])[0]
        self.assertEqual((d["kind"], len(d["steps"])), ("steps", 4))

    def test_an_ordinary_numbered_list_stays_text(self):
        self.assertEqual(diagrams.build([doc("notes", "## Things to buy\n\n1. Flour\n2. Salt\n3. Yeast\n4. Water\n")]), [])
        self.assertEqual(diagrams.build([doc("notes", "## Workflow\n\n1. One\n2. Two\n")]), [], "two steps are not a flow")


class TestMermaid(unittest.TestCase):
    FLOW = "```mermaid\nflowchart LR\n  A[Order page] -->|reserve| B(API)\n  B --> C{Slot free?}\n  C -- yes --> D[(Store)]\n  C -.->|no| A\n```\n"

    def test_a_flowchart_is_parsed_into_boxes_and_arrows(self):
        d = diagrams.build([doc("spec", "## Flow\n\n" + self.FLOW)])[0]
        self.assertEqual((d["kind"], d["fence"], d["dir"]), ("flow", 0, "LR"))
        self.assertEqual([n["shape"] for n in d["nodes"]], ["box", "round", "diamond", "cyl"])
        self.assertEqual(d["edges"][0], {"text": "reserve", "from": "A", "to": "B"})
        self.assertEqual(d["edges"][3]["style"], "dashed")
        self.assertEqual(d["title"], "Flow", "the heading above the block names it")

    def test_a_block_is_found_by_the_hash_of_its_source_the_way_the_page_computes_it(self):
        src = self.FLOW.split("\n", 1)[1].rsplit("```", 1)[0]
        d = diagrams.build([doc("spec", self.FLOW)])[0]
        self.assertEqual(d["h"], diagrams.js_hash(diagrams.norm_source(src)))
        self.assertEqual(diagrams.js_hash("a b é 😀"), "11kgqr2.8", "the page's djb2 over UTF-16 units, base 36, then the length")

    def test_sequence_and_state_diagrams_are_drawn_as_such(self):
        seq = "```mermaid\nsequenceDiagram\n  participant C as Customer\n  C->>S: asks\n  S-->>C: answers\n```\n"
        st = "```mermaid\nstateDiagram-v2\n  [*] --> Held\n  Held --> Confirmed: pays\n```\n"
        a, b = diagrams.build([doc("a", seq), doc("b", st)])
        self.assertEqual((a["kind"], a["actors"]), ("sequence", ["Customer", "S"]))
        self.assertEqual((b["kind"], b["states"]), ("states", ["start", "Held", "Confirmed"]))

    def test_what_is_outside_the_drawn_subset_is_a_structured_list_never_raw_source(self):
        pie = "```mermaid\npie\n  title Pets\n  \"Dogs\" : 3\n```\n"
        er = "```mermaid\nerDiagram\n  ORDER ||--o{ LINE : has\n```\n"
        a, b = diagrams.build([doc("a", pie), doc("b", er)])
        self.assertEqual((a["kind"], a["heading"]), ("list", "Shares"))
        self.assertEqual(b["items"][0], {"text": "ORDER relates to LINE", "note": "has"})
        for d in (a, b):
            self.assertNotIn("```", json.dumps(d))

    def test_every_fence_is_kept_in_order_even_beyond_the_cap(self):
        text = "".join(f"## S{i}\n\n```mermaid\nflowchart TD\n  A{i} --> B{i}\n```\n\n" for i in range(7))
        got = diagrams.build([doc("spec", text)])
        self.assertEqual([d["fence"] for d in got], list(range(7)))


class TestCaps(unittest.TestCase):
    def test_reviews_are_not_drawn_and_no_structure_gives_nothing(self):
        self.assertEqual(diagrams.build([doc("review-01", "```mermaid\nflowchart TD\n A-->B\n```", "review")]), [])
        self.assertEqual(diagrams.build([doc("summary", "# Summary\n\nNothing structured here.\n")]), [])
        self.assertEqual(diagrams.build([]), [])


if __name__ == "__main__":
    unittest.main()
