#!/usr/bin/env python3
"""Nothing is left unhandled without saying so: the rule every gate page holds its rows to.

A row that is a requirement, an NFR or a reviewer finding says where it is handled, or why it is not:

    coveredBy: {text, settled,
                link?:             {kind, target, label?},
                acceptanceReason?: {text, by: "developer"|"agent", quote?, message?}}

- `link` is where the row is handled. `kind` is `step` (a code-plan step), `doc` (a document section), `code` (a
  source file), `test` (a test file) or `unit` (a later Unit). `target` is `#<anchor>` in the page,
  `path:<repo-relative path>[#<id>]`, `unit:<Unit id>` or an http(s) URL. A linked row is settled: the page shows it
  as passing.
- `acceptanceReason` is why it is not handled. `by: "developer"` quotes the developer's words (`quote`) and names the
  message they are on record in (`message`: a chat answer with its date, a questions file and Q id, a page note);
  `by: "agent"` is the agent's own reason. The page shows the reason next to its row, folded or not.

A row with neither is refused: by `validate_bundle.py` for a unit bundle, by `gate_bundle.py` for a per-stage gate
row. Standard library only; imported by both.
"""

import re

LINK_KINDS = ("step", "doc", "code", "test", "unit")
REASON_BY = ("developer", "agent")
LINK_TARGET = re.compile(r"^(?:#[A-Za-z0-9._-]+|path:\S+|unit:[A-Za-z0-9._-]+|https?://\S+)$")
REQUIREMENT_ID = re.compile(r"^(?:[A-Z]{1,3}\s+)?(?:FR|NFR|US|AC|BR|REQ)-?\d")  # `FR1.2`, `NFR3`, `FD R-06` is a finding
MUST_HANDLE_KINDS = ("findings",)  # every row of these sections is a reviewer finding


def must_be_handled(section_kind, row):
    """True for a reviewer finding (a row of a findings section) and for a requirement or NFR row (its id is one)."""
    return section_kind in MUST_HANDLE_KINDS or bool(REQUIREMENT_ID.match(str(row.get("id", ""))))


def linked(covered):
    link = (covered or {}).get("link")
    return isinstance(link, dict) and bool(str(link.get("target", "")).strip())


def reasoned(covered):
    reason = (covered or {}).get("acceptanceReason")
    return isinstance(reason, dict) and bool(str(reason.get("text", "")).strip())


def problems(where, covered, required=True):
    """One line per way `covered` breaks the rule. `required` is False for a row that may have no coveredBy at all."""
    if not covered:
        return [f"{where}: link it to where it is handled (coveredBy.link: a plan step, a document section, a code or "
                "test file, or a later Unit), or write why not (coveredBy.acceptanceReason)"] if required else []
    out = []
    link, reason = covered.get("link"), covered.get("acceptanceReason")
    if not linked(covered) and not reasoned(covered):
        out.append(f"{where}: \"{covered.get('text', '')}\" links nowhere and gives no reason: add coveredBy.link (a plan "
                   "step, a document section, a code or test file, or a later Unit) or coveredBy.acceptanceReason")
    if link is not None:
        if not isinstance(link, dict) or link.get("kind") not in LINK_KINDS:
            out.append(f"{where}: coveredBy.link.kind is one of {', '.join(LINK_KINDS)}")
        elif not LINK_TARGET.match(str(link.get("target", ""))):
            out.append(f"{where}: coveredBy.link.target is #<anchor>, path:<file>[#<id>], unit:<Unit> or a URL, "
                       f"not {link.get('target')!r}")
        elif covered.get("settled") is not True:
            out.append(f"{where}: a linked row is handled, so coveredBy.settled is true")
    if reason is not None:
        if not isinstance(reason, dict) or reason.get("by") not in REASON_BY:
            out.append(f"{where}: coveredBy.acceptanceReason.by is \"developer\" or \"agent\"")
        elif reason.get("by") == "developer" and not (str(reason.get("quote", "")).strip()
                                                       and str(reason.get("message", "")).strip()):
            out.append(f"{where}: a developer's reason quotes their words (acceptanceReason.quote) and names the message "
                       "they are on record in (acceptanceReason.message)")
    return out


def rows_problems(sections):
    """Problems of every row of [{kind, key, rows}] that must be handled, or carries a coveredBy."""
    out = []
    for s in sections or []:
        for r in s.get("rows") or []:
            required = must_be_handled(s.get("kind"), r)
            if required or r.get("coveredBy"):
                out += problems(f"row {r.get('id')}", r.get("coveredBy"), required)
    return out
