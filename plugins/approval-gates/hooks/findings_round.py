"""Review findings at an AI-DLC approval gate, for gate_guard.py (moved here from the review-findings plugin).

There is no Findings question any more. When the review brief is printed with open findings:

 1. The agent fixes the findings it can fix for certain (a clear, local, unambiguous change) and runs the next review
    pass of the stage. A pass that comes back READY settles the round: nothing is left to sort.
 2. Every finding left goes on the gate page as a card (gate_bundle.py --findings), with a suggested action a cheap
    model wrote where the reviewer named none. The developer sorts each card there: Fix, Accept (only when it does not
    block) or Reject with a note. The decision is still the gate's: Approve or Request Changes, in chat.
 3. After the answer the agent reads the page's `findingPicks` and acts on them: a Fix card is Request Changes, named
    in --reason; a Reject card goes on the rejected report as --reject-finding; Accept is carried.

What the round enforces (raised as Refused, which gate_guard turns into its own refusal):
  * the brief is printed unpiped and in full; a cut-off brief holds the gate until it is printed again;
  * a per-stage gate row written while a round is open carries every open finding as a card;
  * the Approval question waits for that page;
  * the approved and rejected reports wait until the picks were read (or the developer typed one answer for all);
    Approve is refused while a card is Fix or a blocking card is not Rejected; Request Changes names every Fix card in
    --reason and every Reject card in --reject-finding.
Answers of Accept or Reject are remembered per project, stage and Unit, so a later brief that lists the same finding
again (the engine keeps it New until approval) does not ask again. The memory ends with the stage's approved report.

The round lives in the guard's session state under "findings"; the saved findings file is
<state dir>/<session>.findings.json. Standard library only.
"""

import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.realpath(os.path.join(HERE, "..", "scripts"))
FINDINGS_PY = os.path.join(SCRIPTS, "findings.py")
GATE_BUNDLE_PY = os.path.join(SCRIPTS, "gate_bundle.py")
LAUNCHERS = {"env", "exec", "nohup", "time", "command", "nice", "sudo"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
OWNER = "findings-owner.json"  # tells the deprecated review-findings plugin that this plugin handles AI-DLC findings
TYPED = {"accept": "accept", "accept all": "accept", "accept them": "accept", "accept them all": "accept",
         "fix": "fix", "fix all": "fix", "fix them": "fix", "fix them all": "fix",
         "fix all findings": "fix", "accept all findings": "accept"}
REMINDERS = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


class Refused(Exception):
    def __init__(self, what, steps, check):
        super().__init__(what)
        self.what, self.steps, self.check = what, steps, check


def library():
    spec = importlib.util.spec_from_file_location("approval_gates_findings", FINDINGS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = library()


# ---------------------------------------------------------------- shell commands

def commands(command):
    """The simple commands of a shell command line as token lists, also inside `bash -c '…'`. Raises ValueError when
    the line cannot be split."""
    lex = shlex.shlex(str(command).replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    out, current = [], []
    for tok in list(lex) + [";"]:
        if tok and set(tok) <= set("&|;()"):
            if current:
                out.append(current)
            current = []
        else:
            current.append(tok)
    for seg in list(out):
        seg = strip_prefix(seg)
        if seg and os.path.basename(seg[0]) in SHELLS and "-c" in seg[1:-1]:
            out += commands(seg[seg.index("-c") + 1])
    return out


def strip_prefix(seg):
    """The command itself: without env assignments and launchers (`env`, `sudo`, `nohup`, …) in front."""
    while seg and (os.path.basename(seg[0]) in LAUNCHERS or re.fullmatch(r"[A-Za-z_]\w*=.*", seg[0], re.S)):
        seg = seg[1:]
        while seg and seg[0].startswith("-") and seg[0] != "-":
            seg = seg[1:]
    return seg


def aidlc_words(seg, words):
    """True when an `aidlc` command carries the words in order (`aidlc engine orchestrate report`)."""
    seg = strip_prefix(seg)
    at = next((i for i, tok in enumerate(seg) if os.path.basename(tok) == "aidlc"), None)
    if at is None:
        return False
    k = 0
    for tok in seg[at + 1:]:
        if k < len(words) and tok == words[k]:
            k += 1
    return k == len(words)


def option(seg, name):
    for i, tok in enumerate(seg):
        if tok == name and i + 1 < len(seg):
            return seg[i + 1]
        if tok.startswith(name + "="):
            return tok[len(name) + 1:]
    return ""


def options(seg, name):
    return [seg[i + 1] for i, tok in enumerate(seg[:-1]) if tok == name] + \
        [tok[len(name) + 1:] for tok in seg if tok.startswith(name + "=")]


def segments(command):
    try:
        return commands(command)
    except ValueError:
        return []


def briefs_of(command):
    return [{"stage": option(seg, "--stage"), "unit": option(seg, "--unit")}
            for seg in segments(command) if aidlc_words(seg, ["engine", "review-brief"])]


def review_logs_of(command):
    return [{"stage": option(seg, "--stage"), "unit": option(seg, "--unit"), "verdict": option(seg, "--verdict").strip().lower()}
            for seg in segments(command) if aidlc_words(seg, ["engine", "log", "review"]) and option(seg, "--verdict")]


def reports_of(command):
    """[{stage, unit, result, reason, rejects}] for each `aidlc engine orchestrate report`; read from the raw text when
    the line cannot be split (an unbalanced quote), rather than let the call through."""
    try:
        segs = commands(command)
    except ValueError:
        if not re.search(r"orchestrate\s+report\b", command):
            return []

        def raw(name):
            found = re.search(rf"--{name}[ =]+[\"']?([^\s\"']+)", command)
            return found.group(1) if found else ""
        reason = re.search(r"--reason[ =]+(.*)$", command, re.S)
        return [{"stage": raw("stage"), "unit": raw("unit"), "result": raw("result").lower(),
                 "reason": reason.group(1) if reason else "", "rejects": re.findall(r"--reject-finding[ =]+(\S+)", command)}]
    return [{"stage": option(seg, "--stage"), "unit": option(seg, "--unit"), "result": option(seg, "--result").lower(),
             "reason": option(seg, "--reason"), "rejects": options(seg, "--reject-finding")}
            for seg in segs if aidlc_words(seg, ["engine", "orchestrate", "report"])]


def cut_segments(command):
    """[True when that review-brief's output is piped or redirected] for each review-brief in the command line."""
    lex = shlex.shlex(str(command).replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex) + [";"]
    except ValueError:
        return [bool(re.search(r"review-brief\b[^;&\n]*\|(?!\|)", str(command)))]
    out, seg = [], []
    for tok in tokens:
        if tok and set(tok) <= set("&|;()"):
            seg_ = strip_prefix(seg)
            if aidlc_words(seg_, ["engine", "review-brief"]):
                redirected = any(t in (">", ">>", ">|", "&>", "&>>") and not (i and seg[i - 1] == "2")
                                 for i, t in enumerate(seg))
                out.append(tok in ("|", "|&") or redirected)
            elif seg_ and os.path.basename(seg_[0]) in SHELLS and "-c" in seg_[1:-1]:
                out += cut_segments(seg_[seg_.index("-c") + 1])
            seg = []
        else:
            seg.append(tok)
    return out


def names_id(text, fid):
    return re.search(r"(?<![A-Za-z0-9-])" + re.escape(fid) + r"(?![0-9])", text or "") is not None


def output_of(response):
    if isinstance(response, dict):
        return "\n".join(str(response.get(k) or "") for k in ("stdout", "output", "text"))
    return response if isinstance(response, str) else json.dumps(response or "")


# ---------------------------------------------------------------- memory of answers

def memory_dir(state_dir):
    return os.path.join(state_dir, "memory")


def memory_path(state_dir, project, stage, unit):
    key = hashlib.sha1("\0".join((os.path.realpath(project), stage or "", unit or "")).encode()).hexdigest()[:20]
    return os.path.join(memory_dir(state_dir), key + ".json")


def fingerprint(finding):
    text = re.sub(r"\s+", " ", str(finding.get("where") or "")).strip().lower() + "\0" + \
        re.sub(r"\s+", " ", str(finding.get("finding") or "")).strip().lower()
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def memory_load(state_dir, project, stage, unit):
    try:
        with open(memory_path(state_dir, project, stage, unit), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    answers = data.get("answers") if isinstance(data, dict) else None
    return answers if isinstance(answers, dict) else {}


def remember(state_dir, project, rnd, picks):
    """Keep the developer's Accept and Reject of this round. Never raises: a lost memory only means asking again."""
    try:
        answers = memory_load(state_dir, project, rnd["stage"], rnd.get("unit"))
        for fid, fp in (rnd.get("prints") or {}).items():
            pick = picks.get(fid)
            if pick and pick["pick"] in ("accept", "reject"):
                answers[fid] = {"fp": fp, "answer": pick["pick"], "note": pick.get("note", "")}
        os.makedirs(memory_dir(state_dir), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=memory_dir(state_dir), prefix="m.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"project": os.path.realpath(project), "stage": rnd["stage"], "unit": rnd.get("unit") or "",
                       "answers": answers}, fh, indent=1)
        os.replace(tmp, memory_path(state_dir, project, rnd["stage"], rnd.get("unit")))
    except OSError:
        pass


def forget(state_dir, project, stage, unit):
    with contextlib.suppress(OSError):
        os.remove(memory_path(state_dir, project, stage, unit))


def split_answered(state_dir, project, doc):
    """Take the findings sorted Accept or Reject earlier (same id, same text and place) out of the document, under
    `carried`."""
    known = memory_load(state_dir, project, doc.get("stage"), doc.get("unit"))
    left, carried = [], []
    for f in doc["findings"]:
        got = known.get(f["id"])
        if isinstance(got, dict) and got.get("answer") in ("accept", "reject") and got.get("fp") == fingerprint(f):
            carried.append({"id": f["id"], "answer": got["answer"], "note": got.get("note", "")})
        else:
            left.append(f)
    doc["findings"], doc["carried"] = left, carried
    return doc


# ---------------------------------------------------------------- the round

def same(rnd, stage, unit):
    return bool(rnd) and rnd.get("stage") == stage and (not unit or (rnd.get("unit") or "") == unit)


def write_owner(state_dir, version):
    """Say, at most once an hour, that this plugin handles AI-DLC findings: the deprecated review-findings plugin
    steps aside while this file is fresh."""
    path = os.path.join(state_dir, OWNER)
    with contextlib.suppress(OSError):
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 3600:
            return
        os.makedirs(state_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=OWNER + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"plugin": "approval-gates", "version": version, "at": time.time()}, fh)
        os.replace(tmp, path)


def brief_steps(stage, unit):
    cmd = f"aidlc engine review-brief review --stage {stage}" + (f" --unit {unit}" if unit else "")
    return [f"Run `{cmd}` (with the same `--why` as before) as the only command: no `| head`, `| tail`, `| grep`, no `>`.",
            "Read the findings the hook lists after it, and go on as its message says."]


def pre_bash(rnd, command):
    """Refuse a piped or redirected review brief, and a closing report the round does not allow yet."""
    if "review-brief" in command and any(cut_segments(command)):
        raise Refused("this command, because it pipes or redirects `aidlc engine review-brief`: the findings are in the "
                      "detail lines after the table, so a cut-off brief holds findings with nothing to decide on.",
                      ["Run the same `aidlc engine review-brief review …` command again with nothing after it: no pipe, no "
                       "redirect, no other command on the line."],
                      "the brief prints in full and the hook answers with the open findings (or says there are none).")
    if not rnd:
        return
    for rep in reports_of(command):
        if rep["result"] not in ("approved", "rejected", "accepted") or not same(rnd, rep["stage"], rep["unit"]):
            continue
        if rnd.get("truncated"):
            raise Refused(f"`report --result {rep['result']}` for {rnd['stage']}, because the review brief was cut off, so "
                          f"its findings ({', '.join(rnd['truncated'])}) were never read.",
                          brief_steps(rnd["stage"], rnd.get("unit")),
                          "the hook records the findings from the full brief.")
        if not rnd.get("page"):
            continue  # a unit-end bundle, or no page yet: the gate's own checks hold the report
        check_report(rnd, rep)


def read_picks_steps(rnd):
    return [f"Read the developer's sort: ArtifactData `action: \"get\"`, `collection: \"gates\"`, `doc_id: "
            f"\"{rnd['page']}\"`, `url: \"{rnd.get('url') or '<the AI-DLC approval gates artifact URL>'}\"`.",
            "Act on `findingPicks` as the hook's answer to that read says, then make the report again."]


def check_report(rnd, rep):
    picks = rnd.get("picks")
    typed = rnd.get("typed")
    if picks is None and not typed:
        raise Refused(f"`report --result {rep['result']}` for {rnd['stage']}, because the developer's sort of the "
                      f"{len(rnd['ids'])} finding card(s) on the gate page was not read since they answered.",
                      read_picks_steps(rnd), "the read returns the row and the report goes through.")
    picks = dict(picks or {})
    for fid in rnd["ids"]:
        if typed and fid not in picks and not (typed == "accept" and fid in rnd["blocking"]):
            picks[fid] = {"pick": typed, "note": ""}
    fixes = [fid for fid in rnd["ids"] if picks.get(fid, {}).get("pick") == "fix"]
    rejects = [fid for fid in rnd["ids"] if picks.get(fid, {}).get("pick") == "reject"]
    if rep["result"] in ("approved", "accepted"):
        if fixes:
            raise Refused(f"`report --result {rep['result']}`, because the developer sorted {', '.join(fixes)} Fix on the "
                          "gate page, and a Fix card is Request Changes.",
                          ["Tell the developer in one line which findings they sorted Fix, and that approving would carry "
                           "them unfixed.",
                           "Ask in chat whether to go with Request Changes; if they still approve, ask them to move those cards "
                           "to Accept or Reject on the page, then read the page again."],
                          "the report that follows their answer goes through.")
        open_blocking = [fid for fid in rnd["blocking"] if picks.get(fid, {}).get("pick") != "reject"]
        if open_blocking:
            raise Refused(f"`report --result {rep['result']}`, because {', '.join(open_blocking)} block(s) approval: a "
                          "blocking finding is never accepted, it is fixed (Request Changes) or rejected with a reason.",
                          ["Tell the developer in one line which findings block, and that they can sort each one Fix or "
                           "Reject (with a note) on the gate page.",
                           "When they say they did, read the page again (ArtifactData get of "
                           f"gates/{rnd['page']}), then report as their sort says."],
                          "every blocking card is Reject, or the report is rejected.")
        return
    reason = rep.get("reason") or ""
    missing = [fid for fid in fixes if not names_id(reason, fid)]
    if missing:
        raise Refused(f"`report --result rejected`, because --reason does not name the Fix finding(s) {', '.join(missing)}.",
                      [f"Add each Fix finding to --reason with its action, as `R-02: <the action on its card>; …`.",
                       "Run the rejected report again with that --reason (keep the developer's notes in it, quoted)."],
                      "the report goes through.")
    rejects_given = " ".join(rep.get("rejects") or [])
    missing = [fid for fid in rejects if f"#{fid}=" not in rejects_given]
    if missing:
        art = rnd.get("artifact") or "<review artifact path>"
        raise Refused(f"`report --result rejected`, because the Reject finding(s) {', '.join(missing)} are not passed as "
                      "--reject-finding.",
                      [f"Add `--reject-finding \"{art}#<id>=<the developer's note>\"` once per Reject finding "
                       f"({', '.join(missing)}).",
                       "Run the rejected report again."],
                      "the report goes through.")


def pre_question(rnd, gate_asked):
    """The Approval question waits while the brief is cut off, and, at a per-stage gate, for a page with the cards."""
    if not rnd or not gate_asked:
        return
    if rnd.get("truncated"):
        raise Refused(f"the Approval question for {rnd['stage']}, because the review brief was cut off, so its findings "
                      f"({', '.join(rnd['truncated'])}) were never read.",
                      brief_steps(rnd["stage"], rnd.get("unit")),
                      "the hook records the findings from the full brief.")
    if rnd["ids"] and not rnd.get("page") and rnd.get("rhythm") != "unit-end":
        raise Refused(f"the Approval question for {rnd['stage']}, because {len(rnd['ids'])} open finding(s) "
                      f"({', '.join(rnd['ids'])}) are not on a gate page published since the brief was printed.",
                      page_steps(rnd), "the hook answers your batch with `gates/<id> is published`, and the question "
                                       "after the link goes through.")


def page_steps(rnd):
    cmd = f'python3 "{GATE_BUNDLE_PY}" --stage {rnd["stage"]}' + (f" --unit {rnd['unit']}" if rnd.get("unit") else "")
    return [f"Make sure every finding has a suggested action: `python3 \"{FINDINGS_PY}\" suggest --findings {rnd['file']} "
            "--set '{}'` prints `still_missing`; for those, have a Haiku subagent (Agent, `model: \"haiku\"`) write one "
            "sentence each and record them with the same command.",
            f"Run `{cmd} --why first --summary-file <your scratchpad folder>/summary.md --findings {rnd['file']} --out "
            "<your scratchpad folder>/gate`.",
            "Send the `writes` array of its writes.json with one ArtifactData batch to the \"AI-DLC approval gates\" artifact.",
            "In ONE response, write the page's link `<artifact url>#<gate id>` as the first line of a text message, then "
            "call AskUserQuestion with the engine's question."]


def check_gate_write(rnd, doc_id, data, matches):
    """A per-stage gate row written while a round is open carries every open finding as a card."""
    if not rnd or rnd.get("truncated") or not rnd["ids"] or rnd.get("rhythm") == "unit-end" or not matches:
        return
    shown = {str(c.get("id")) for c in ((data or {}).get("findings") or {}).get("items") or [] if isinstance(c, dict)}
    missing = [fid for fid in rnd["ids"] if fid not in shown]
    if missing:
        raise Refused(f"the write to gates/{doc_id}, because the open finding(s) {', '.join(missing)} of the review are "
                      "not on the page: the developer sorts every finding you did not fix there.",
                      page_steps(rnd)[:3],
                      f"the hook answers your batch with `gates/<id> is published`, and the page shows {len(rnd['ids'])} "
                      "finding card(s).")


# ---------------------------------------------------------------- what the hook records

def instruction(rnd, doc):
    stage = rnd["stage"] + (f" ({rnd['unit']})" if rnd.get("unit") else "")
    review = f"aidlc engine log review --stage {rnd['stage']}" + (f" --unit {rnd['unit']}" if rnd.get("unit") else "")
    carried = F.answered_line(doc)
    head = (f"{len(rnd['ids'])} review finding(s) of {stage} are open ({len(rnd['blocking'])} blocking): "
            f"{', '.join(rnd['ids'])}. There is no Findings question: do not ask one.")
    if rnd.get("rhythm") == "unit-end":
        where = ("This Unit has the unit-end rhythm: every finding you leave goes on the Unit's bundle page as a row of its "
                 "findings section, with coveredBy saying where it is handled or why not.")
    else:
        where = (f"Every finding you leave goes on the gate page as a card the developer sorts (Fix, Accept, Reject): add "
                 f"`--findings {rnd['file']}` to gate_bundle.py; the hook refuses a gate row without them.")
    return "\n".join([
        head + (f" {carried}; they are not asked again." if carried else ""),
        "1. Fix now every finding you can fix for certain: a clear, local change with one obvious result. Leave anything "
        "that needs a judgment, touches another stage or Unit, or that you are not sure of.",
        f"2. If you fixed any: run the next review pass (`{review} --reviewer <reviewer> --iteration <N+1>`, dispatch the "
        f"reviewer, then `{review} … --iteration <N+1> --verdict <verdict>`), then print the brief again unpiped. READY "
        "settles every finding; otherwise the new brief is the new list. If the engine refuses the edit (review freeze), "
        "leave that finding for the page.",
        f"3. For each finding left with no reviewer action, have a Haiku subagent (Agent, `model: \"haiku\"`) write one "
        f"plain sentence that starts with a verb (\"none\" when nothing needs to change), and record them: `python3 "
        f"\"{FINDINGS_PY}\" suggest --findings {rnd['file']} --set '{{\"<id>\": \"<action>\"}}'`. Short titles the "
        f"same way with `titles` (optional).",
        "4. " + where,
    ])


def on_brief(state_dir, project, session_file, brief, text, rhythm):
    """The round a printed brief opens: (round or None, message)."""
    doc = F.parse_brief(text, brief["stage"])
    doc["unit"] = brief["unit"]
    if not doc["findings"]:
        return None, None
    if F.unfilled(doc):
        rnd = {"stage": doc["stage"], "unit": brief["unit"], "ids": [], "blocking": [], "truncated": F.unfilled(doc),
               "at": time.time()}
        return rnd, (f"the review brief was cut off: {F.CUT_OFF}. The gate waits until it is printed in full.")
    doc = split_answered(state_dir, project, doc)
    if not doc["findings"]:
        return None, (f"{F.answered_line(doc)}: every open finding was sorted in an earlier round, so there is nothing "
                      "new for the page. Go on with the gate; on Approve the engine records them as accepted risks.")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    rnd = {"stage": doc["stage"], "unit": brief["unit"], "ids": [f["id"] for f in doc["findings"]],
           "blocking": [f["id"] for f in doc["findings"] if f.get("blocking")],
           "prints": {f["id"]: fingerprint(f) for f in doc["findings"]}, "artifact": doc.get("artifact", ""),
           "file": session_file, "at": time.time(), "rhythm": rhythm, "page": None, "picks": None, "typed": None}
    return rnd, instruction(rnd, doc)


def post_bash(state, state_dir, project, session_file, command, response, rhythm_of):
    """Record what a finished Bash call means for the round; returns a message or None."""
    rnd = state.get("findings")
    text = output_of(response)
    for rep in reports_of(command):
        if rep["result"] in ("approved", "accepted") and rep["stage"]:
            forget(state_dir, project, rep["stage"], rep["unit"])
        if rnd and rep["result"] in ("approved", "rejected", "accepted") and same(rnd, rep["stage"], rep["unit"]) \
                and '"kind": "error"' not in text:
            state["findings"] = None
            return None
    if "REVIEW_COMPLETED" in text:
        for log in review_logs_of(command):
            if rnd and not rnd.get("truncated") and log["verdict"] == "ready" and same(rnd, log["stage"], log["unit"]):
                state["findings"] = None
                return (f"the {log['stage']} review came back READY, so {', '.join(rnd['ids']) or 'its findings'} are "
                        "settled: nothing goes on the page. Present the gate as usual.")
    for brief in briefs_of(command):
        if "**Stage:**" not in text and "| ID |" not in text:
            continue
        new, note = on_brief(state_dir, project, session_file, brief, text, rhythm_of(brief["stage"], brief["unit"]))
        if rnd and same(rnd, brief["stage"], brief["unit"]) or new:
            state["findings"] = new
        return note
    return None


def on_page(state, doc_id, url):
    rnd = state.get("findings")
    if rnd and rnd["ids"] and not rnd.get("truncated"):
        rnd.update(page=doc_id, url=url, picks=None, typed=None, answered=None)
        return (f"the page holds {len(rnd['ids'])} finding card(s). The developer sorts them there and answers the gate in "
                "chat; after the answer, read gates/" + doc_id + " (ArtifactData get) for `findingPicks`.")
    return None


def sort_in(response):
    """The object that holds `findingPicks` in an ArtifactData get result, wherever the result nests the row (a JSON text
    with words around it too); {} when the row holds none."""
    if isinstance(response, str):
        start = response.find("{")
        try:
            response = json.JSONDecoder().raw_decode(response[start:])[0] if start >= 0 else {}
        except ValueError:
            return {}
    stack = [response]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if "findingPicks" in item:
                return item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return {}


def on_read(state, state_dir, project, doc_id, response):
    """An ArtifactData get of the round's page: record the developer's sort and say what to do with it."""
    rnd = state.get("findings")
    if not rnd or rnd.get("page") != doc_id:
        return None
    picks = F.picks_in(sort_in(response))
    rnd["picks"] = picks
    remember(state_dir, project, rnd, picks)
    by = {k: [fid for fid in rnd["ids"] if picks.get(fid, {}).get("pick") == k] for k in F.PICKS}
    unsorted = [fid for fid in rnd["ids"] if fid not in picks]
    lines = [f"the developer's sort of the findings: Fix {', '.join(by['fix']) or 'none'}; Accept "
             f"{', '.join(by['accept']) or 'none'}; Reject {', '.join(by['reject']) or 'none'}"
             + (f"; not sorted {', '.join(unsorted)}" if unsorted else "") + "."]
    if by["fix"]:
        lines.append("A Fix card is Request Changes: name each in the rejected report's --reason with its action and the "
                     "developer's note.")
    if by["reject"]:
        lines.append(f"Each Reject goes on the rejected report as `--reject-finding \"{rnd.get('artifact') or '<review artifact>'}"
                     "#<id>=<note>\"`; when nothing is fixed it is carried like an Accept, with its note quoted in chat.")
    blocking_open = [fid for fid in rnd["blocking"] if picks.get(fid, {}).get("pick") not in ("fix", "reject")]
    if blocking_open:
        lines.append(f"{', '.join(blocking_open)} block approval and are neither Fix nor Reject: say so in one line and ask "
                     "the developer to sort them before you report approved.")
    return " ".join(lines)


def typed_choice(text):
    text = REMINDERS.sub(" ", str(text or ""))
    return TYPED.get(re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip())


def on_typed(state, text):
    """A message that is just one answer for every card ("fix all", "accept all") is recorded as the sort."""
    rnd = state.get("findings")
    choice = typed_choice(text)
    if not rnd or not rnd.get("page") or not choice:
        return None
    rnd["typed"] = choice
    if choice == "accept" and rnd["blocking"]:
        return (f"the developer typed Accept for every finding. {', '.join(rnd['blocking'])} block(s) approval and cannot be "
                "accepted: the others are recorded as Accept; say in one line that the blocking ones need Fix or Reject.")
    return f"the developer typed {choice.capitalize()} for every finding card; it is recorded as their sort."
