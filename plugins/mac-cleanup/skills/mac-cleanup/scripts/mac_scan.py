#!/usr/bin/env python3
"""Account for a Mac's whole disk, build the rows of the "Mac cleanup" page, and remove what was picked.

  mac_scan.py walk --out DIR [--since YYYY-MM-DD] [--depth 9]
      One pass over the Data volume. Reads the APFS container (diskutil), walks the volume with du,
      lists the files written since --since (default: 30 days ago) and keeps every error du hit.
      Writes DIR/volumes.json, DIR/walk.tsv, DIR/walk.err, DIR/recent.tsv. Takes a few minutes.

  mac_scan.py build --dir DIR --out OUT [--agents DIR/agents] [--worktree-plan plan.json]
                    [--live-paths FILE] [--summary-file summary.md] [--host NAME]
      Merges the walk, the investigators' findings (one JSON file per area, contract in
      references/investigators.md) and scan_worktrees.py's plan into one scan. Writes OUT/scan.json
      (everything, for the agent) and OUT/writes.json (+ writes-<n>.json when it does not fit one
      batch): the ArtifactData batch that creates the page's rows. Prints one JSON line:
      {"id", "writes", "batches", "items", "suggestedBytes", "unverifiedBytes"}.

  mac_scan.py remove --scan OUT/scan.json --picks picks.json [--live-paths FILE]
                     [--quiet-minutes 30] [--execute]
      Re-checks every item picked "remove" against the disk as it is now, then (only with --execute)
      deletes the plain folders and files that pass. Worktrees, tool commands and manual steps are
      never run here: they are printed for the agent, which runs them through their own gates.
      Dry run by default. Exit codes: 0 done, 1 a removal failed, 2 refused to start.

Python 3 stdlib only. Nothing here writes outside --out / --dir except `remove --execute`.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time

DATA = "/System/Volumes/Data"
GB = 1000 ** 3                   # decimal, as Finder and System Settings count
ROW_LIMIT = 200 * 1024           # a db document holds 256 KiB; keep a margin for the page's own fields
MAX_BATCH_WRITES = 50
MAX_BATCH_BYTES = 1024 * 1024
HOTSPOT_BYTES = 2 * GB         # a folder this big that no investigator explained gets its own row

# The page's sections, in order. Every item's category maps to one.
GROUPS = [
    ("worktrees", "Git worktrees", "Extra checkouts agents made. Removed only through the worktree gates: unpushed work and live sessions are re-checked at the moment of removal."),
    ("dev-build", "Build output and dependencies", "node_modules, Swift .build, .venv, dist and the like inside your projects. They come back with an install or a build."),
    ("simulators", "Simulators and emulators", "iOS simulator runtimes and devices, Xcode device support, Android images and virtual devices."),
    ("containers", "Containers, VMs and AI models", "Docker's disk image, virtual machines, local models and the Claude app's sandbox images."),
    ("caches", "Package caches and toolchains", "Download caches of npm, pip, Gradle, Homebrew and friends, and old toolchain versions."),
    ("app-caches", "App caches", "Caches apps rebuild on their own."),
    ("app-data", "App data", "What apps keep for you: settings, libraries, game saves, chat media."),
    ("repos", "Code projects", "Whole checkouts. Listed so you can see their size; remove one only if you are done with it."),
    ("files", "Your files", "Downloads, documents, media and backups. Only you can say whether they can go."),
    ("system", "macOS and system", "Space macOS manages: system volumes, swap, snapshots, prepared updates, logs."),
    ("other", "Everything else", "Apps, media and big folders that fit no group above; rows marked \"A large folder no investigator described\" were found by the walk alone. Look before you pick."),
]
CATEGORY_GROUP = {
    "worktrees": "worktrees", "dev-build": "dev-build", "simulators": "simulators",
    "containers-vms": "containers", "ai-models": "containers", "package-caches": "caches", "dev-tools": "caches",
    "app-caches": "app-caches", "app-data": "app-data", "repos": "repos", "personal-files": "files",
    "backups": "files", "system": "system", "logs": "system", "other": "other",
}
# Where a plain folder may be deleted from by `remove`. Anything else is printed as a manual step.
REMOVABLE_ROOTS = ("/Users/", "/private/tmp/", "/private/var/folders/", "/Library/Caches/",
                   "/Library/Developer/CoreSimulator/Caches/", "/opt/homebrew/var/log/")
NEVER = ("/System", "/usr", "/bin", "/sbin", "/private/var/db", "/private/var/vm", "/Applications")


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def item_id(path):
    return hashlib.sha1(path.encode()).hexdigest()[:12]


def strip_data(p):
    return p[len(DATA):] if p.startswith(DATA + "/") else p


def under(child, parent):
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def write_json(path, value):
    with open(path, "w") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------- walk

def apfs_volumes():
    """The APFS container that holds the Data volume: its size, free space and every volume in it."""
    try:
        raw = subprocess.run(["diskutil", "apfs", "list", "-plist"], capture_output=True, timeout=60).stdout
        tree = plistlib.loads(raw)
    except Exception as exc:  # not a Mac, or diskutil refused
        return {"error": f"diskutil apfs list failed: {exc}"}
    for c in tree.get("Containers", []):
        vols = c.get("Volumes", [])
        if not any("Data" in (v.get("Roles") or []) for v in vols):
            continue
        return {
            "container": c.get("ContainerReference"),
            "size": c.get("CapacityCeiling"),
            "free": c.get("CapacityFree"),
            "volumes": [{"name": v.get("Name"), "role": (v.get("Roles") or ["None"])[0],
                         "bytes": v.get("CapacityInUse", 0), "device": v.get("DeviceIdentifier")} for v in vols],
        }
    return {"error": "no APFS container with a Data volume"}


def cmd_walk(args):
    out = args.out
    os.makedirs(out, exist_ok=True)
    since = args.since or (dt.date.today() - dt.timedelta(days=30)).isoformat()
    vols = apfs_volumes()
    vols["since"] = since
    vols["walkedAt"] = now_iso()
    vols["host"] = socket.gethostname().split(".")[0]
    t0 = time.time()
    with open(os.path.join(out, "walk.tsv"), "w") as fo, open(os.path.join(out, "walk.err"), "w") as fe:
        subprocess.run(["du", "-x", "-k", "-d", str(args.depth), DATA], stdout=fo, stderr=fe, cwd="/")
    vols["walkSeconds"] = round(time.time() - t0)
    # Files written since --since, measured on disk (512-byte blocks), so sparse disk images count as what they use.
    with open(os.path.join(out, "recent.tsv"), "w") as fo:
        subprocess.run(f"find {DATA} -xdev -type f -newermt {since} -size +1M -exec stat -f '%b%t%N' {{}} + 2>/dev/null",
                       shell=True, stdout=fo, cwd="/")
    write_json(os.path.join(out, "volumes.json"), vols)
    print(json.dumps({"dir": out, "walkSeconds": vols["walkSeconds"], "since": since}))
    return 0


# ---------------------------------------------------------------------------- build

def read_walk(path):
    sizes = {}
    with open(path) as fh:
        for line in fh:
            kb, _, p = line.rstrip("\n").partition("\t")
            if kb.isdigit():
                sizes[p] = int(kb) * 1024
    return sizes


def denied_areas(err_path):
    """Folders du could not read, rolled up to the folder a person would recognise."""
    counts = {}
    if not os.path.exists(err_path):
        return []
    for line in open(err_path):
        m = re.match(r"du: (.*): (Operation not permitted|Permission denied)$", line.strip())
        if not m:
            continue
        p = strip_data(m.group(1))
        parts = p.split("/")
        if p.startswith("/Users/") and len(parts) > 3 and parts[3] == "Library":
            key = "/".join(parts[:5])          # /Users/<u>/Library/<area>
        elif p.startswith("/Users/"):
            key = "/".join(parts[:5])
        elif p.startswith("/private/var/folders/"):
            key = "/private/var/folders (other users' and system temp folders)"
        else:
            key = "/".join(parts[:4])
        reason = "privacy" if m.group(2) == "Operation not permitted" else "owner"
        c = counts.setdefault(key, {"path": key, "count": 0, "why": reason})
        c["count"] += 1
    return sorted(counts.values(), key=lambda c: -c["count"])


def bar_segments(vols, sizes, user_home):
    """The capacity bar: macOS volumes, swap, the Data volume by area, what du could not see, and free space."""
    def size(p):
        return sizes.get(DATA + p, 0)

    home = DATA + user_home
    personal = {"Downloads", "Documents", "Desktop", "Movies", "Music", "Pictures"}
    code = dots = files = 0
    for p, b in sizes.items():
        if os.path.dirname(p) != home:
            continue
        name = os.path.basename(p)
        if name == "Library":
            continue
        if name.startswith("."):
            dots += b
        elif name in personal or name.startswith("Creative Cloud Files"):
            files += b
        else:
            code += b
    segs = []
    by_role = {v["role"]: v["bytes"] for v in vols.get("volumes", [])}
    data_bytes = by_role.get("Data", 0)
    macos = sum(b for r, b in by_role.items() if r in ("System", "Preboot", "Recovery", "Update", "xART", "Hardware"))
    segs.append({"key": "macos", "label": "macOS volumes", "bytes": macos, "tone": "sys"})
    segs.append({"key": "swap", "label": "Swap", "bytes": by_role.get("VM", 0), "tone": "sys"})
    segs.append({"key": "library", "label": "Your Library (apps' data and caches)", "bytes": size(user_home + "/Library"), "tone": "c1"})
    segs.append({"key": "code", "label": "Code and project folders", "bytes": code, "tone": "c2"})
    segs.append({"key": "dots", "label": "Tool folders in your home (.npm, .gradle, …)", "bytes": dots, "tone": "c3"})
    segs.append({"key": "files", "label": "Your files", "bytes": files, "tone": "c4"})
    segs.append({"key": "apps", "label": "Applications", "bytes": size("/Applications"), "tone": "c5"})
    segs.append({"key": "shared", "label": "Shared Library and macOS assets", "bytes": size("/Library") + size("/System"), "tone": "c6"})
    segs.append({"key": "var", "label": "System temp and data (/private)", "bytes": size("/private"), "tone": "c6"})
    segs.append({"key": "brew", "label": "Homebrew and /usr/local", "bytes": size("/opt") + size("/usr"), "tone": "c6"})
    accounted = sizes.get(DATA, 0)
    other_data = accounted - sum(s["bytes"] for s in segs[2:])
    if other_data > 0:
        segs.append({"key": "rest", "label": "Elsewhere on the Data volume", "bytes": other_data, "tone": "c6"})
    segs.append({"key": "unverified", "label": "Could not verify", "bytes": max(0, data_bytes - accounted), "tone": "unv"})
    other_vols = sum(b for r, b in by_role.items() if r not in ("System", "Preboot", "Recovery", "Update", "xART", "Hardware", "VM", "Data"))
    if other_vols:
        segs.append({"key": "othervols", "label": "Other volumes in the container", "bytes": other_vols, "tone": "sys"})
    segs.append({"key": "free", "label": "Free", "bytes": vols.get("free") or 0, "tone": "free"})
    return [s for s in segs if s["bytes"] > 0]


def recent_growth(path, limit=12):
    """What was written since the walk's --since date, rolled up to folders a person would recognise."""
    agg, total = {}, 0
    if not os.path.exists(path):
        return {"bytes": 0, "top": []}
    for line in open(path):
        b, _, p = line.rstrip("\n").partition("\t")
        if not b.isdigit():
            continue
        b = int(b) * 512
        total += b
        p = strip_data(p)
        m = re.match(r"(.*/\.claude/worktrees/[^/]+)", p)
        parts = p.split("/")
        if m:
            key = m.group(1)
        elif p.startswith("/Users/") and len(parts) > 4 and parts[3] == "Library":
            key = "/".join(parts[:6])
        elif p.startswith("/Users/"):
            key = "/".join(parts[:5]) if len(parts) > 5 else "/".join(parts[:4])
        elif p.startswith("/System/Library/AssetsV2/"):
            key = "/".join(parts[:5])
        else:
            key = "/".join(parts[:5])
        agg[key] = agg.get(key, 0) + b
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:limit]
    return {"bytes": total, "top": [{"path": k, "bytes": v} for k, v in top]}


def kind_of(item):
    if item.get("category") == "worktrees":
        return "worktree"
    if item.get("virtual"):
        return item.get("kind") or "command"
    action = (item.get("action") or "").strip()
    m = re.match(r"^rm -rf ['\"]?(.+?)['\"]?$", action)
    if m and os.path.normpath(os.path.expanduser(m.group(1))) == os.path.normpath(item["path"]):
        return "path"
    if not action or re.search(r"(Settings|Finder|in the app|›|>)", action) and not re.match(r"^[a-z./~]", action):
        return "manual"
    return "command"


def load_agents(folder):
    items, denied, summaries, extra = [], [], [], {}
    if not folder or not os.path.isdir(folder):
        return items, denied, summaries, extra
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            doc = json.load(open(os.path.join(folder, name)))
        except Exception as exc:
            print(f"mac_scan: skipped {name}: {exc}", file=sys.stderr)
            continue
        # Only an investigator's own report counts: <area>.json whose "area" is that name. Investigators leave
        # working files next to it (drafts, raw listings), which must not add rows.
        if not isinstance(doc, dict) or doc.get("area") != name[:-5] or not isinstance(doc.get("items"), list):
            continue
        area = doc["area"]
        for it in doc.get("items") or []:
            if not isinstance(it, dict) or not it.get("path") or not isinstance(it.get("bytes"), (int, float)):
                continue
            it = dict(it)
            it["path"] = strip_data(os.path.expanduser(str(it["path"])))
            it["bytes"] = int(it["bytes"])
            it["source"] = area
            items.append(it)
        denied += [strip_data(str(d)) for d in doc.get("denied") or []]
        if doc.get("summary"):
            summaries.append({"area": area, "text": doc["summary"]})
        for k in ("volumes", "snapshots", "purgeable_bytes"):
            if k in doc:
                extra[k] = doc[k]
    return items, denied, summaries, extra


def worktree_items(plan_path):
    if not plan_path or not os.path.exists(plan_path):
        return []
    plan = json.load(open(plan_path))
    rows = plan.get("worktrees") if isinstance(plan, dict) else plan
    out = []
    for w in rows or []:
        verdict = w.get("verdict")
        size = int(w.get("size_kb") or 0) * 1024
        if verdict in ("main", "stale") or w.get("is_main") or not size:
            continue
        reasons = w.get("reasons") or []
        out.append({
            "path": w["path"], "bytes": size,
            "what": "Git worktree" + (f" on {w['branch']}" if w.get("branch") else ""),
            "category": "worktrees",
            "risk": {"safe": "safe", "review": "review"}.get(verdict, "keep"),
            "regenerates": "Commits stay in the repository; `git worktree add` recreates the checkout. Ignored files in it are lost.",
            "action": "remove_worktrees.py (re-verified at removal)",
            "notes": "; ".join(reasons[:4]), "source": "worktrees", "verdict": verdict,
        })
    return out


# Things investigators report that are not files (a Docker image, a volume inside Docker's disk image) are given a
# path under what holds them, so a folder and what is inside it are never counted twice.
VIRTUAL_PARENTS = {"docker-": "~/Library/Containers/com.docker.docker"}


def place_virtual(items):
    for it in items:
        p = it["path"]
        # macOS's own volumes (the sealed system, Preboot, swap, Recovery) are not folders on the Data volume:
        # they explain the bar's "macOS volumes" and "Swap", and nothing is ever inside them for this tool.
        if p == "/" or p.startswith(("/System/Volumes/", "/Volumes/")):
            it["label"] = p
            it["path"] = "/virtual/volumes/" + (p.strip("/").replace("/", "∕") or "system")
            it["virtual"] = True
            it["kind"] = "manual"
            continue
        if p.startswith("/"):
            continue
        parent = next((os.path.expanduser(v) for k, v in VIRTUAL_PARENTS.items() if p.startswith(k)), None)
        it["label"] = p
        it["path"] = (parent or "/virtual") + "/" + p.replace("/", "∕")
        it["virtual"] = True
    return items


def backed_by_walk(items, sizes):
    """Leave out sizes the walk contradicts: an item bigger than the nearest folder the walk measured around it was
    estimated, not measured (a mounted image's contents, an apparent size of a sparse file). Returns (kept, dropped)."""
    kept, dropped = [], []
    for it in items:
        if it.get("virtual") or it.get("category") == "worktrees":
            kept.append(it)
            continue
        p = DATA + it["path"]
        while p not in sizes and p.startswith(DATA + "/"):
            p = os.path.dirname(p)
        around = sizes.get(p)
        if around is not None and it["bytes"] > around * 1.1 + 50 * 1024 ** 2:
            dropped.append(dict(it, walkBytes=around))
        else:
            kept.append(it)
    return kept, dropped


def dedupe(items):
    """One row per thing. Two investigators reporting the same path with the same action is one thing: keep the
    report that says more. The same path with different actions is several things inside it (a project's
    node_modules and its .venv, summed): each becomes its own child of the path, so a sum never counts it twice."""
    best = {}
    for it in items:
        p = it["path"].rstrip("/") or "/"
        it["path"] = p
        key = (p, (it.get("action") or "").strip())
        cur = best.get(key)
        score = len(json.dumps(it)) + (10 ** 6 if it.get("category") == "worktrees" else 0)
        if cur is None or score > cur[0]:
            best[key] = (score, it)
    kept = [v[1] for v in best.values()]
    by_path = {}
    for it in kept:
        by_path.setdefault(it["path"], []).append(it)
    for p, same in by_path.items():
        if len(same) < 2:
            continue
        # the whole thing (a project kept as is) stays at the path; what is inside it moves one level down
        same.sort(key=lambda it: (it.get("risk") != "keep", -it["bytes"]))
        anchor = same[0]
        for it in same[1:]:
            # two investigators describing the same thing in their own words: one row is enough. A project kept as a
            # whole and its build output can be nearly the same size; they differ in risk, so both stay.
            if it.get("risk") == anchor.get("risk") and abs(it["bytes"] - anchor["bytes"]) <= 0.03 * anchor["bytes"]:
                kept.remove(it)
                continue
            name = re.sub(r"\s+", " ", str(it.get("what") or it.get("category") or "part"))[:48].replace("/", "∕")
            it["label"] = p
            it["path"] = f"{p}/⟨{name}⟩"
            it["virtual"] = True
    return kept


def hotspots(sizes, items, user_home):
    """The deepest folders of HOTSPOT_BYTES or more that no reported item explains."""
    big = {strip_data(p): b for p, b in sizes.items() if b >= HOTSPOT_BYTES and p.startswith(DATA + "/")}
    covered = [it["path"] for it in items]
    found = []
    for p in sorted(big, key=len, reverse=True):
        if p.count("/") < 3:
            continue
        if any(under(c, p) or under(p, c) for c in covered + found):
            continue
        found.append(p)
    out = []
    for p in found:
        out.append({"path": p, "bytes": big[p], "what": "A large folder no investigator described",
                    "category": "other", "risk": "review", "regenerates": "Unknown: look at it before picking.",
                    "action": "", "notes": "Found by the disk walk.", "source": "walk"})
    return out


def top_level(items):
    """Items not inside another item of the list (so sums do not count a folder twice)."""
    paths = sorted({it["path"] for it in items}, key=len)
    tops = []
    for p in paths:
        if not any(under(p, t) for t in tops):
            tops.append(p)
    keep = set(tops)
    return [it for it in items if it["path"] in keep]


def cmd_build(args):
    folder = args.dir
    vols = json.load(open(os.path.join(folder, "volumes.json")))
    sizes = read_walk(os.path.join(folder, "walk.tsv"))
    user_home = os.path.expanduser("~")
    live = [l.strip() for l in open(args.live_paths)] if args.live_paths else []
    live = [l for l in live if l and not l.startswith("#")]

    agent_items, agent_denied, summaries, extra = load_agents(args.agents or os.path.join(folder, "agents"))
    items = dedupe(worktree_items(args.worktree_plan) + place_virtual(agent_items))
    items, dropped = backed_by_walk(items, sizes)
    for it in dropped:
        print(f"mac_scan: left out {it['path']}: reported {it['bytes'] / GB:.1f} GB, but the walk measured "
              f"{it['walkBytes'] / GB:.1f} GB around it", file=sys.stderr)
    items += hotspots(sizes, items, user_home)
    for it in items:
        it["id"] = item_id(it["path"])
        it["category"] = it.get("category") if it.get("category") in CATEGORY_GROUP else "other"
        it["group"] = CATEGORY_GROUP[it["category"]]
        it["risk"] = it.get("risk") if it.get("risk") in ("safe", "review", "keep") else "review"
        it["kind"] = kind_of(it)
        users = [l for l in live if under(l, it["path"]) or (it.get("label", "").startswith("/") and under(l, it["label"]))]
        if users:
            it["inUse"] = True
            it["notes"] = ((it.get("notes") or "") + f" In use by a running session ({users[0]}).").strip()
            if it["risk"] == "safe":
                it["risk"] = "review"
        for k in ("what", "regenerates", "action", "notes", "modified"):
            if it.get(k) is not None:
                it[k] = str(it[k])[:600]
    items.sort(key=lambda it: -it["bytes"])

    by_role = {v["role"]: v["bytes"] for v in vols.get("volumes", [])}
    accounted = sizes.get(DATA, 0)
    unverified = max(0, by_role.get("Data", 0) - accounted)
    denied = denied_areas(os.path.join(folder, "walk.err"))
    seen = {d["path"] for d in denied}
    for p in agent_denied:
        if p not in seen and not any(under(p, s) for s in seen):
            denied.append({"path": p, "count": 1, "why": "privacy"})
            seen.add(p)

    host = args.host or vols.get("host") or socket.gethostname().split(".")[0]
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M")
    scan_id = re.sub(r"[^A-Za-z0-9-]", "-", f"{host}-{stamp}").lower()

    groups = []
    for key, title, blurb in GROUPS:
        g_items = [it for it in items if it["group"] == key]
        if not g_items:
            continue
        tops = top_level(g_items)
        groups.append({"key": key, "title": title, "blurb": blurb, "count": len(g_items),
                       "bytes": sum(it["bytes"] for it in tops),
                       "safeBytes": sum(it["bytes"] for it in top_level([i for i in g_items if i["risk"] == "safe"]))})
    suggested = sum(it["bytes"] for it in top_level([it for it in items if it["risk"] == "safe"]))

    scan = {
        "id": scan_id, "title": "Mac cleanup", "host": host, "createdAt": now_iso(), "status": "open",
        "disk": {"container": vols.get("size"), "free": vols.get("free"),
                 "used": (vols.get("size") or 0) - (vols.get("free") or 0),
                 "dataVolume": by_role.get("Data", 0), "volumes": vols.get("volumes", [])},
        "accounted": accounted,
        "unverified": {"bytes": unverified, "denied": denied[:40],
                       "note": "The Data volume holds this much more than the walk could read: folders macOS keeps "
                               "private without Full Disk Access, folders only root can read, and APFS's own metadata."},
        "bar": bar_segments(vols, sizes, user_home),
        "recent": dict(recent_growth(os.path.join(folder, "recent.tsv")), since=vols.get("since")),
        "groups": groups, "suggestedBytes": suggested, "itemCount": len(items),
        "investigators": summaries, "system": extra,
        "summary": open(args.summary_file).read() if args.summary_file else "",
    }
    os.makedirs(args.out, exist_ok=True)
    write_json(os.path.join(args.out, "scan.json"), dict(scan, items=items))

    # Rows: scans/<id> (the scan), scans/<id>/groups/<key>[-pN] (the items, split to fit a row).
    writes, sizes_ = [], []
    def add(collection, doc_id, body):
        path = os.path.join(args.out, f"row-{collection.replace('/', '_')}-{doc_id}.json")
        write_json(path, body)
        writes.append({"op": "set", "collection": collection, "doc_id": doc_id, "file_path": path})
        sizes_.append(os.path.getsize(path))
    add("scans", scan_id, scan)
    for order, g in enumerate(groups):
        g_items = [it for it in items if it["group"] == g["key"]]
        parts, cur, cur_size = [], [], 0
        for it in g_items:
            s = len(json.dumps(it, ensure_ascii=False)) + 2
            if cur and cur_size + s > ROW_LIMIT:
                parts.append(cur)
                cur, cur_size = [], 0
            cur.append(it)
            cur_size += s
        parts.append(cur)
        for n, chunk in enumerate(parts, 1):
            doc_id = g["key"] if n == 1 else f"{g['key']}-p{n}"
            add(f"scans/{scan_id}/groups", doc_id, {"key": g["key"], "order": order, "part": n,
                                                     "parts": len(parts), "items": chunk})
    write_json(os.path.join(args.out, "writes.json"), writes)
    batches, cur, cur_bytes = [], [], 0
    for w, s in zip(writes, sizes_):
        if cur and (len(cur) >= MAX_BATCH_WRITES or cur_bytes + s > MAX_BATCH_BYTES):
            batches.append(cur)
            cur, cur_bytes = [], 0
        cur.append(w)
        cur_bytes += s
    batches.append(cur)
    batch_paths = []
    if len(batches) > 1:
        for n, b in enumerate(batches, 1):
            batch_paths.append(os.path.join(args.out, f"writes-{n}.json"))
            write_json(batch_paths[-1], b)
    print(json.dumps({"id": scan_id, "writes": os.path.join(args.out, "writes.json"), "batches": batch_paths,
                      "items": len(items), "suggestedBytes": suggested, "unverifiedBytes": unverified}))
    return 0


# ---------------------------------------------------------------------------- remove

def du_bytes(path):
    r = subprocess.run(["du", "-sk", path], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0]) * 1024
    except (IndexError, ValueError):
        return 0


def written_within(path, minutes):
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    r = subprocess.run(["find", path, "-xdev", "-newermt", cutoff, "-print", "-quit"], capture_output=True, text=True)
    return r.stdout.strip()


def open_files_under(paths):
    """Which of these paths a running process holds open, from one lsof pass."""
    r = subprocess.run(["lsof", "-n", "-Fn"], capture_output=True, text=True)
    held = {}
    for line in r.stdout.splitlines():
        if not line.startswith("n/"):
            continue
        f = line[1:]
        for p in paths:
            if p not in held and under(f, p):
                held[p] = f
    return held


def cmd_remove(args):
    scan = json.load(open(args.scan))
    picks = json.load(open(args.picks))
    picks = picks.get("picks", picks)
    live = [l.strip() for l in open(args.live_paths)] if args.live_paths else []
    live = [l for l in live if l and not l.startswith("#")]
    by_id = {it["id"]: it for it in scan["items"]}
    chosen = [by_id[i] for i, p in picks.items() if isinstance(p, dict) and p.get("pick") == "remove" and i in by_id]
    unknown = [i for i, p in picks.items() if isinstance(p, dict) and p.get("pick") == "remove" and i not in by_id]
    if not chosen:
        print("mac_scan: nothing is picked for removal." + (f" {len(unknown)} pick(s) name items not in this scan." if unknown else ""))
        return 2
    chosen = top_level(chosen)
    paths = [it["path"] for it in chosen if it["kind"] == "path"]
    held = open_files_under(paths) if paths else {}
    plan = {"remove": [], "held": [], "worktrees": [], "commands": [], "manual": []}
    for it in chosen:
        p = it["path"]
        if it["kind"] == "worktree":
            plan["worktrees"].append(it)
            continue
        if it["kind"] == "command":
            plan["commands"].append(it)
            continue
        if it["kind"] == "manual":
            plan["manual"].append(it)
            continue
        why = None
        if not os.path.exists(p):
            why = "already gone"
        elif any(p == n or p.startswith(n + "/") for n in NEVER) or not p.startswith(REMOVABLE_ROOTS):
            why = "outside the folders this tool deletes from; do it by hand if you mean it"
        elif p.rstrip("/") in (os.path.expanduser("~"), "/Users", "/private/tmp"):
            why = "a top-level folder; refusing"
        elif any(under(l, p) for l in live):
            why = "a running session works inside it"
        elif p in held:
            why = f"a running process has a file open in it ({held[p]})"
        else:
            recent = written_within(p, args.quiet_minutes)
            if recent:
                why = f"written to in the last {args.quiet_minutes} minutes ({recent})"
        if why:
            plan["held"].append(dict(it, heldBecause=why))
        else:
            plan["remove"].append(dict(it, bytesNow=du_bytes(p)))

    freed, failed = 0, []
    if args.execute:
        for it in plan["remove"]:
            try:
                if os.path.isdir(it["path"]) and not os.path.islink(it["path"]):
                    shutil.rmtree(it["path"])
                else:
                    os.remove(it["path"])
                it["result"] = "removed"
                freed += it["bytesNow"]
            except Exception as exc:
                it["result"] = f"failed: {exc}"
                failed.append(it)

    def gb(b):
        return f"{b / GB:6.2f} GB"
    verb = "Removed" if args.execute else "Would remove"
    print(f"{verb}: {len(plan['remove'])} item(s), {gb(sum(i['bytesNow'] for i in plan['remove'])).strip()}")
    for it in plan["remove"]:
        print(f"  {'✗' if it.get('result', '').startswith('failed') else '✓'} {gb(it['bytesNow'])}  {it['path']}"
              + (f"  [{it['result']}]" if it.get("result") else ""))
    if plan["held"]:
        print(f"\nHeld back on re-check: {len(plan['held'])}")
        for it in plan["held"]:
            print(f"  ⊘ {gb(it['bytes'])}  {it['path']}\n      {it['heldBecause']}")
    if plan["worktrees"]:
        print(f"\nWorktrees ({len(plan['worktrees'])}): remove with remove_worktrees.py --only, after fresh liveness:")
        for it in plan["worktrees"]:
            print(f"  {gb(it['bytes'])}  {it['path']}")
    if plan["commands"]:
        print(f"\nTool commands ({len(plan['commands'])}): run each yourself, one at a time, after reading it:")
        for it in plan["commands"]:
            print(f"  {gb(it['bytes'])}  {it['path']}\n      $ {it['action']}")
    if plan["manual"]:
        print(f"\nManual steps ({len(plan['manual'])}): for the owner to do:")
        for it in plan["manual"]:
            print(f"  {gb(it['bytes'])}  {it['path']}\n      {it.get('action') or it.get('regenerates')}")
    if not args.execute:
        print("\n(dry run — nothing was deleted; re-run with --execute)")
    if args.execute:
        print(f"\nFreed by this run: {gb(freed).strip()} (measured before each removal).")
    write_json(os.path.splitext(args.picks)[0] + "-result.json", plan)
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("walk")
    w.add_argument("--out", required=True)
    w.add_argument("--since")
    w.add_argument("--depth", type=int, default=9)
    b = sub.add_parser("build")
    b.add_argument("--dir", required=True, help="the walk's --out folder")
    b.add_argument("--out", required=True)
    b.add_argument("--agents", help="folder of investigator JSON files (default: <dir>/agents)")
    b.add_argument("--worktree-plan", help="scan_worktrees.py --json output")
    b.add_argument("--live-paths", help="working directories of live sessions, one per line")
    b.add_argument("--summary-file", help="Markdown summary shown at the top of the page")
    b.add_argument("--host")
    r = sub.add_parser("remove")
    r.add_argument("--scan", required=True)
    r.add_argument("--picks", required=True, help="the scan row's picks, as saved from ArtifactData")
    r.add_argument("--live-paths")
    r.add_argument("--quiet-minutes", type=int, default=30)
    r.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    return {"walk": cmd_walk, "build": cmd_build, "remove": cmd_remove}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
