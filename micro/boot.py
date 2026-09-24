"""Recover an interrupted loader handoff, then return to MicroPython startup."""

import os


BOOTSTRAP_MARKER = ".bambutton/bootstrap-install.marker"
STAGED_MAIN = ".bambutton/bootstrap/main.py"
LEGACY_MAIN = ".bambutton/legacy_main.py"


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def recover_main_handoff():
    try:
        with open(BOOTSTRAP_MARKER) as marker:
            if marker.read().strip() != "bambutton-bootstrap-v1":
                return
    except OSError:
        return

    if exists(STAGED_MAIN):
        if exists("main.py") and not exists(LEGACY_MAIN):
            os.rename("main.py", LEGACY_MAIN)
        if not exists("main.py"):
            os.rename(STAGED_MAIN, "main.py")
    elif not exists("main.py") and exists(LEGACY_MAIN):
        # A damaged staging directory should still leave the old app bootable.
        os.rename(LEGACY_MAIN, "main.py")


recover_main_handoff()
