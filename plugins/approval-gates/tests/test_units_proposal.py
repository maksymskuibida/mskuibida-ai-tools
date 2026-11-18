"""The proposed Units map at the Units Generation plan approval (approval-gates 1.40.0).

draft/finalize from a units-proposal.json; the guard at the Approve Plan question; the map built after generation
compared with the proposal (the next revision of the same row). Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map_fixture as fx  # noqa: E402
from test_gate_guard import INTENT, PLUGIN, URL, gate_question  # noqa: E402
from test_maps_guard import MAPS_URL, MapCase  # noqa: E402

sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import map_bundle as mb  # noqa: E402

SCRIPT = os.path.join(PLUGIN, "scripts", "map_bundle.py")
PLAN_LOG = "aidlc engine log decision --stage units-generation --checkpoint plan-approval --value presented"

PROPOSAL = {"schema": mb.PROPOSAL_SCHEMA, "units": [
    {"id": "u1-core", "label": "U1", "name": "Core", "kind": "foundation", "purpose": "Accounts and the shared data model.",
     "stories": ["US1", "US2"], "points": 5},
    {"id": "u2-orders", "label": "U2", "name": "Orders", "kind": "feature", "purpose": "Taking and listing orders.",
     "needs": [{"id": "U1", "why": "orders belong to an account"}], "stories": ["US3"]},
    {"id": "u3-pickup", "label": "U3", "name": "Pickup", "kind": "feature", "purpose": "Choosing a pickup slot.",
     "needs": ["u2-orders", "u9-ghost"], "points": 3}]}


class ProposalCase(MapCase):
    units = False
    components = False

    def write_proposal(self, data=None):
        self.proposal = os.path.join(self.tmp, "units-proposal.json")
        with open(self.proposal, "w", encoding="utf-8") as f:
            json.dump(data or PROPOSAL, f)
        return self.proposal

    def run_map(self, *args):
        done = subprocess.run([sys.executable, SCRIPT, *args, "--project-dir", self.project], capture_output=True, text=True,
                              env=dict(os.environ, APPROVAL_GATES_DIR=self.state), timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def build_proposed(self, data=None, out="proposed"):
        proposal = self.write_proposal(data)
        out = os.path.join(self.tmp, out)
        self.run_map("draft", "--kind", "units", "--proposal", proposal, "--out", out)
        jpath = os.path.join(out, "judgment.json")
        with open(jpath, encoding="utf-8") as f:
            j = json.load(f)
        for e in j["blocks"].values():
            e["summary"] = e["summary"] or "A plain sentence."
            e["group"] = e["group"] or "core"
        j["groups"] = j["groups"] or [{"key": "core", "label": "Core"}]
        for e in j["blocks"].values():
            e["group"] = e["group"] if any(g["key"] == e["group"] for g in j["groups"]) else j["groups"][0]["key"]
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(j, f)
        self.run_map("finalize", "--kind", "units", "--proposal", proposal, "--out", out)
        with open(os.path.join(out, "row.json"), encoding="utf-8") as f:
            return json.load(f), os.path.join(out, "row.json")

    def publish_row(self, path):
        call = {"action": "batch", "url": MAPS_URL, "writes": [{"op": "set", "collection": "maps", "doc_id": f"{INTENT}-units", "file_path": path}]}
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)
        return self.post("ArtifactData", call, {"ok": True})

    def plan_question(self):
        return self.pre("AskUserQuestion", gate_question("Units plan ready. How would you like to proceed?", header="Plan",
                                                         labels=("Approve Plan", "Revise Plan")))

    def open_plan(self):
        self.assertEqual(self.post("Bash", {"command": PLAN_LOG}, {"stdout": ""})[0], 0)
        self.assertEqual(self.state_of()["pending"]["stage"], "units-generation")

    def open_plan_with_page(self):
        self.open_plan()
        self.publish(gate_id=f"{INTENT}-units-generation-20260101T0900")


class TestDraftFromProposal(ProposalCase):
    def test_the_row_is_a_proposed_revision_1_with_waves_and_edges(self):
        row, _ = self.build_proposed()
        self.assertTrue(row["proposed"])
        self.assertEqual((row["basis"], row["revision"], row["id"], row["kind"]), ("plan", 1, f"{INTENT}-units", "units"))
        by = {b["id"]: b for b in row["blocks"]}
        self.assertEqual([by[k]["layer"] for k in ("u1-core", "u2-orders", "u3-pickup")], [1, 2, 3])
        self.assertEqual(by["u2-orders"]["needs"], [{"id": "u1-core", "why": "orders belong to an account"}])
        self.assertEqual(by["u1-core"]["usedBy"], ["u2-orders"])
        self.assertEqual((by["u1-core"]["points"], by["u1-core"]["stories"], by["u1-core"]["status"]), (5, ["US1", "US2"], "planned"))
        self.assertEqual(by["u2-orders"]["summary"], "Taking and listing orders.")  # the purpose starts the judgment
        self.assertEqual([w["points"] for w in row["waves"]], [5, 0, 3])

    def test_a_need_the_proposal_does_not_list_is_warned_about_and_left_out(self):
        rec = mb.proposal_records(PROPOSAL)
        self.assertTrue(any("u9-ghost" in w for w in rec["warnings"]))
        self.assertEqual([n["id"] for b in rec["blocks"] if b["id"] == "u3-pickup" for n in b["needs"]], ["u2-orders"])

    def test_a_bad_proposal_is_refused(self):
        for bad in ({"units": []}, {"schema": mb.PROPOSAL_SCHEMA, "units": [{"id": "Core"}]},
                    {"schema": mb.PROPOSAL_SCHEMA, "units": [{"id": "u1-a"}, {"id": "u1-a"}]}):
            with self.assertRaises(mb.MapError):
                mb.proposal_records(bad)

    def test_the_schema_knows_the_new_fields(self):
        with open(os.path.join(PLUGIN, "contract", "map.schema.json"), encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("proposed", schema["properties"])
        self.assertIn("basis", schema["properties"])
        self.assertIn("proposed", schema["properties"]["previous"]["properties"])


class TestGuardAtThePlanApproval(ProposalCase):
    def test_refused_without_a_proposed_map_then_passes_once_it_is_published_and_linked(self):
        self.open_plan_with_page()
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn("reads the proposed unit map before approving the plan", err)
        self.assertIn("units-proposal.json", err)
        self.assertIn("--proposal", err)
        _row, path = self.build_proposed()
        self.publish_row(path)
        self.said(f"Proposed Units map: {MAPS_URL}#{INTENT}-units")
        self.assertEqual(self.plan_question()[0], 0)

    def test_a_changed_proposal_makes_the_published_map_stale_again(self):
        self.open_plan_with_page()
        _row, path = self.build_proposed()
        self.publish_row(path)
        self.write_proposal(dict(PROPOSAL, units=PROPOSAL["units"][:2]))  # Revise Plan: a Unit leaves
        self.run_map("draft", "--kind", "units", "--proposal", self.proposal, "--out", os.path.join(self.tmp, "again"))
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn("drawn from a different proposal", err)

    def test_the_hook_says_the_published_map_is_proposed(self):
        _row, path = self.build_proposed()
        out = self.publish_row(path)[1]
        self.assertIn("proposed: the plan is not approved yet", self.context(out))

    def test_other_plan_approvals_are_not_held_to_it(self):
        self.assertEqual(self.post("Bash", {"command": "aidlc engine log decision --stage user-stories --checkpoint plan-approval --value presented"}, {"stdout": ""})[0], 0)
        code, _out, err = self.plan_question()
        self.assertNotIn("proposed unit map", err)


class TestStageGateAfterGeneration(MapCase):
    """Units exist now (the records of the bakery fixture): the stage gate needs the real map, and a proposed row is not it."""

    def test_a_proposed_row_never_satisfies_the_stage_gate_and_the_real_map_is_the_next_revision(self):
        proposal = os.path.join(self.tmp, "p.json")
        # the plan proposed the fixture's Units but one fewer: u4-baker-list was added after approval
        rec = mb.records(self.root, "units")
        units = [{"id": b["id"], "label": b["label"], "name": b["title"], "kind": b["kind"], "purpose": "x.", "stories": b["stories"],
                  "needs": [{"id": n["id"], "why": n["why"]} for n in b["needs"]], "points": b["points"]}
                 for b in rec["blocks"] if b["id"] != "u4-baker-list"]
        with open(proposal, "w", encoding="utf-8") as f:
            json.dump({"schema": mb.PROPOSAL_SCHEMA, "units": units}, f)
        out = os.path.join(self.tmp, "prop")
        done = lambda *a: subprocess.run([sys.executable, SCRIPT, *a, "--project-dir", self.project], capture_output=True, text=True,
                                         env=dict(os.environ, APPROVAL_GATES_DIR=self.state), timeout=120)
        self.assertEqual(done("draft", "--kind", "units", "--proposal", proposal, "--out", out).returncode, 0)
        jpath = os.path.join(out, "judgment.json")
        j = json.load(open(jpath))
        j["groups"] = [{"key": "core", "label": "Core"}]
        for e in j["blocks"].values():
            e.update(summary=e["summary"] or "A sentence.", group="core")
        json.dump(j, open(jpath, "w"))
        self.assertEqual(done("finalize", "--kind", "units", "--proposal", proposal, "--out", out).returncode, 0)
        proposed = json.load(open(os.path.join(out, "row.json")))
        self.assertTrue(proposed["proposed"])
        self.assertEqual(mb.plan_freshness(self.project)["fresh"], False)  # nothing published yet
        # publish the proposed row, then the stage gate asks for the real map
        call = {"action": "batch", "url": MAPS_URL, "writes": [{"op": "set", "collection": "maps", "doc_id": f"{INTENT}-units",
                                                                "file_path": os.path.join(out, "row.json")}]}
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)
        self.post("ArtifactData", call, {"ok": True})
        self.assertTrue(mb.plan_freshness(self.project)["fresh"])
        self.gate("units-generation")
        code, _out, err = self.ask("Units Generation complete. How would you like to proceed?")
        self.assertEqual(code, 2)
        self.assertIn("built from records that have changed since", err)
        # the real map: the next revision of the same row, and the page can say what moved since the plan
        final_out = os.path.join(self.tmp, "final")
        self.assertEqual(done("draft", "--kind", "units", "--out", final_out).returncode, 0)
        jf = json.load(open(os.path.join(final_out, "judgment.json")))
        jf["groups"] = [{"key": "core", "label": "Core"}]
        for e in jf["blocks"].values():
            e.update(summary=e["summary"] or "A sentence.", group="core")
        json.dump(jf, open(os.path.join(final_out, "judgment.json"), "w"))
        self.assertEqual(done("finalize", "--kind", "units", "--out", final_out).returncode, 0)
        final = json.load(open(os.path.join(final_out, "row.json")))
        self.assertNotIn("proposed", final)
        self.assertEqual(final["revision"], 2)
        self.assertTrue(final["previous"]["proposed"])
        self.assertEqual(final["previous"]["revision"], 1)
        self.assertNotIn("u4-baker-list", final["previous"]["blocks"])
        self.assertIn("u4-baker-list", {b["id"] for b in final["blocks"]})
        self.assertEqual(mb.changes_of(final)["new"], 1)
        call = {"action": "batch", "url": MAPS_URL, "writes": [{"op": "set", "collection": "maps", "doc_id": f"{INTENT}-units",
                                                                "file_path": os.path.join(final_out, "row.json")}]}
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)
        self.post("ArtifactData", call, {"ok": True})
        self.assertEqual(self.ask("Units Generation complete. How would you like to proceed?")[0], 0)


class TestPageRendersIt(unittest.TestCase):
    def test_the_page_has_the_proposed_state(self):
        with open(os.path.join(PLUGIN, "skills", "approval-gates", "maps.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Proposed — plan not approved yet", page)
        self.assertIn("since the approved plan", page)


if __name__ == "__main__":
    unittest.main()
