"""Boot orchestrator.

- Config button held at power-on  -> setup portal
- Config incomplete (fresh flash) -> setup portal
- Otherwise run normally; if Wi-Fi won't come up -> fall back to setup portal
"""
import time

try:
    from machine import Pin
except ImportError:  # host-side testing
    Pin = None

import config_loader


def config_button_pressed(config):
    """True if station A's button is held down at boot (pull-down: pressed=HIGH)."""
    if Pin is None:
        return False
    try:
        stations = config.get("stations") or []
        pin_no = stations[0].get("button_pin", 4) if stations else 4
    except Exception:
        pin_no = 4
    try:
        pin = Pin(pin_no, Pin.IN, Pin.PULL_DOWN)
        high = 0
        for _ in range(6):
            if pin.value():
                high += 1
            if hasattr(time, "sleep_ms"):
                time.sleep_ms(15)
            else:
                time.sleep(0.015)
        return high >= 5
    except Exception:
        return False


def apply_hostname(config):
    """Set the network/DHCP hostname before Wi-Fi comes up, so the board shows
    up by name in the router/client list instead of a generic chip name."""
    name = str(config.get("hostname", "")).strip()
    if not name:
        return
    try:
        import network
        network.hostname(name)
        print("Hostname:", name)
    except Exception as exc:
        print("hostname set failed:", exc)


def decide_setup(config, button_pressed):
    # Only the Wi-Fi credentials gate the setup AP. Bambuddy + printers are set
    # afterwards from a PC via the board's LAN IP.
    if button_pressed:
        return True, "Config-Taste beim Start gehalten"
    if not str(config.get("wifi", {}).get("ssid", "")).strip():
        return True, "Kein WLAN hinterlegt"
    return False, ""


def main():
    config = config_loader.load_config()
    apply_hostname(config)
    setup, reason = decide_setup(config, config_button_pressed(config))
    if setup:
        print("Setup-Modus:", reason)
        import provisioning
        provisioning.run(config)
        return

    import runner
    try:
        runner.run(config)
    except Exception as exc:
        print("Normalbetrieb nicht moeglich -> Setup-Modus:", exc)
        import provisioning
        provisioning.run(config)


if __name__ == "__main__":
    main()
