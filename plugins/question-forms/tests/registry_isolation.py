"""Every test that runs a hook (which writes the shared registry of AI-DLC artifact links, scripts/aidlc_links.py) imports
this first: the registry goes to a temporary folder, never to the real one in ~/.claude/plugins/data/aidlc-artifacts."""

import atexit
import os
import shutil
import tempfile

REAL = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "aidlc-artifacts")
TEMP = tempfile.mkdtemp(prefix="aidlc-links-test-")
os.environ["AIDLC_ARTIFACTS_DIR"] = TEMP
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)


def real_listing():
    """Every file and folder of the real registry folder, now."""
    found = []
    for folder, dirs, files in os.walk(REAL):
        found += [os.path.join(folder, name) for name in dirs + files]
    return sorted(found)
