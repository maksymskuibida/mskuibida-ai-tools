"""Shared by the bundle tests: a stand-in for the agent's part of a draft, and the page's renderer run under Node."""

import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
SCRIPTS = os.path.join(PLUGIN, "scripts")
PAGE = os.path.join(PLUGIN, "skills", "approval-gates", "unit-gate.html")
NODE = shutil.which("node")

RENDER = r"""
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const src = html.split("/* RENDER-START")[1].split("/* RENDER-END */")[0];
const ctx = { module: {} }; vm.createContext(ctx); vm.runInContext("/*" + src, ctx);
const G = ctx.module.exports;
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [name, state] of Object.entries(input.states)) out[name] = G.render(input.bundle, state);
out.order = G.order(input.bundle);
out.list = G.listHtml([{ id: input.bundle.id, bundle: input.bundle, page: input.bundle.page, title: input.bundle.header.title, createdAt: input.bundle.createdAt, status: "open", intent: input.bundle.header.intent, unit: input.bundle.header.unit }]);
process.stdout.write(JSON.stringify(out));
"""


def render(bundle, states=None):
    """{state name: html, 'order': [...], 'list': html} from the page's own render functions."""
    states = states or {"summary": {}}
    done = subprocess.run([NODE, "-e", RENDER, PAGE], input=json.dumps({"bundle": bundle, "states": states}),
                          capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError("the page's renderer failed under Node:\n" + done.stderr)
    return json.loads(done.stdout)


def agent_pass(bundle):
    """What the agent does to a draft, reduced to the minimum the contract asks: a label on every row, look first on one
    high row, and a row in every section the records cannot fill."""
    first = True
    for s in bundle["sections"]:
        for r in s["rows"]:
            if not r.get("label"):
                r["label"] = "core" if s["kind"] == "built" else "medium"
        if s["kind"] == "assumptions" and s["rows"] and first:
            s["rows"][0].update(label="high", lookFirst=True)
            first = False
        if not s["rows"] and s["kind"] in ("narrows", "visible", "tests"):
            s["rows"].append({"id": f"{s['key'][0].upper()}-1", "title": f"One {s['kind']} row", "label": "low",
                              "body": "Written by the agent.", "refs": []})
    if not bundle["header"]["lede"]:
        bundle["header"]["lede"] = "What the Unit does."
    return bundle
