"""A copy of the fixture project as an intent with no Units: Construction runs once, its stage folders sit directly
under construction/ (construction/code-generation/code-generation-plan.md)."""

import os
import shutil

FIXTURE_UNIT = "u2-pickup-slots"


def make_no_unit(project, intent="260101-bakery-preorder"):
    construction = os.path.join(project, "aidlc", "spaces", "default", "intents", intent, "construction")
    shutil.rmtree(os.path.join(construction, "u1-core"))
    unit = os.path.join(construction, FIXTURE_UNIT)
    for name in os.listdir(unit):
        shutil.move(os.path.join(unit, name), os.path.join(construction, name))
    os.rmdir(unit)
    return construction
