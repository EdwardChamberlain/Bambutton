"""Stable MicroPython entrypoint for the atomic application updater."""

import machine
import ota_manager


manager = ota_manager.OTAUpdateManager(reset=machine.reset)

try:
    manager.launch()
except ota_manager.OTAError as exc:
    print("Bambutton boot error:", exc)
    raise
