"""The gate pages link the maps (approval-gates 1.32.0): `maps: [{kind, url, title}]` on a per-stage gate row and on a Unit
bundle, filled from what map_bundle.py published, shown in both pages' header, and allowed by the bundle schema."""

import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import batch1_fixture as b1  # noqa: E402
import map_bundle as mb  # noqa: E402
import validate_bundle  # noqa: E402
from bundle_helpers import NODE, render  # noqa: E402
from test_gate_bundle import FIXTURE, INTENT, Case as BundleCase, fill_judgment  # noqa: E402
from test_validate_bundle import plan_bundle  # noqa: E402

LINKS = [{"kind": "units", "url": "https://claude.ai/artifact/maps1#260101-bakery-preorder-units", "title": "Unit map"},
         {"kind": "components", "url": "https://claude.ai/artifact/maps1#260101-bakery-preorder-components", "title": "Component map"}]


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


class GateRowCarriesTheMaps(BundleCase):
    def test_draft_links_the_published_maps_and_leaves_the_field_out_when_there_are_none(self):
        self.assertNotIn("maps", self.gate_after_draft())
        os.environ["APPROVAL_GATES_DIR"] = os.path.join(self.tmp, "state")
        self.addCleanup(os.environ.pop, "APPROVAL_GATES_DIR", None)
        mb.record_published(self.project, INTENT, "units", f"{INTENT}-units", "https://claude.ai/artifact/maps1", "abc", 1)
        self.assertEqual(self.gate_after_draft()["maps"], [{"kind": "units", "url": f"https://claude.ai/artifact/maps1#{INTENT}-units", "title": "Unit map"}])

    def gate_after_draft(self):
        shutil.rmtree(self.out, ignore_errors=True)
        self.summary("--stage", "user-stories", "--why", "first", "--no-brief")
        return self.gate()

    def test_the_finalized_row_keeps_them(self):
        os.environ["APPROVAL_GATES_DIR"] = os.path.join(self.tmp, "state")
        self.addCleanup(os.environ.pop, "APPROVAL_GATES_DIR", None)
        mb.record_published(self.project, INTENT, "components", f"{INTENT}-components", "https://claude.ai/artifact/maps1", "abc", 1)
        drafted = self.summary("--stage", "user-stories", "--why", "first", "--no-brief")
        fill_judgment(drafted["judgment"])
        code, _out, err = self.run_finalize()
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.out, "row.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["maps"][0]["kind"], "components")


class UnitBundleAndPages(unittest.TestCase):
    def test_the_bundle_schema_allows_maps_and_refuses_a_link_that_is_not_https(self):
        bundle = plan_bundle()
        bundle["maps"] = LINKS
        self.assertEqual(validate_bundle.validate(bundle), [])
        bundle["maps"] = [{"kind": "units", "url": "javascript:alert(1)#x"}]
        self.assertTrue(validate_bundle.validate(bundle))
        bundle["maps"] = [{"kind": "wishes", "url": "https://claude.ai/artifact/m#x"}]
        self.assertTrue(validate_bundle.validate(bundle))

    @unittest.skipUnless(NODE, "needs Node")
    def test_the_unit_page_shows_the_links_in_its_header(self):
        bundle = plan_bundle()
        bundle["maps"] = LINKS
        html = render(bundle)["summary"]
        self.assertIn('data-map-link="units"', html)
        self.assertIn('href="https://claude.ai/artifact/maps1#260101-bakery-preorder-units"', html)
        self.assertIn('rel="noopener"', html)
        self.assertNotIn("maplinks", render(plan_bundle())["summary"])

    @unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
    def test_the_stage_page_shows_them_too(self):
        from test_batch2 import drive  # noqa: E402  (jsdom driver of the per-stage page)
        sample = b1.sample(False)
        sample["row"]["maps"] = LINKS + [{"kind": "units", "url": "http://insecure.example/x#y", "title": "No"}]
        out = drive(sample, "maps", "m")
        self.assertEqual(sorted(out["links"]), ["components:Component map", "units:Unit map"], "an http link is not shown")


if __name__ == "__main__":
    unittest.main()
