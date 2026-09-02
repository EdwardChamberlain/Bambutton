"""Normal operating mode: join Wi-Fi, serve the config page at the board's LAN
IP (so Bambuddy/printers can be set from a PC), and poll whatever stations are
configured. Started by main.py once Wi-Fi credentials exist.

All wired stations are created (even without a printer assigned) so their LED
can be blinked from the web UI ("identify"); unassigned stations stay dark and
are not polled. The board is reachable on the LAN even before Bambuddy is set."""
import time

try:
    from machine import Pin, WDT
except ImportError:  # allows host-side testing
    Pin = None
    WDT = None
try:
    from machine import reset as machine_reset
except ImportError:
    machine_reset = None

import bambuddy_api
import gpio_button
import wifi
import periodic_timer
import bb_util
import webconfig


def _now_ms():
    return time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)


def _diff_ms(a, b):
    return time.ticks_diff(a, b) if hasattr(time, "ticks_diff") else (a - b)


class Station:
    def __init__(self, index, printer_ref, led_pin, button_pin,
                 debounce_ms=150, pull="down", trigger="rising"):
        self.index = index
        self.printer_ref = printer_ref
        self.active = bool(str(printer_ref).strip())
        self.printer_id = None
        self.led = Pin(led_pin, Pin.OUT)
        self.awaiting_plate_clear = False
        self.pending_button_press = False
        self.chamber_light_on = True
        self.status_update_required = True
        self.identify_until = 0
        self.button = gpio_button.GPIOButton(
            pin_number=button_pin,
            on_press=self._on_press,
            debounce_ms=debounce_ms,
            pull=pull,
            trigger=trigger,
        )

    def _on_press(self, pin):
        if self.awaiting_plate_clear:
            self.awaiting_plate_clear = False
            self.pending_button_press = True

    def start_button(self):
        self.button.start()

    def identify(self, seconds=4):
        self.identify_until = _now_ms() + int(float(seconds) * 1000)

    def update_led(self):
        if self.identify_until and _diff_ms(self.identify_until, _now_ms()) > 0:
            self.led.value(0 if self.led.value() else 1)   # blink to identify
            return
        if not self.active:
            self.led.value(0)                                # no printer -> dark
            return
        if self.awaiting_plate_clear and not self.pending_button_press:
            self.led.value(0 if self.led.value() else 1)
        else:
            self.led.value(1 if self.chamber_light_on else 0)


def build_stations(config):
    button_cfg = config.get("button", {})
    stations = []
    for index, entry in enumerate(config.get("stations", [])):
        stations.append(
            Station(
                index=index,
                printer_ref=entry.get("printer_id", entry.get("printer", "")),
                led_pin=entry["led_pin"],
                button_pin=entry["button_pin"],
                debounce_ms=button_cfg.get("debounce_ms", 150),
                pull=button_cfg.get("pull", "down"),
                trigger=button_cfg.get("trigger", "rising"),
            )
        )
    return stations


def network_call(network, request):
    network.ensure_connected()
    return request()


def resolve_station_ids(api, network, stations):
    name_map = {}
    need_names = False
    for station in stations:
        if station.printer_id is None and not bb_util.is_numeric(station.printer_ref):
            need_names = True
            break
    if need_names:
        try:
            printers = network_call(network, lambda: api.get_printers())
            name_map = bb_util.build_name_map(bb_util.extract_list(printers))
            print("Bambuddy printers:", list(name_map.keys()))
        except Exception as exc:
            print("Could not fetch printer list:", exc)
            return False

    all_resolved = True
    for station in stations:
        if station.printer_id is not None:
            continue
        pid = bb_util.match_printer_id(station.printer_ref, name_map)
        if pid is None:
            all_resolved = False
            print("Station", station.index, "could not resolve printer:", station.printer_ref)
        else:
            station.printer_id = pid
            print("Station", station.index, "->", station.printer_ref, "= id", pid)
    return all_resolved


def handle_pending_press(api, network, station):
    try:
        network_call(network, lambda: api.clear_plate(station.printer_id))
        station.status_update_required = True
        print("Station", station.index, "plate marked clear")
    except Exception as exc:
        print("Station", station.index, "clear-plate failed:", exc)
    station.pending_button_press = False


def handle_status_update(api, network, station):
    if station.printer_id is None:
        station.status_update_required = False
        return
    try:
        response = network_call(network, lambda: api.get_printer_status(station.printer_id))
        station.awaiting_plate_clear = bool(response.get("awaiting_plate_clear", False))
        station.chamber_light_on = bool(response.get("chamber_light", station.chamber_light_on))
    except Exception as exc:
        print("Station", station.index, "status fetch failed:", exc)
    station.status_update_required = False


def _sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000.0)


def connect_wifi(config, stations, attempts=3):
    network = wifi.WiFi(
        ssid=config["wifi"]["ssid"],
        password=config["wifi"]["password"],
        status_led=None,
        timeout_seconds=config["wifi"].get("timeout_seconds", 10),
    )
    last = None
    for _ in range(attempts):
        try:
            network.connect()
            return network
        except Exception as exc:
            last = exc
            print("Wi-Fi attempt failed:", exc)
            time.sleep(1)
    for station in stations:
        station.led.value(1)
    raise RuntimeError("Wi-Fi connect failed: %s" % last)


def build_api(config):
    api_cfg = config.get("api", {})
    base = str(api_cfg.get("base_url", "")).strip()
    key = str(api_cfg.get("key", "")).strip()
    if not base or not key:
        return None
    return bambuddy_api.BambuddyAPI(
        key, bb_util.normalize_base_url(base), api_cfg.get("request_timeout_seconds", 3)
    )


def run(config, max_iterations=None):
    stations = build_stations(config)               # all wired stations
    active = [s for s in stations if s.active]       # those with a printer

    watchdog = WDT(timeout=60_000) if WDT else None
    for station in stations:
        station.start_button()

    network = connect_wifi(config, stations)         # raises on failure -> setup
    api = build_api(config)                           # None until Bambuddy set

    if api and active:
        attempts = 0
        while not resolve_station_ids(api, network, active):
            if watchdog:
                watchdog.feed()
            attempts += 1
            if attempts >= 3:
                print("Continuing; unresolved stations will keep retrying.")
                break
            time.sleep(3)

    poll_state = {"due": True}

    def on_poll_tick():
        poll_state["due"] = True

    def on_flash_tick():
        for station in stations:
            station.update_led()

    if stations:
        periodic_timer.PeriodicTimer(
            period_ms=int(config.get("poll_interval_seconds", 3) * 1000),
            callback=on_poll_tick,
        ).start()
        periodic_timer.PeriodicTimer(
            period_ms=int(config.get("led", {}).get("flash_interval_ms", 250)),
            callback=on_flash_tick,
        ).start()

    webconfig.FEED = watchdog.feed if watchdog else None
    server = None
    if max_iterations is None:
        try:
            server = webconfig.Server(config, {"mode": "normal", "api": api, "stations": stations})
            print("Konfig-Server: http://%s/" % network.ifconfig()[0])
        except Exception as exc:
            print("Konfig-Server nicht gestartet:", exc)

    iterations = 0
    while True:
        if watchdog:
            watchdog.feed()

        if api and active:
            for station in active:
                if station.pending_button_press:
                    handle_pending_press(api, network, station)
            if poll_state["due"]:
                poll_state["due"] = False
                for station in active:
                    if station.printer_id is None:
                        resolve_station_ids(api, network, [station])
                    handle_status_update(api, network, station)

        if server is not None:
            try:
                if server.poll():
                    print("Konfig gespeichert/aktualisiert -> Neustart")
                    _sleep_ms(300)
                    if machine_reset:
                        machine_reset()
            except Exception as exc:
                print("Konfig-Server-Fehler:", exc)

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return stations
        _sleep_ms(25)
