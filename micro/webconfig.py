"""Shared web layer used by both modes:

- Setup mode (AP): full portal (Wi-Fi scan + test + assign printers) via run_setup().
- Normal mode (STA): the same page under the board's LAN IP via Server(), so you
  can re-assign printers or change settings anytime, plus OTA app-code updates
  (browser upload or GitHub pull).

route()/parse/handlers are plain functions so they can be tested off-device.
"""
import time

try:
    import ujson as json
except ImportError:
    import json

try:
    import network
except ImportError:
    network = None
try:
    import machine
except ImportError:
    machine = None
try:
    import urequests
except ImportError:
    urequests = None

import bambuddy_api
import config_loader
import bb_util


VERSION = "2.3.0"
AP_IP = "192.168.4.1"
ALLOWED_UPLOAD_SUFFIX = (".py", ".json")

FEED = None  # optional watchdog-feed callback, set by the runner during OTA


def _feed():
    if FEED:
        try:
            FEED()
        except Exception:
            pass


# ---------------------------------------------------------------- HTTP parsing

def parse_request(head_bytes):
    try:
        text = head_bytes.decode("utf-8", "replace")
    except Exception:
        return None
    lines = text.split("\r\n")
    if not lines or " " not in lines[0]:
        return None
    parts = lines[0].split(" ")
    if len(parts) < 2:
        return None
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return parts[0], parts[1], headers


def json_body(body_bytes):
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {}


def ip_port_from_base_url(base_url):
    s = str(base_url or "")
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("/api/v1", "")
    return s.strip("/")


# ------------------------------------------------------------------ Wi-Fi ops

def _sta():
    return network.WLAN(network.STA_IF)


def do_scan():
    sta = _sta()
    sta.active(True)
    try:
        nets = sta.scan()
    except Exception as exc:
        return {"networks": [], "error": str(exc)}
    best = {}
    for n in nets:
        try:
            ssid = n[0].decode("utf-8", "replace")
        except Exception:
            ssid = str(n[0])
        if not ssid:
            continue
        if ssid not in best or n[3] > best[ssid][0]:
            best[ssid] = (n[3], n[2])
    out = [{"ssid": s, "rssi": best[s][0], "ch": best[s][1]}
           for s in sorted(best, key=lambda s: best[s][0], reverse=True)]
    return {"networks": out}


def sta_connect(ssid, password, timeout=15):
    sta = _sta()
    sta.active(True)
    if sta.isconnected():
        try:
            sta.disconnect()
        except Exception:
            pass
        time.sleep(0.3)
    sta.connect(ssid, password)
    ticks = time.ticks_ms if hasattr(time, "ticks_ms") else (lambda: int(time.time() * 1000))
    diff = time.ticks_diff if hasattr(time, "ticks_diff") else (lambda a, b: a - b)
    t0 = ticks()
    while not sta.isconnected():
        if diff(ticks(), t0) > timeout * 1000:
            return False
        time.sleep(0.25)
    return True


def _api_from_config(config):
    return bambuddy_api.BambuddyAPI(
        config["api"]["key"],
        bb_util.normalize_base_url(config["api"]["base_url"]),
        config["api"].get("request_timeout_seconds", 5),
    )


def _printers_payload(api):
    out = []
    for p in bb_util.extract_list(api.get_printers()):
        if isinstance(p, dict) and "id" in p:
            out.append({"id": p["id"], "label": bb_util.printer_label(p)})
    return out


def do_test(params):
    ssid = str(params.get("ssid", "")).strip()
    password = str(params.get("password", ""))
    host = str(params.get("host", "")).strip()
    key = str(params.get("key", "")).strip()
    if not ssid or not host or not key:
        return {"ok": False, "error": "SSID, Bambuddy-Adresse und API-Key noetig."}
    if not sta_connect(ssid, password):
        return {"ok": False, "error": "WLAN-Verbindung fehlgeschlagen (SSID/Passwort pruefen)."}
    api = bambuddy_api.BambuddyAPI(key, bb_util.normalize_base_url(host), 6)
    try:
        return {"ok": True, "printers": _printers_payload(api)}
    except Exception as exc:
        return {"ok": False, "error": "Bambuddy nicht erreichbar / Key falsch: %s" % exc}


def do_printers(config, ctx):
    api = ctx.get("api") if ctx else None
    if api is None:
        api = _api_from_config(config)
    try:
        return {"ok": True, "printers": _printers_payload(api)}
    except Exception as exc:
        return {"ok": False, "error": "Druckerliste nicht abrufbar: %s" % exc}


def do_wifitest(params):
    ssid = str(params.get("ssid", "")).strip()
    password = str(params.get("password", ""))
    if not ssid:
        return {"ok": False, "error": "Bitte WLAN waehlen."}
    if not sta_connect(ssid, password):
        return {"ok": False, "error": "WLAN-Verbindung fehlgeschlagen (Passwort pruefen)."}
    ip = ""
    try:
        ip = _sta().ifconfig()[0]
    except Exception:
        ip = ""
    return {"ok": True, "ip": ip}


def do_probe(params, config):
    host = str(params.get("host", "")).strip()
    base = host if host else str(config.get("api", {}).get("base_url", "")).strip()
    key = str(params.get("key", "")).strip() or str(config.get("api", {}).get("key", "")).strip()
    if not base or not key:
        return {"ok": False, "error": "Bambuddy-Adresse und API-Key eingeben."}
    api = bambuddy_api.BambuddyAPI(key, bb_util.normalize_base_url(base), 6)
    try:
        return {"ok": True, "printers": _printers_payload(api)}
    except Exception as exc:
        return {"ok": False, "error": "Bambuddy nicht erreichbar / Key falsch: %s" % exc}


def _keep(new, old):
    new = "" if new is None else str(new)
    return new if new.strip() != "" else old


def do_save(params, config, state):
    wifi = config.setdefault("wifi", {})
    api = config.setdefault("api", {})
    wifi["ssid"] = _keep(params.get("ssid"), wifi.get("ssid", ""))
    wifi["password"] = _keep(params.get("password"), wifi.get("password", ""))
    host = params.get("host")
    if host is not None and str(host).strip() != "":
        api["base_url"] = bb_util.normalize_base_url(str(host).strip())
    api["key"] = _keep(params.get("key"), api.get("key", ""))
    if "update_url" in params:
        config.setdefault("update", {})["url"] = str(params.get("update_url", "")).strip()

    by_index = {}
    for a in params.get("stations", []):
        try:
            by_index[int(a.get("index"))] = a.get("printer_id", "")
        except Exception:
            pass
    for i, st in enumerate(config.get("stations", [])):
        if i in by_index:
            st["printer_id"] = by_index[i]

    try:
        config_loader.save_config(config)
    except Exception as exc:
        return {"ok": False, "error": "Speichern fehlgeschlagen: %s" % exc}
    state["reset"] = True
    return {"ok": True}


def _safe_name(filename):
    fn = str(filename or "").strip()
    if not fn or "/" in fn or "\\" in fn or ".." in fn:
        return None
    if not fn.endswith(ALLOWED_UPLOAD_SUFFIX):
        return None
    return fn


def do_upload(params):
    fn = _safe_name(params.get("filename"))
    if fn is None:
        return {"ok": False, "error": "Ungueltiger Dateiname (nur .py/.json, kein Pfad)."}
    content = params.get("content")
    if not isinstance(content, str):
        return {"ok": False, "error": "Kein Textinhalt."}
    try:
        with open(fn, "w") as f:
            f.write(content)
    except Exception as exc:
        return {"ok": False, "error": "Schreiben fehlgeschlagen: %s" % exc}
    return {"ok": True, "file": fn, "bytes": len(content)}


def _http_get_text(url, timeout=10):
    resp = urequests.get(url, timeout=timeout) if urequests else None
    if resp is None:
        raise RuntimeError("kein HTTP-Client")
    try:
        code = getattr(resp, "status_code", 200)
        text = resp.text
    finally:
        try:
            resp.close()
        except Exception:
            pass
    if code < 200 or code >= 300:
        raise RuntimeError("HTTP %s fuer %s" % (code, url))
    return text


def do_update(params, config, state):
    url = str(params.get("url", "")).strip() or config.get("update", {}).get("url", "")
    url = url.rstrip("/")
    if not url:
        return {"ok": False, "error": "Keine Update-URL gesetzt."}
    config.setdefault("update", {})["url"] = url
    try:
        manifest = json.loads(_http_get_text(url + "/manifest.json"))
    except Exception as exc:
        return {"ok": False, "error": "Manifest nicht ladbar: %s" % exc}
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list) or not files:
        return {"ok": False, "error": "Manifest ohne Dateiliste."}
    written = []
    for name in files:
        _feed()
        fn = _safe_name(name)
        if fn is None:
            return {"ok": False, "error": "Manifest enthaelt unsicheren Namen: %s" % name}
        try:
            text = _http_get_text(url + "/" + fn)
        except Exception as exc:
            return {"ok": False, "error": "Datei %s nicht ladbar: %s" % (fn, exc)}
        try:
            with open(fn, "w") as f:
                f.write(text)
        except Exception as exc:
            return {"ok": False, "error": "Schreiben %s fehlgeschlagen: %s" % (fn, exc)}
        written.append(fn)
    try:
        config_loader.save_config(config)
    except Exception:
        pass
    state["reset"] = True
    return {"ok": True, "version": manifest.get("version", "?"), "files": written}


def do_reboot(state):
    state["reset"] = True
    return {"ok": True}


def do_identify(params, ctx):
    """Blink a station's LED so the user can see which physical button it is."""
    stations = ctx.get("stations") if ctx else None
    if not stations:
        return {"ok": False, "error": "Nur im Normalbetrieb verfuegbar."}
    try:
        idx = int(params.get("index"))
    except Exception:
        return {"ok": False, "error": "index fehlt"}
    seconds = params.get("seconds", 4)
    for st in stations:
        if getattr(st, "index", None) == idx:
            try:
                st.identify(seconds)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True}
    return {"ok": False, "error": "Station %s nicht gefunden" % idx}


def do_status(config, ctx):
    ip = ""
    try:
        if network:
            ip = _sta().ifconfig()[0]
    except Exception:
        ip = ""
    return {"version": VERSION, "mode": ctx.get("mode") if ctx else "?", "ip": ip}


# ---------------------------------------------------------------- HTTP routing

def route(method, path, body_bytes, config, state, ctx=None):
    ctx = ctx or {"mode": "setup"}
    p = path.split("?", 1)[0]
    if p == "/scan":
        return _json(do_scan())
    if p == "/printers":
        return _json(do_printers(config, ctx))
    if p == "/status":
        return _json(do_status(config, ctx))
    if p == "/probe" and method == "POST":
        return _json(do_probe(json_body(body_bytes), config))
    if p == "/wifitest" and method == "POST":
        return _json(do_wifitest(json_body(body_bytes)))
    if p == "/test" and method == "POST":
        return _json(do_test(json_body(body_bytes)))
    if p == "/save" and method == "POST":
        return _json(do_save(json_body(body_bytes), config, state))
    if p == "/update" and method == "POST":
        return _json(do_update(json_body(body_bytes), config, state))
    if p == "/upload" and method == "POST":
        return _json(do_upload(json_body(body_bytes)))
    if p == "/reboot" and method == "POST":
        return _json(do_reboot(state))
    if p == "/identify" and method == "POST":
        return _json(do_identify(json_body(body_bytes), ctx))
    return "200 OK", "text/html; charset=utf-8", render_page(config, ctx.get("mode", "setup"))


def _json(obj):
    return "200 OK", "application/json", json.dumps(obj)


def render_page(config, mode):
    cfg = {
        "ssid": config.get("wifi", {}).get("ssid", ""),
        "host": ip_port_from_base_url(config.get("api", {}).get("base_url", "")),
        "update_url": config.get("update", {}).get("url", ""),
        "stations": [{"index": i, "printer_id": st.get("printer_id", "")}
                     for i, st in enumerate(config.get("stations", []))],
    }
    inject = "<script>window.MODE=%s;window.VERSION=%s;window.CFG=%s;</script>" % (
        json.dumps(mode), json.dumps(VERSION), json.dumps(cfg))
    return PAGE.replace("<!--INJECT-->", inject)


# ------------------------------------------------------------------- DNS (A->AP)

def build_dns_response(query, ip):
    if len(query) < 12:
        return None
    tid = query[0:2]
    counts = query[4:6] + b"\x00\x01" + b"\x00\x00" + b"\x00\x00"
    idx = 12
    while idx < len(query) and query[idx] != 0:
        idx += 1 + query[idx]
    idx += 1
    question = query[12:idx + 4]
    try:
        ipb = bytes(int(x) for x in ip.split("."))
    except Exception:
        return None
    answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + ipb
    return tid + b"\x81\x80" + counts + question + answer


# --------------------------------------------------------------- socket helpers

def read_http(conn):
    conn.settimeout(6)
    data = b""
    try:
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(512)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                break
    except Exception:
        pass
    if not data:
        return None, None, None, b""
    head, _, rest = data.partition(b"\r\n\r\n")
    parsed = parse_request(head)
    if not parsed:
        return None, None, None, b""
    method, path, headers = parsed
    body = rest
    try:
        total = int(headers.get("content-length", "0"))
    except Exception:
        total = 0
    try:
        while len(body) < total:
            chunk = conn.recv(1024)
            if not chunk:
                break
            body += chunk
    except Exception:
        pass
    return method, path, headers, body


def send_http(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    header = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
              "Connection: close\r\nCache-Control: no-store\r\n\r\n") % (status, ctype, len(body))
    try:
        conn.send(header.encode("utf-8") + body)
    except Exception:
        pass


# --------------------------------------------------------------- setup-mode run

def start_ap(config):
    ap_cfg = config.get("ap", {})
    ssid = ap_cfg.get("ssid", "Bambutton-Setup")
    password = ap_cfg.get("password", "bambutton")
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try:
        ap.config(essid=ssid, password=password, authmode=getattr(network, "AUTH_WPA2_PSK", 3))
    except Exception:
        try:
            ap.config(essid=ssid, password=password)
        except Exception:
            ap.config(essid=ssid)
    return ap


def run_setup(config):
    import socket
    import select

    ap = start_ap(config)
    try:
        print("Setup-AP aktiv:", ap.config("essid"), "-> http://%s/" % ap.ifconfig()[0])
    except Exception:
        print("Setup-AP aktiv -> http://%s/" % AP_IP)

    http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http.bind(("0.0.0.0", 80))
    http.listen(4)
    dns = None
    try:
        dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dns.bind(("0.0.0.0", 53))
    except Exception as exc:
        print("DNS aus:", exc)
        dns = None

    poller = select.poll()
    poller.register(http, select.POLLIN)
    if dns:
        poller.register(dns, select.POLLIN)

    ctx = {"mode": "setup"}
    state = {"reset": False}
    print("Portal laeuft. Auf Verbindung warten ...")
    while True:
        for sock, _ev in poller.poll(500):
            if sock is http:
                try:
                    conn, _addr = http.accept()
                    method, path, _h, body = read_http(conn)
                    if method is not None:
                        s, ct, out = route(method, path, body, config, state, ctx)
                        send_http(conn, s, ct, out)
                    conn.close()
                except Exception as exc:
                    print("HTTP-Fehler:", exc)
            elif dns and sock is dns:
                try:
                    data, addr = dns.recvfrom(512)
                    resp = build_dns_response(data, AP_IP)
                    if resp:
                        dns.sendto(resp, addr)
                except Exception:
                    pass
        if state["reset"]:
            print("Gespeichert. Neustart in 1s ...")
            time.sleep(1)
            if machine:
                machine.reset()
            return


# ------------------------------------------------------ normal-mode (non-block)

class Server:
    """Non-blocking config server for normal mode; poll() from the main loop."""

    def __init__(self, config, ctx):
        import socket
        self.config = config
        self.ctx = ctx
        self.state = {"reset": False}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", 80))
        self.sock.listen(2)
        self.sock.settimeout(0)

    def poll(self):
        try:
            conn, _addr = self.sock.accept()
        except Exception:
            return False
        try:
            method, path, _h, body = read_http(conn)
            if method is not None:
                s, ct, out = route(method, path, body, self.config, self.state, self.ctx)
                send_http(conn, s, ct, out)
        except Exception as exc:
            print("Web-Fehler:", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return self.state["reset"]


PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bambutton</title><!--INJECT-->
<style>
:root{--bg:#0f172a;--card:#fff;--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--acc:#2563eb;--ok:#059669;--err:#dc2626}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,Segoe UI,Arial,sans-serif}
.wrap{max-width:520px;margin:0 auto;padding:16px}
h1{color:#fff;font-size:20px;margin:12px 4px}.sub{color:#94a3b8;margin:0 4px 14px;font-size:13px}
.badge{display:inline-block;font-size:11px;color:#cbd5e1;border:1px solid #334155;border-radius:999px;padding:2px 8px;margin-left:6px}
.card{background:var(--card);border-radius:14px;padding:16px;margin:12px 0;box-shadow:0 6px 20px rgba(0,0,0,.25)}
.step{font-size:12px;font-weight:700;color:var(--acc);letter-spacing:.04em;text-transform:uppercase;margin:0 0 8px}
label{display:block;font-size:13px;color:var(--mut);margin:10px 0 4px}
input,select{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;font-size:16px;background:#fff;color:var(--ink)}
.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}
button{width:100%;padding:13px;border:0;border-radius:10px;background:var(--acc);color:#fff;font-size:16px;font-weight:600;margin-top:14px}
button:disabled{background:#94a3b8}button.sec{background:#eef2ff;color:var(--acc)}
.msg{margin-top:10px;font-size:14px;padding:10px 12px;border-radius:10px;display:none}
.msg.ok{display:block;background:#ecfdf5;color:var(--ok)}.msg.err{display:block;background:#fef2f2;color:var(--err)}.msg.info{display:block;background:#eff6ff;color:var(--acc)}
.hide{display:none}.pw{position:relative}.pw button{position:absolute;right:6px;top:6px;width:auto;margin:0;padding:6px 10px;background:#eef2ff;color:var(--acc);font-size:12px}
small{color:var(--mut)}hr{border:0;border-top:1px solid var(--line);margin:14px 0}
</style></head><body><div class="wrap">
<h1>Bambutton <span class="badge" id="verBadge"></span></h1>
<p class="sub" id="lead">WLAN & Bambuddy einrichten, dann Drucker den Knöpfen zuordnen.</p>

<div class="card">
  <p class="step">1 · WLAN</p>
  <label>Netzwerk</label>
  <div class="row">
    <select id="ssidSel"><option value="">— Netz wählen —</option><option value="__manual__">andere (manuell)…</option></select>
    <button class="sec" style="flex:0 0 auto;width:auto;margin:0" onclick="loadScan()">↻</button>
  </div>
  <input id="ssidManual" class="hide" placeholder="WLAN-Name (SSID)" style="margin-top:8px">
  <label>Passwort</label>
  <div class="pw"><input id="pw" type="password" placeholder="WLAN-Passwort"><button onclick="togglePw()">zeigen</button></div>
  <button onclick="wifiSave()" id="btnWifi" class="hide">WLAN verbinden &amp; speichern</button>
  <div id="wifiMsg" class="msg"></div>
</div>

<div class="card">
  <p class="step">2 · Bambuddy</p>
  <label>Adresse (IP:Port)</label>
  <input id="host" placeholder="z. B. 192.168.1.50:8000" inputmode="url">
  <label>API-Key</label>
  <input id="key" placeholder="Bambuddy API-Key">
  <button onclick="primaryAction()" id="btnTest">Verbindung testen</button>
  <div id="testMsg" class="msg"></div>
</div>

<div class="card hide" id="cardStations">
  <p class="step">3 · Knöpfe zuordnen</p>
  <label>Knopf A (GP3 / GP4)</label>
  <div class="row"><select id="stA" onchange="identify(0)"></select><button class="sec" style="flex:0 0 auto;width:auto;margin:0" onclick="identify(0)">🔦</button></div>
  <label>Knopf B (GP5 / GP6)</label>
  <div class="row"><select id="stB" onchange="identify(1)"></select><button class="sec" style="flex:0 0 auto;width:auto;margin:0" onclick="identify(1)">🔦</button></div>
  <small>Tipp: 🔦 lässt den passenden Knopf ~4 s blinken.</small>
  <button onclick="save()" id="btnSave">Speichern & Neustart</button>
  <div id="saveMsg" class="msg"></div>
</div>

<div class="card hide" id="cardUpdate">
  <p class="step">4 · Update (OTA)</p>
  <label>Update-URL (GitHub raw, optional)</label>
  <input id="updUrl" placeholder="https://…/ (Ordner mit manifest.json)">
  <button class="sec" onclick="updateGit()" id="btnUpd">Aus dem Internet aktualisieren</button>
  <hr>
  <label>Oder Dateien hochladen (.py / .json)</label>
  <input id="files" type="file" multiple accept=".py,.json">
  <button class="sec" onclick="uploadFiles()" id="btnUpl">Hochladen & Neustart</button>
  <div id="updMsg" class="msg"></div>
</div>
<p class="sub">Beim Verbindungstest kann sich dein Handy kurz neu mit „Bambutton-Setup" verbinden — das ist normal.</p>
</div>
<script>
var MODE=window.MODE||'setup',CFG=window.CFG||{},VERSION=window.VERSION||'';
var printers=[];
function $(i){return document.getElementById(i)}
function togglePw(){var i=$('pw');i.type=i.type==='password'?'text':'password'}
$('ssidSel').addEventListener('change',function(){$('ssidManual').classList.toggle('hide',this.value!=='__manual__')});
function ssidVal(){var s=$('ssidSel').value;return s==='__manual__'?$('ssidManual').value.trim():s}
function setMsg(id,cls,txt){var m=$(id);m.className='msg '+cls;m.textContent=txt}
function loadScan(){fetch('/scan').then(r=>r.json()).then(function(d){
  var s=$('ssidSel'),cur=s.value;s.innerHTML='<option value="">— Netz wählen —</option>';
  (d.networks||[]).forEach(function(n){var o=document.createElement('option');o.value=n.ssid;o.textContent=n.ssid+'  ('+n.rssi+' dBm)';s.appendChild(o)});
  var m=document.createElement('option');m.value='__manual__';m.textContent='andere (manuell)…';s.appendChild(m);
  if(cur)s.value=cur;
}).catch(function(){})}
function opts(sel,cur){var s=$(sel);s.innerHTML='<option value="">— kein Drucker —</option>';
  printers.forEach(function(p){var o=document.createElement('option');o.value=p.id;o.textContent=p.label;s.appendChild(o)});
  if(cur!==undefined&&cur!==null&&cur!=='')s.value=String(cur)}
function stCur(i){var a=(CFG.stations||[]).filter(function(x){return x.index===i});return a.length?a[0].printer_id:''}
function fillStations(){opts('stA',stCur(0));opts('stB',stCur(1))}
function identify(i){fetch('/identify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i})}).catch(function(){})}
function primaryAction(){if(MODE==='normal'){loadPrinters()}else{testConn()}}
function testConn(){setMsg('testMsg','info','Teste… (kann ~15 s dauern)');$('btnTest').disabled=true;
  var b={ssid:ssidVal(),password:$('pw').value,host:$('host').value.trim(),key:$('key').value.trim()};
  fetch('/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json()).then(function(d){
    $('btnTest').disabled=false;
    if(d.ok){printers=d.printers||[];setMsg('testMsg','ok','Verbunden! '+printers.length+' Drucker gefunden.');fillStations();$('cardStations').classList.remove('hide')}
    else{setMsg('testMsg','err',d.error||'Fehlgeschlagen.')}
  }).catch(function(){$('btnTest').disabled=false;setMsg('testMsg','err','Keine Antwort (Handy evtl. kurz getrennt) — nochmal.')})}
function loadPrinters(){setMsg('testMsg','info','Lade Drucker…');$('btnTest').disabled=true;
  fetch('/probe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({host:$('host').value.trim(),key:$('key').value.trim()})}).then(r=>r.json()).then(function(d){$('btnTest').disabled=false;
    if(d.ok){printers=d.printers||[];setMsg('testMsg','ok',printers.length+' Drucker geladen.');fillStations();$('cardStations').classList.remove('hide')}
    else{setMsg('testMsg','err',d.error||'Fehlgeschlagen.')}
  }).catch(function(){$('btnTest').disabled=false;setMsg('testMsg','err','Nicht ladbar.')})}
function wifiSave(){var s=ssidVal();if(!s){setMsg('wifiMsg','err','Bitte WLAN wählen.');return}
  setMsg('wifiMsg','info','Verbinde… (~15 s)');$('btnWifi').disabled=true;
  fetch('/wifitest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:s,password:$('pw').value})}).then(r=>r.json()).then(function(d){
    if(!d.ok){$('btnWifi').disabled=false;setMsg('wifiMsg','err',d.error||'WLAN fehlgeschlagen.');return}
    var ip=d.ip||'?';setMsg('wifiMsg','info','Verbunden ('+ip+'). Speichere…');
    fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:s,password:$('pw').value})}).then(r=>r.json()).then(function(){
      setMsg('wifiMsg','ok','Gespeichert! Der Button startet neu und ist dann unter http://'+ip+'/ erreichbar — dort am PC Bambuddy + Drucker einrichten.');
    }).catch(function(){setMsg('wifiMsg','ok','Gespeichert — Neustart. Danach unter http://'+ip+'/ erreichbar.');});
  }).catch(function(){$('btnWifi').disabled=false;setMsg('wifiMsg','err','Keine Antwort — bitte nochmal.')});}
function save(){setMsg('saveMsg','info','Speichere…');$('btnSave').disabled=true;
  var b={ssid:ssidVal(),password:$('pw').value,host:$('host').value.trim(),key:$('key').value.trim(),
    stations:[{index:0,printer_id:$('stA').value},{index:1,printer_id:$('stB').value}]};
  fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json()).then(function(d){
    if(d.ok){setMsg('saveMsg','ok','Gespeichert! Button startet neu. Fenster kann zu.')}else{$('btnSave').disabled=false;setMsg('saveMsg','err',d.error||'Fehler.')}
  }).catch(function(){setMsg('saveMsg','ok','Gespeichert — Button startet neu (Verbindung getrennt).')})}
function updateGit(){setMsg('updMsg','info','Hole Update…');$('btnUpd').disabled=true;
  fetch('/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:$('updUrl').value.trim()})}).then(r=>r.json()).then(function(d){
    if(d.ok){setMsg('updMsg','ok','Update '+(d.version||'')+' geladen ('+(d.files||[]).length+' Dateien). Neustart…')}
    else{$('btnUpd').disabled=false;setMsg('updMsg','err',d.error||'Fehler.')}
  }).catch(function(){setMsg('updMsg','ok','Vermutlich aktualisiert — Button startet neu.')})}
function uploadFiles(){var fs=$('files').files;if(!fs.length){setMsg('updMsg','err','Keine Dateien gewählt.');return}
  setMsg('updMsg','info','Lade hoch…');$('btnUpl').disabled=true;var arr=[].slice.call(fs);
  function one(i){if(i>=arr.length){fetch('/reboot',{method:'POST'});setMsg('updMsg','ok',arr.length+' Dateien hochgeladen. Neustart…');return}
    var f=arr[i],rd=new FileReader();rd.onload=function(){
      fetch('/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:f.name,content:rd.result})})
       .then(r=>r.json()).then(function(d){if(!d.ok){$('btnUpl').disabled=false;setMsg('updMsg','err',f.name+': '+(d.error||'Fehler'))}else{one(i+1)}})
       .catch(function(){$('btnUpl').disabled=false;setMsg('updMsg','err','Upload-Fehler bei '+f.name)})};
    rd.readAsText(f)}
  one(0)}
(function init(){
  $('verBadge').textContent='v'+VERSION;
  if(MODE==='normal'){
    $('lead').textContent='Verbunden. Drucker neu zuordnen, Einstellungen ändern oder aktualisieren.';
    if(CFG.ssid){var s=$('ssidSel');var o=document.createElement('option');o.value=CFG.ssid;o.textContent=CFG.ssid+' (aktuell)';s.appendChild(o);s.value=CFG.ssid}
    $('pw').placeholder='unverändert lassen';
    $('host').value=CFG.host||'';$('key').placeholder='unverändert lassen';
    $('btnTest').textContent='Drucker neu laden';
    $('updUrl').value=CFG.update_url||'';
    $('cardUpdate').classList.remove('hide');
    loadPrinters();loadScan();
  }else{
    $('lead').textContent='Nur WLAN wählen und speichern — Bambuddy + Drucker richtest du danach bequem am PC über die Button-IP ein.';
    $('btnWifi').classList.remove('hide');
    loadScan();
  }
})();
</script></body></html>"""
