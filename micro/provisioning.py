"""Setup mode entry point: opens the access point + captive portal.
The actual web layer lives in webconfig (shared with normal mode)."""
import webconfig


def run(config):
    webconfig.run_setup(config)
