"""Stable boot hook used to migrate existing flat-root installations."""

import machine
import ota_manager


manager = ota_manager.OTAUpdateManager(reset=machine.reset)

try:
    manager.launch()
except ota_manager.OTAError as exc:
    print("Bambutton boot error:", exc)
    raise
