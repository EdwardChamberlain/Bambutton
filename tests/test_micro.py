"""Host-side tests for the Bambutton multi-station firmware.

These run under CPython using the light-weight fakes in tests/fakes/
(machine, network, urequests) that stand in for the MicroPython runtime, so
no board and no network are required:

    python tests/test_micro.py

They cover the config schema (incl. legacy migration), printer-name
resolution, the on-device web/setup layer, the boot decision and the
per-station LED logic.
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fakes"))
sys.path.insert(0, os.path.join(HERE, "..", "micro"))

import config_loader
import bb_util
import webconfig
import main
import runner


# ---------------------------------------------------------------------------
# config_loader
# ---------------------------------------------------------------------------
def test_defaults():
    cfg = config_loader.load_config(os.path.join(tempfile.mkdtemp(), "none.json"))
    assert len(cfg["stations"]) == 2
    assert cfg["update"]["url"] == ""
    assert cfg["ap"]["ssid"] == "Bambutton-Setup"
    print("defaults OK")


def test_config_complete():
    complete = {"wifi": {"ssid": "HomeWiFi"},
                "api": {"base_url": "http://192.168.1.50:8000/api/v1", "key": "k"},
                "stations": [{"printer_id": "X1C"}, {"printer_id": ""}]}
    assert config_loader.config_complete(complete) is True
    assert config_loader.config_complete(
        {"wifi": {"ssid": ""}, "api": {}, "stations": []}) is False
    no_printer = dict(complete)
    no_printer["stations"] = [{"printer_id": ""}, {"printer_id": ""}]
    assert config_loader.config_complete(no_printer) is False
    print("config_complete OK")


def test_legacy_migration():
    # An old single-printer config (as the desktop assistant writes) must keep
    # working: printer{}/led.pin/button.pin fold into station 0.
    path = os.path.join(tempfile.mkdtemp(), "config.json")
    with open(path, "w") as f:
        json.dump({"wifi": {"ssid": "HomeWiFi", "password": "p"},
                   "api": {"base_url": "http://192.168.1.50:8000/api/v1", "key": "k"},
                   "printer": {"id": 7, "poll_interval_seconds": 5},
                   "led": {"pin": 8}, "button": {"pin": 9}}, f)
    cfg = config_loader.load_config(path)
    assert cfg["stations"][0]["printer_id"] == "7"
    assert cfg["stations"][0]["led_pin"] == 8
    assert cfg["stations"][0]["button_pin"] == 9
    assert cfg["poll_interval_seconds"] == 5
    print("legacy_migration OK")


def test_save_load_roundtrip():
    os.chdir(tempfile.mkdtemp())
    cfg = config_loader.load_config("config.json")
    cfg["wifi"]["ssid"] = "HomeWiFi"
    config_loader.save_config(cfg, "config.json")
    assert config_loader.load_config("config.json")["wifi"]["ssid"] == "HomeWiFi"
    print("save_load_roundtrip OK")


# ---------------------------------------------------------------------------
# bb_util
# ---------------------------------------------------------------------------
def test_normalize_base_url():
    n = bb_util.normalize_base_url
    assert n("192.168.1.50:8000") == "http://192.168.1.50:8000/api/v1"
    assert n("http://192.168.1.50:8000") == "http://192.168.1.50:8000/api/v1"
    assert n("http://192.168.1.50:8000/api/v1/") == "http://192.168.1.50:8000/api/v1"
    assert n("") == ""
    print("normalize_base_url OK")


def test_match_printer_id():
    nm = bb_util.build_name_map([{"id": 7, "friendly_name": "BambuLab X1C 3D"},
                                 {"id": 9, "friendly_name": "BambuLab P1S 3D"}])
    assert bb_util.match_printer_id("X1C", nm) == 7        # contains, case-insensitive
    assert bb_util.match_printer_id("p1s", nm) == 9
    assert bb_util.match_printer_id("7", nm) == 7          # numeric passthrough
    assert bb_util.match_printer_id("BambuLab", nm) is None  # ambiguous
    assert bb_util.match_printer_id("nope", nm) is None
    print("match_printer_id OK")


# ---------------------------------------------------------------------------
# webconfig – parsing / rendering / DNS
# ---------------------------------------------------------------------------
def test_parse_and_ipport():
    m, p, h = webconfig.parse_request(b"POST /save HTTP/1.1\r\nContent-Length: 5")
    assert m == "POST" and p == "/save" and h["content-length"] == "5"
    assert webconfig.ip_port_from_base_url(
        "http://192.168.1.50:8000/api/v1") == "192.168.1.50:8000"
    assert webconfig.ip_port_from_base_url("") == ""
    print("parse_and_ipport OK")


def test_dns_captive():
    q = b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03abc\x03com\x00\x00\x01\x00\x01"
    r = webconfig.build_dns_response(q, "192.168.4.1")
    assert r[:2] == b"\xab\xcd" and r[-4:] == bytes([192, 168, 4, 1])
    print("dns_captive OK")


def base_config():
    return config_loader.load_config(os.path.join(tempfile.mkdtemp(), "none.json"))


def test_render_page_normal():
    c = base_config()
    c["wifi"]["ssid"] = "HomeWiFi"
    c["api"]["base_url"] = "http://192.168.1.50:8000/api/v1"
    c["stations"][0]["printer_id"] = "7"
    html = webconfig.render_page(c, "normal")
    assert "<!--INJECT-->" not in html
    assert 'window.MODE="normal"' in html.replace(" ", "")
    assert "192.168.1.50:8000" in html
    assert "HomeWiFi" in html
    print("render_page_normal OK")


def test_route_html_and_scan():
    s, ct, body = webconfig.route("GET", "/", b"", base_config(), {"reset": False})
    assert s.startswith("200") and "text/html" in ct and "Bambutton" in body
    s2, ct2, body2 = webconfig.route("GET", "/scan", b"", base_config(), {"reset": False})
    ssids = [n["ssid"] for n in json.loads(body2)["networks"]]
    assert "HomeWiFi" in ssids and ssids.count("HomeWiFi") == 1   # deduped
    print("route_html_and_scan OK")


# ---------------------------------------------------------------------------
# webconfig – Bambuddy probe / Wi-Fi test (with a fake API)
# ---------------------------------------------------------------------------
class FakeAPI:
    def __init__(self, *a, **k):
        pass

    def get_printers(self):
        return [{"id": 7, "friendly_name": "BambuLab X1C 3D"},
                {"id": 9, "friendly_name": "BambuLab P1S 3D"}]


def test_probe():
    webconfig.bambuddy_api.BambuddyAPI = lambda *a, **k: FakeAPI()
    r = webconfig.do_probe({"host": "192.168.1.50:8000", "key": "k"}, {})
    assert r["ok"] is True and 7 in [p["id"] for p in r["printers"]]
    saved = {"api": {"base_url": "http://192.168.1.50:8000/api/v1", "key": "savedkey"}}
    assert webconfig.do_probe({}, saved)["ok"] is True     # falls back to saved
    assert webconfig.do_probe({}, {})["ok"] is False       # nothing to probe
    print("probe OK")


def test_wifitest():
    webconfig.sta_connect = lambda ssid, pw, timeout=15: True
    r = webconfig.do_wifitest({"ssid": "HomeWiFi", "password": "x"})
    assert r["ok"] is True and r["ip"] == "192.168.4.1"
    webconfig.sta_connect = lambda ssid, pw, timeout=15: False
    assert webconfig.do_wifitest({"ssid": "HomeWiFi", "password": "bad"})["ok"] is False
    assert webconfig.do_wifitest({"ssid": ""})["ok"] is False
    print("wifitest OK")


def test_do_test_combined():
    webconfig.sta_connect = lambda ssid, pw, timeout=15: True
    webconfig.bambuddy_api.BambuddyAPI = lambda *a, **k: FakeAPI()
    r = webconfig.do_test({"ssid": "HomeWiFi", "password": "p",
                           "host": "192.168.1.50:8000", "key": "k"})
    assert r["ok"] is True and "BambuLab X1C 3D" in [p["label"] for p in r["printers"]]
    print("do_test_combined OK")


# ---------------------------------------------------------------------------
# webconfig – save keeps secrets, upload/OTA safety
# ---------------------------------------------------------------------------
def test_save_keeps_secrets():
    os.chdir(tempfile.mkdtemp())
    cfg = base_config()
    cfg["wifi"]["password"] = "oldpw"
    cfg["api"]["key"] = "oldkey"
    cfg["api"]["base_url"] = "http://192.168.1.1:8000/api/v1"
    st = {"reset": False}
    r = webconfig.do_save({"ssid": "HomeWiFi", "password": "", "host": "192.168.1.50:8000",
                           "key": "", "stations": [{"index": 0, "printer_id": "7"},
                                                    {"index": 1, "printer_id": "9"}]}, cfg, st)
    assert r["ok"] is True and st["reset"] is True
    saved = config_loader.load_config("config.json")
    assert saved["wifi"]["password"] == "oldpw"      # blank -> kept
    assert saved["api"]["key"] == "oldkey"           # blank -> kept
    assert saved["api"]["base_url"] == "http://192.168.1.50:8000/api/v1"  # updated
    assert saved["wifi"]["ssid"] == "HomeWiFi"
    assert saved["stations"][0]["printer_id"] == "7" and saved["stations"][1]["printer_id"] == "9"
    print("save_keeps_secrets OK")


def test_upload_path_safety():
    os.chdir(tempfile.mkdtemp())
    assert webconfig.do_upload({"filename": "runner.py", "content": "# NEW\n"})["ok"] is True
    assert open("runner.py").read() == "# NEW\n"
    assert webconfig.do_upload({"filename": "../evil.py", "content": "x"})["ok"] is False
    assert webconfig.do_upload({"filename": "evil.txt", "content": "x"})["ok"] is False
    assert webconfig.do_upload({"filename": "a/b.py", "content": "x"})["ok"] is False
    assert webconfig.do_upload({"filename": "main.py", "content": 123})["ok"] is False
    print("upload_path_safety OK")


def test_ota_update():
    os.chdir(tempfile.mkdtemp())
    manifest = json.dumps({"version": "9.9", "files": ["main.py", "runner.py"]})

    def fake_get(url, timeout=10):
        if url.endswith("/manifest.json"):
            return manifest
        return "# OTA CODE for " + url.rsplit("/", 1)[-1] + "\n"

    webconfig._http_get_text = fake_get
    cfg = base_config()
    st = {"reset": False}
    r = webconfig.do_update({"url": "https://example.test/bb/"}, cfg, st)
    assert r["ok"] is True and r["version"] == "9.9" and st["reset"] is True
    assert set(r["files"]) == {"main.py", "runner.py"}
    assert "OTA CODE for main.py" in open("main.py").read()

    def fake_get_unsafe(url, timeout=10):
        if url.endswith("/manifest.json"):
            return json.dumps({"version": "1", "files": ["../evil.py"]})
        return "x"

    webconfig._http_get_text = fake_get_unsafe
    assert webconfig.do_update({"url": "https://x/"}, base_config(), {"reset": False})["ok"] is False
    print("ota_update OK")


# ---------------------------------------------------------------------------
# main.decide_setup
# ---------------------------------------------------------------------------
def test_decide_setup():
    complete = {"wifi": {"ssid": "HomeWiFi"},
                "api": {"base_url": "h", "key": "k"}, "stations": [{"printer_id": "7"}]}
    assert main.decide_setup(complete, True)[0] is True       # button held
    assert main.decide_setup(complete, False)[0] is False     # runs normally
    assert main.decide_setup({"wifi": {"ssid": ""}}, False)[0] is True  # no Wi-Fi
    print("decide_setup OK")


# ---------------------------------------------------------------------------
# runner – stations, LED logic, identify, id resolution
# ---------------------------------------------------------------------------
def two_stations(a="", b=""):
    return {"button": {}, "stations": [
        {"printer_id": a, "led_pin": 3, "button_pin": 4},
        {"printer_id": b, "led_pin": 5, "button_pin": 6}]}


def test_build_stations_active_flags():
    sts = runner.build_stations(two_stations("X1C", ""))
    assert len(sts) == 2 and sts[0].active is True and sts[1].active is False
    print("build_stations_active_flags OK")


def test_led_inactive_is_dark():
    st = runner.build_stations(two_stations("", ""))[0]
    st.led.value(1)
    st.update_led()
    assert st.led.value() == 0
    print("led_inactive_is_dark OK")


def test_led_identify_blinks_even_when_inactive():
    st = runner.build_stations(two_stations("", ""))[0]
    st.led.value(0)
    st.identify(4)
    st.update_led(); assert st.led.value() == 1
    st.update_led(); assert st.led.value() == 0
    st.identify_until = runner._now_ms() - 100   # window elapsed
    st.update_led(); assert st.led.value() == 0
    print("led_identify_blinks OK")


def test_led_active_follows_chamber_and_awaiting():
    st = runner.build_stations(two_stations("X1C", ""))[0]
    st.printer_id = 7
    st.awaiting_plate_clear = False
    st.chamber_light_on = True
    st.update_led(); assert st.led.value() == 1        # chamber on -> steady on
    st.chamber_light_on = False
    st.update_led(); assert st.led.value() == 0        # chamber off -> off
    st.awaiting_plate_clear = True
    st.led.value(0); st.update_led(); assert st.led.value() == 1   # awaiting -> blink
    print("led_active_logic OK")


def test_build_api_guards():
    assert runner.build_api({"api": {"base_url": "", "key": ""}}) is None
    assert runner.build_api({"api": {"base_url": "192.168.1.50:8000", "key": ""}}) is None
    runner.bambuddy_api.BambuddyAPI = lambda *a, **k: FakeAPI()
    assert runner.build_api({"api": {"base_url": "192.168.1.50:8000", "key": "k"}}) is not None
    print("build_api_guards OK")


class _Net:
    def ensure_connected(self):
        return True


def test_resolve_station_ids():
    st = runner.build_stations(two_stations("X1C", ""))[0]
    api = FakeAPI()
    assert runner.resolve_station_ids(api, _Net(), [st]) is True
    assert st.printer_id == 7
    print("resolve_station_ids OK")


def test_identify_route():
    sts = runner.build_stations(two_stations("X1C", "P1S"))
    ctx = {"mode": "normal", "stations": sts}
    assert webconfig.do_identify({"index": 1}, ctx)["ok"] is True
    assert sts[1].identify_until > 0
    assert webconfig.do_identify({"index": 9}, ctx)["ok"] is False
    assert webconfig.do_identify({"index": 0}, {"mode": "setup"})["ok"] is False
    s, ct, body = webconfig.route("POST", "/identify", b'{"index":0}', {}, {"reset": False}, ctx)
    assert "application/json" in ct and json.loads(body)["ok"] is True
    print("identify_route OK")


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    for fn in ALL:
        fn()
    print("\nALL %d TESTS PASSED" % len(ALL))
