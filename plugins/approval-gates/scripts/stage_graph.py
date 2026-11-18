"""The per-Unit stages of a project, read from its stage graph (`.claude/tools/data/stage-graph.json`).

Upstream's Construction runs five stages per Unit (the four design stages, then Code Generation). A project can add its
own through engine plugins: a stage with `for_each: "unit-of-work"` that runs after Code Generation and is approved
with the Unit is part of the Unit, and the last of them is where the Unit ends. Everything here falls back to upstream's
constants when the graph is absent, unreadable, or marks no stage per-Unit.
"""

import json
import os
import re

DESIGN_STAGES = ("functional-design", "nfr-requirements", "nfr-design", "infrastructure-design")
CODE_STAGE = "code-generation"
DEFAULT_UNIT_STAGES = DESIGN_STAGES + (CODE_STAGE,)
PER_UNIT = "unit-of-work"


def load_graph(project):
    """[stage, ...] in the graph's order, or []."""
    path = os.path.join(project or "", ".claude", "tools", "data", "stage-graph.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [s for s in data if isinstance(s, dict) and isinstance(s.get("slug"), str)] if isinstance(data, list) else []


def _number(stage):
    parts = re.findall(r"\d+", str(stage.get("number") or ""))
    return tuple(int(p) for p in parts) or (10 ** 6,)


def _listed(intent_dir):
    """The stage slugs the intent's aidlc-state.md lists as checklist rows, or None when it has none to read."""
    if not intent_dir:
        return None
    try:
        with open(os.path.join(intent_dir, "aidlc-state.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    rows = set(re.findall(r"(?m)^\s*-\s*\[[^\]]\]\s+([a-z0-9][a-z0-9-]*)\b", text))
    return rows or None


def unit_stages(project, intent_dir=None):
    """The slugs of the per-Unit stages, in stage order. A custom stage the intent's state does not list is left out
    (it does not apply to this intent); upstream's five are always kept when the graph names them."""
    graph = load_graph(project)
    flagged = [s for s in graph if s.get("for_each") == PER_UNIT]
    if not flagged:
        return list(DEFAULT_UNIT_STAGES)
    listed = _listed(intent_dir)
    ordered = sorted(enumerate(flagged), key=lambda p: (_number(p[1]), p[0]))
    out = [s["slug"] for _i, s in ordered if s["slug"] in DEFAULT_UNIT_STAGES or listed is None or s["slug"] in listed]
    return out or list(DEFAULT_UNIT_STAGES)


def last_stage(project, intent_dir=None):
    """The Unit's last stage: the last applicable per-Unit stage. Code Generation when the graph says nothing else."""
    stages = unit_stages(project, intent_dir)
    return stages[-1] if stages else CODE_STAGE


def stages_after_code(project, intent_dir=None):
    """The per-Unit stages that run after Code Generation (the ones approved with the Unit), in order."""
    stages = unit_stages(project, intent_dir)
    return stages[stages.index(CODE_STAGE) + 1:] if CODE_STAGE in stages else []


def stage_name(project, slug):
    for s in load_graph(project):
        if s["slug"] == slug and s.get("name"):
            return s["name"]
    return None
