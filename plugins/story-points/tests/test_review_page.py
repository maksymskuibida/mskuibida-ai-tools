"""Render the review form's page under Node and check what a Unit card shows.

points-review.html keeps its render functions between RENDER-START and RENDER-END, free of the DOM,
so a review can be rendered here as plain HTML. Skipped when node is not installed.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "skills" / "review" / "points-review.html"

REVIEW = {"title": "Checkout", "intent": "checkout", "file": "aidlc-docs/checkout/unit-points.csv",
          "scale": [1, 2, 3, 5, 8], "status": "open", "createdAt": "2026-10-25T10:00:00Z", "picks": {}}
UNITS = [
    {"id": "U1", "n": 1, "unit": "U1", "name": "auth", "title": "Guests sign in with email",
     "ctx": "Sends a one-time code. U2 reads the token.", "points": 3, "source": "human"},
    {"id": "U2", "n": 2, "unit": "U2", "name": "api-billing", "title": "Guests pay by card at checkout",
     "ctx": "Covers US-2.1 and **refunds**; waits on U9.", "points": 5, "source": "ai",
     "dependsOn": ["U1", {"unit": "U9", "title": "Fraud screening"}],
     "stories": [{"id": "US-2.1", "title": "Pay by card", "text": "As a guest I pay with a saved card"}],
     "requirements": ["FR-4"]},
    {"id": "U3", "n": 3, "unit": "U3", "name": "emails", "title": "Receipts by email", "points": None, "source": None},
]


def render(state):
    script = PAGE.read_text().split("/* RENDER-START: no DOM below, until RENDER-END */", 1)[1].split("/* RENDER-END */", 1)[0]
    js = script + "\nprocess.stdout.write(PointsView.render(%s, %s, %s));" % (json.dumps(REVIEW), json.dumps(UNITS), json.dumps(state))
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def card(html, unit):
    return re.search(r'<section class="card unit[^"]*" id="u-%s".*?</section>' % unit, html, re.S).group(0)


def text_of(html):
    """The visible text: tags and attribute values (tooltips, link targets) removed."""
    return re.sub(r"<[^>]+>", " ", html)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ReviewPageTest(unittest.TestCase):
    def test_dependency_in_the_review_is_a_live_link_by_title(self):
        c = card(render({}), "U2")
        self.assertIn('href="#u-U1" data-jump="u-U1"', c)
        self.assertIn(">Guests sign in with email</a>", c)

    def test_sources_outside_the_page_are_links_with_their_text_in_the_tooltip(self):
        c = card(render({}), "U2")
        self.assertRegex(c, r'class="ref out" href="#" data-missing="1" data-tip="Unit U9: Fraud screening\.[^"]*">Fraud screening</a>')
        self.assertRegex(c, r'data-tip="Story US-2\.1: Pay by card — As a guest I pay with a saved card\.[^"]*">Pay by card</a>')
        self.assertIn(">FR-4</a>", c)  # a bare id is all that is known

    def test_ids_in_prose_become_links_labelled_by_title(self):
        html = render({})
        prose = re.search(r'<div class="ctx">(.*?)</div>', card(html, "U2"), re.S).group(1)
        self.assertNotRegex(text_of(prose), r"\bU[12]\b|US-2\.1")
        self.assertIn("<strong>refunds</strong>", prose)
        self.assertIn('data-jump="u-U2" data-tip="Unit U2 · api-billing. Jump to its card.">Guests pay by card at checkout</a> reads', card(html, "U1"))

    def test_counts_and_filter_for_units_without_a_developer_estimate(self):
        html = render({"filter": "need"})
        self.assertIn('Needs your estimate<span class="n">2</span>', html)
        self.assertNotIn('id="u-U1"', html)
        self.assertIn('id="u-U2"', html)
        self.assertIn('id="u-U3"', html)
        self.assertIn("1/3 estimated", html)

    def test_a_pick_makes_it_the_developers_estimate(self):
        html = render({"picks": {"U2": {"points": 5, "at": "2026-10-25T10:01:00Z"}}, "unitSave": {"U2": "saved"}})
        c = card(html, "U2")
        self.assertIn('class="pt is-ai picked" data-act="pick" data-unit="U2" data-v="5" aria-pressed="true"', c)
        self.assertIn("it confirms the AI suggestion", c)
        self.assertIn('<span class="ustat saved">Saved</span>', c)
        self.assertIn("2/3 estimated", html)

    def test_failed_save_offers_retry(self):
        html = render({"unitSave": {"U3": "failed"}, "save": {"state": "failed"}})
        self.assertIn('data-act="retry">Retry</button>', card(html, "U3"))
        self.assertIn('<span class="save failed" role="status">', html)

    def test_every_badge_and_id_has_a_tooltip(self):
        html = render({})
        for cls in ("uid", "state", "lc human", "lc ai", "lc none", "chip"):
            for m in re.finditer(r'<(?:span|a) class="%s[^"]*"([^>]*)>' % re.escape(cls), html):
                self.assertIn("data-tip=", m.group(1), cls)

    def test_old_rows_without_the_new_fields_still_render(self):
        old = [{"id": "U1", "n": 1, "unit": "U1", "name": "auth", "title": "Sign in", "points": 13, "source": "ai", "dependsOn": ["U7"]}]
        script = PAGE.read_text().split("/* RENDER-START: no DOM below, until RENDER-END */", 1)[1].split("/* RENDER-END */", 1)[0]
        js = script + "\nprocess.stdout.write(PointsView.render(%s, %s, {}));" % (json.dumps({"scale": [1, 2, 3, 5, 8]}), json.dumps(old))
        html = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
        self.assertIn('class="pt is-ai off"', html)
        self.assertIn("or split the Unit", html)
        self.assertIn('data-missing="1"', html)


if __name__ == "__main__":
    unittest.main()
