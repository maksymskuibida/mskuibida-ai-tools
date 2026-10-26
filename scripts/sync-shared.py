#!/usr/bin/env python3
"""Keep the shared pieces in shared/ and their copies in the plugins the same.

A plugin is installed on its own, so a piece several plugins use is copied into each one. The canonical copy lives in
shared/, and this script writes it into every plugin that carries it:

  shared/aidlc-ids/aidlc_ids.py     -> plugins/*/scripts/aidlc_ids.py, wherever one exists
  shared/aidlc-ids/aidlc-ids.js     -> every page (plugins/**/*.html) between /* aidlc-ids.js:begin */ and :end */
  shared/aidlc-ids/aidlc-ids.css    -> the same pages, between /* aidlc-ids.css:begin */ and :end */

  sync-shared.py                     write the shared copies into every plugin file that carries one
  sync-shared.py --check             exit 1, naming each file, when a copy differs from shared/ (CI runs this)
  sync-shared.py --add-page <html>   give a page both blocks: the CSS at the end of its first <style>, the script as a
                                     <script> of its own before its first <script>
  sync-shared.py --add-python <dir>  copy aidlc_ids.py into a plugin's scripts folder

Edit the shared copy, never a plugin's. Standard library only.
"""

import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(ROOT, "shared", "aidlc-ids")
PY = "aidlc_ids.py"
BLOCKS = {"aidlc-ids.js": "aidlc-ids.js", "aidlc-ids.css": "aidlc-ids.css"}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def marker(name):
    return re.compile(r"(/\* " + re.escape(name) + r":begin \*/\n)(.*?)(\n?/\* " + re.escape(name) + r":end \*/)", re.S)


def shared(name):
    return read(os.path.join(SHARED, name)).rstrip("\n")


def pages():
    return sorted(p for p in glob.glob(os.path.join(ROOT, "plugins", "**", "*.html"), recursive=True)
                  if any(f"/* {n}:begin */" in read(p) for n in BLOCKS))


def pythons():
    return sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "scripts", PY)))


def synced_page(text):
    for name, src in BLOCKS.items():
        body = shared(src)
        text = marker(name).sub(lambda m: m.group(1) + body + "\n" + m.group(3).lstrip("\n"), text)
    return text


def add_page(path):
    text = read(path)
    if "/* aidlc-ids.css:begin */" not in text:
        if "</style>" not in text:
            raise SystemExit(f"sync-shared.py: {path} has no <style> to add the CSS to")
        text = text.replace("</style>", "/* aidlc-ids.css:begin */\n/* aidlc-ids.css:end */\n</style>", 1)
    if "/* aidlc-ids.js:begin */" not in text:
        at = text.find("<script")
        if at < 0:
            raise SystemExit(f"sync-shared.py: {path} has no <script> to put the shared one before")
        text = text[:at] + "<script>\n/* aidlc-ids.js:begin */\n/* aidlc-ids.js:end */\n</script>\n" + text[at:]
    write(path, synced_page(text))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sync-shared.py")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--add-page", action="append", default=[])
    ap.add_argument("--add-python", action="append", default=[])
    args = ap.parse_args(argv)
    for path in args.add_page:
        add_page(os.path.abspath(path))
    for folder in args.add_python:
        os.makedirs(folder, exist_ok=True)
        write(os.path.join(folder, PY), read(os.path.join(SHARED, PY)))
    stale = []
    canonical = read(os.path.join(SHARED, PY))
    for path in pythons():
        if read(path) != canonical:
            stale.append(path)
            if not args.check:
                write(path, canonical)
    for path in pages():
        text = read(path)
        if synced_page(text) != text:
            stale.append(path)
            if not args.check:
                write(path, synced_page(text))
    rel = [os.path.relpath(p, ROOT) for p in stale]
    if args.check:
        if rel:
            for p in rel:
                print(f"{p}: differs from shared/; run scripts/sync-shared.py")
            return 1
        print(f"OK shared copies match: {len(pythons())} aidlc_ids.py, {len(pages())} pages")
        return 0
    for p in rel:
        print(f"synced {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
