"""Tests for mac_scan.py: the page's numbers add up, contradicted sizes stay out, and removal re-checks.

Run: python3 -m unittest discover -s plugins/mac-cleanup/skills/mac-cleanup/tests -p 'test_*.py'
"""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.dont_write_bytecode = True
import mac_scan  # noqa: E402

D = mac_scan.DATA
GB = 10 ** 9


def kb(b):
    return str(int(b // 1024))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.home = "/Users/tester"
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        vols = {"size": 100 * GB, "free": 10 * GB, "host": "testmac", "since": "2026-10-01",
                "volumes": [{"name": "Macintosh HD", "role": "System", "bytes": 10 * GB},
                            {"name": "Data", "role": "Data", "bytes": 75 * GB},
                            {"name": "VM", "role": "VM", "bytes": 5 * GB}]}
        json.dump(vols, open(os.path.join(self.dir, "volumes.json"), "w"))
        walk = [
            (70 * GB, D), (50 * GB, D + "/Users"), (50 * GB, D + self.home),
            (20 * GB, D + self.home + "/Library"), (25 * GB, D + self.home + "/proj"),
            (3 * GB, D + self.home + "/proj/node_modules"), (5 * GB, D + self.home + "/.npm"),
            (10 * GB, D + "/Applications"), (10 * GB, D + "/Library"), (6 * GB, D + "/Library/Big/Samples"),
            (6 * GB, D + "/Library/Big"),
        ]
        with open(os.path.join(self.dir, "walk.tsv"), "w") as fh:
            for b, p in walk:
                fh.write(f"{kb(b)}\t{p}\n")
        open(os.path.join(self.dir, "walk.err"), "w").write(
            f"du: {D}{self.home}/Library/Mail: Operation not permitted\n"
            f"du: {D}/private/var/db/x: Permission denied\n")
        open(os.path.join(self.dir, "recent.tsv"), "w").write(f"4000000\t{D}{self.home}/proj/big.bin\n")
        os.makedirs(os.path.join(self.dir, "agents"))
        report = {"area": "repos", "summary": "Projects.", "denied": [], "items": [
            {"path": self.home + "/proj/node_modules", "bytes": 3 * GB, "what": "deps", "category": "dev-build",
             "risk": "safe", "action": f"rm -rf {self.home}/proj/node_modules"},
            {"path": self.home + "/proj/mounted.dmg", "bytes": 40 * GB, "what": "estimate", "category": "simulators",
             "risk": "review", "action": "rm -rf x"},
            {"path": "docker-volume:db_data", "bytes": 2 * GB, "what": "volume", "category": "containers-vms",
             "risk": "review", "action": "docker volume rm db_data"},
        ]}
        json.dump(report, open(os.path.join(self.dir, "agents", "repos.json"), "w"))
        draft = dict(report, items=[{"path": self.home + "/proj/draft", "bytes": GB, "category": "repos"}])
        json.dump(draft, open(os.path.join(self.dir, "agents", "repos_draft.json"), "w"))

    def tearDown(self):
        os.environ["HOME"] = self.old_home or ""
        self.tmp.cleanup()

    def build(self):
        out = os.path.join(self.dir, "page")
        args = argparse.Namespace(dir=self.dir, out=out, agents=None, worktree_plan=None, live_paths=None,
                                  summary_file=None, host=None)
        with contextlib.redirect_stdout(io.StringIO()) as so, contextlib.redirect_stderr(io.StringIO()) as se:
            mac_scan.cmd_build(args)
        return json.load(open(os.path.join(out, "scan.json"))), json.loads(so.getvalue()), se.getvalue(), out

    def test_bar_adds_up_to_the_container(self):
        scan, _, _, _ = self.build()
        # du reports whole KiB, so the walked folders lose under a KiB each; nothing else may be missing.
        self.assertAlmostEqual(sum(s["bytes"] for s in scan["bar"]), 100 * GB, delta=10 * 1024)
        by = {s["key"]: s["bytes"] for s in scan["bar"]}
        self.assertAlmostEqual(by["unverified"], 5 * GB, delta=1024)  # Data volume 75 GB minus the 70 GB walked
        self.assertEqual(by["free"], 10 * GB)
        self.assertEqual(by["swap"], 5 * GB)

    def test_unverified_names_the_folders_behind_it(self):
        scan, printed, _, _ = self.build()
        paths = [d["path"] for d in scan["unverified"]["denied"]]
        self.assertIn(self.home + "/Library/Mail", paths)
        self.assertEqual(printed["unverifiedBytes"], scan["unverified"]["bytes"])

    def test_a_size_the_walk_contradicts_is_left_out(self):
        scan, _, err, _ = self.build()
        self.assertNotIn(self.home + "/proj/mounted.dmg", [i["path"] for i in scan["items"]])
        self.assertIn("left out", err)

    def test_working_files_of_an_investigator_add_no_rows(self):
        scan, _, _, _ = self.build()
        self.assertNotIn(self.home + "/proj/draft", [i["path"] for i in scan["items"]])

    def test_docker_things_sit_under_docker_and_are_commands(self):
        scan, _, _, _ = self.build()
        vol = [i for i in scan["items"] if i.get("label") == "docker-volume:db_data"][0]
        self.assertTrue(vol["path"].startswith(self.home + "/Library/Containers/com.docker.docker/"))
        self.assertEqual(vol["kind"], "command")

    def test_big_unexplained_folders_get_a_row(self):
        scan, _, _, _ = self.build()
        other = sorted(i["path"] for i in scan["items"] if i["group"] == "other")
        # the deepest big folder, not its parent; ~/proj is explained by its node_modules row
        self.assertEqual(other, ["/Library/Big/Samples", self.home + "/.npm"])

    def test_known_wrong_commands_are_fixed_before_the_owner_picks(self):
        lib = self.home + "/Library"
        report = {"area": "caches", "items": [
            {"path": self.home + "/.nvm", "bytes": GB, "category": "dev-build", "risk": "safe",
             "action": f"find '{self.home}/.nvm' -name 'node_modules' -type d -prune -exec rm -rf {{}} +"},
            {"path": lib + "/Caches/pnpm", "bytes": GB, "category": "package-caches", "risk": "safe",
             "action": "pnpm cache delete"},
            {"path": lib + "/Caches/ms-playwright", "bytes": GB, "category": "package-caches", "risk": "safe",
             "action": "npx playwright uninstall --all"},
            {"path": lib + "/Application Support/Steam/Steam.AppBundle", "bytes": GB, "category": "app-data",
             "risk": "keep", "action": "none (keep)."},
        ]}
        json.dump(report, open(os.path.join(self.dir, "agents", "caches.json"), "w"))
        scan, _, _, _ = self.build()
        by = {i["path"]: i for i in scan["items"]}
        nvm = by[self.home + "/.nvm"]
        # npm itself and the global packages live in there: never offered as build output
        self.assertEqual((nvm["risk"], nvm["kind"], nvm["action"]), ("keep", "manual", ""))
        self.assertEqual(by[lib + "/Caches/pnpm"]["kind"], "path")
        self.assertEqual(by[lib + "/Caches/ms-playwright"]["action"], f'rm -rf "{lib}/Caches/ms-playwright"')
        steam = by[lib + "/Application Support/Steam/Steam.AppBundle"]
        self.assertEqual((steam["kind"], steam["action"]), ("manual", ""))

    def test_rows_fit_and_name_their_files(self):
        scan, printed, _, out = self.build()
        writes = json.load(open(printed["writes"]))
        self.assertEqual(writes[0]["collection"], "scans")
        self.assertEqual(writes[0]["doc_id"], scan["id"])
        for w in writes:
            self.assertLess(os.path.getsize(w["file_path"]), 256 * 1024)


class RemoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.saved_roots = mac_scan.REMOVABLE_ROOTS
        mac_scan.REMOVABLE_ROOTS = (self.root + "/",)
        old = time.time() - 3 * 3600
        self.paths = {}
        for name in ("cache", "cache/inner", "live", "fresh", "keepme"):
            p = os.path.join(self.root, name)
            os.makedirs(p, exist_ok=True)
            with open(os.path.join(p, "f.bin"), "wb") as fh:
                fh.write(b"x" * 4096)
            self.paths[name] = p
        for dirpath, dirs, files in os.walk(self.root):
            for f in files:
                os.utime(os.path.join(dirpath, f), (old, old))
            os.utime(dirpath, (old, old))
        with open(os.path.join(self.paths["fresh"], "new.bin"), "wb") as fh:
            fh.write(b"y")
        items = [dict(id=mac_scan.item_id(p), path=p, bytes=4096, kind="path", risk="safe") for p in self.paths.values()]
        items.append(dict(id="w1", path=self.root + "/wt", bytes=1, kind="worktree", risk="safe"))
        self.scan = os.path.join(self.root, "scan.json")
        json.dump({"items": items}, open(self.scan, "w"))
        picks = {mac_scan.item_id(self.paths[n]): {"pick": "remove"} for n in ("cache", "cache/inner", "live", "fresh")}
        picks[mac_scan.item_id(self.paths["keepme"])] = {"pick": "keep"}
        picks["w1"] = {"pick": "remove"}
        self.picks = os.path.join(self.root, "picks.json")
        json.dump({"picks": picks}, open(self.picks, "w"))
        self.live = os.path.join(self.root, "live.txt")
        open(self.live, "w").write(self.paths["live"] + "/sub\n")

    def tearDown(self):
        mac_scan.REMOVABLE_ROOTS = self.saved_roots
        for dirpath, dirs, files in os.walk(self.root):
            os.chmod(dirpath, 0o755)
        self.tmp.cleanup()

    def run_remove(self, execute, include_keep=False):
        args = argparse.Namespace(scan=self.scan, picks=self.picks, live_paths=self.live, quiet_minutes=30,
                                  include_keep=include_keep, execute=execute)
        with contextlib.redirect_stdout(io.StringIO()) as so:
            code = mac_scan.cmd_remove(args)
        return code, so.getvalue(), json.load(open(os.path.splitext(self.picks)[0] + "-result.json"))

    def add(self, item, pick="remove"):
        """One more item in the scan, picked."""
        scan = json.load(open(self.scan))
        item = dict({"bytes": 4096, "risk": "safe", "kind": "path"}, **item)
        item.setdefault("id", mac_scan.item_id(item["path"]))
        scan["items"].append(item)
        json.dump(scan, open(self.scan, "w"))
        picks = json.load(open(self.picks))
        picks["picks"][item["id"]] = {"pick": pick}
        json.dump(picks, open(self.picks, "w"))
        return item

    def old_folder(self, *parts):
        p = os.path.join(self.root, *parts)
        os.makedirs(p)
        with open(os.path.join(p, "f.bin"), "wb") as fh:
            fh.write(b"x" * 8192)
        old = time.time() - 3 * 3600
        os.utime(os.path.join(p, "f.bin"), (old, old))
        for n in range(len(parts), 0, -1):    # every folder makedirs just created, or the re-check holds it
            os.utime(os.path.join(self.root, *parts[:n]), (old, old))
        return p

    def test_a_failed_removal_is_not_counted_as_removed(self):
        contents = self.old_folder("dotslash", "Tool.app", "Contents")
        os.chmod(contents, 0o555)   # what App Management does to a bundle: nothing in it can be deleted
        self.add({"path": os.path.join(self.root, "dotslash")})
        code, out, plan = self.run_remove(True)
        self.assertEqual(code, 1)
        self.assertIn("Removed: 1 of 2 item(s)", out)
        failed = [i for i in plan["remove"] if i["result"].startswith("failed")]
        self.assertEqual(len(failed), 1)
        self.assertIn("Finder", failed[0]["result"])
        self.assertEqual(failed[0]["freed"], 0)

    def test_picks_marked_keep_wait_for_a_second_yes(self):
        p = self.old_folder("runtime")
        self.add({"path": p, "risk": "keep"})
        _, out, plan = self.run_remove(True)
        self.assertTrue(os.path.exists(p))
        self.assertEqual([i["path"] for i in plan["keep"]], [p])
        self.assertIn("--include-keep", out)
        self.run_remove(True, include_keep=True)
        self.assertFalse(os.path.exists(p))

    def test_commands_that_need_sudo_go_to_the_owner(self):
        self.add({"path": self.root + "/dyld", "kind": "command", "action": "sudo rm -rf /Library/x"})
        self.add({"path": self.root + "/npm", "kind": "command", "action": "npm cache clean --force"})
        _, _, plan = self.run_remove(False)
        self.assertEqual([i["path"] for i in plan["owner"]], [self.root + "/dyld"])
        self.assertEqual([i["path"] for i in plan["commands"]], [self.root + "/npm"])

    def test_a_folder_finder_refills_is_removed_on_the_next_pass(self):
        p = self.old_folder("finder-open")
        real, calls = mac_scan.shutil.rmtree, []

        def flaky(path, *a, **k):
            calls.append(path)
            if len(calls) == 1:
                raise OSError(mac_scan.errno.ENOTEMPTY, "Directory not empty", path)
            return real(path, *a, **k)
        mac_scan.shutil.rmtree = flaky
        try:
            self.assertIsNone(mac_scan.delete_path(p))
        finally:
            mac_scan.shutil.rmtree = real
        self.assertFalse(os.path.exists(p))
        self.assertEqual(len(calls), 2)

    def test_check_holds_what_is_in_use_and_measures_the_rest(self):
        args = argparse.Namespace(live_paths=self.live, quiet_minutes=30,
                                  paths=[self.paths["cache"], self.paths["live"], self.paths["fresh"],
                                         self.root + "/missing"])
        with contextlib.redirect_stdout(io.StringIO()) as so:
            code = mac_scan.cmd_check(args)
        self.assertEqual(code, 3)
        rows = {os.path.basename(r[2]): r for r in (l.split("\t") for l in so.getvalue().splitlines())}
        self.assertEqual(rows["cache"][0], "ok")
        self.assertGreater(int(rows["cache"][1]), 0)
        self.assertIn("running session", rows["live"][3])
        self.assertIn("written to", rows["fresh"][3])
        self.assertEqual(rows["missing"][0], "gone")

    def test_dry_run_deletes_nothing(self):
        code, out, plan = self.run_remove(False)
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        for p in self.paths.values():
            self.assertTrue(os.path.exists(p))

    def test_execute_removes_only_what_passes_the_recheck(self):
        code, out, plan = self.run_remove(True)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.paths["cache"]))
        held = {os.path.basename(i["path"]): i["heldBecause"] for i in plan["held"]}
        self.assertIn("running session", held["live"])
        self.assertIn("written to", held["fresh"])
        self.assertTrue(os.path.exists(self.paths["live"]))
        self.assertTrue(os.path.exists(self.paths["fresh"]))
        self.assertTrue(os.path.exists(self.paths["keepme"]))
        self.assertEqual([i["path"] for i in plan["worktrees"]], [self.root + "/wt"])

    def test_a_folder_and_its_child_count_once(self):
        _, _, plan = self.run_remove(False)
        removed = [i["path"] for i in plan["remove"]]
        self.assertIn(self.paths["cache"], removed)
        self.assertNotIn(self.paths["cache/inner"], removed)

    def test_outside_the_allowed_roots_is_refused(self):
        mac_scan.REMOVABLE_ROOTS = ("/nowhere/",)
        code, _, plan = self.run_remove(True)
        self.assertTrue(os.path.exists(self.paths["cache"]))
        self.assertTrue(all("outside" in i["heldBecause"] for i in plan["held"]))


if __name__ == "__main__":
    unittest.main()
