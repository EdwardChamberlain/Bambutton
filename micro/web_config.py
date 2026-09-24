import socket

try:
    import ujson as json
except ImportError:
    import json

try:
    import ubinascii as _base64
except ImportError:
    import base64 as _base64

try:
    import ota_manager
    import config_loader
except ImportError:
    from micro import ota_manager, config_loader

save_config = config_loader.save_config


CONFIG_PATH = "config.json"
DEFAULT_HOSTNAME = "bambutton"
DEFAULT_WEB_PASSWORD = "bambutton"
WEB_AUTH_USERNAME = "admin"
MAX_REQUEST_BYTES = 128 * 1024


class WebConfigServer:
    """Small polled configuration server for the MicroPython board.

    The server is deliberately polled from the main loop instead of running a
    second thread. That keeps configuration writes and application state in one
    execution context while the server is available on station or AP Wi-Fi.
    """

    def __init__(
        self,
        config,
        api,
        status_provider=None,
        config_path=CONFIG_PATH,
        host="0.0.0.0",
        port=80,
        socket_module=socket,
        update_manager=None,
    ):
        self.config = config
        self.api = api
        self.status_provider = status_provider or (lambda: {})
        self.config_path = config_path
        self.socket_module = socket_module
        self.update_manager = update_manager or ota_manager.OTAUpdateManager()
        self.restart_requested = False

        self.listener = socket_module.socket()
        try:
            self.listener.setsockopt(
                socket_module.SOL_SOCKET,
                socket_module.SO_REUSEADDR,
                1,
            )
        except (AttributeError, OSError):
            pass

        self.listener.bind((host, port))
        self.listener.listen(1)
        self.listener.settimeout(0)

    def close(self):
        if self.listener is not None:
            self.listener.close()
            self.listener = None

    def poll(self):
        """Handle at most one browser request without blocking the main loop."""
        if self.listener is None:
            return False

        client = None
        try:
            client, _address = self.listener.accept()
            client.settimeout(0.25)
            method, path, body, headers = _read_request(client)
            status, content_type, response_body = self.handle_request(
                method,
                path,
                body,
                headers,
            )
            response_headers = {}
            if status == 401:
                response_headers["WWW-Authenticate"] = 'Basic realm="Bambutton"'
            _send_response(client, status, content_type, response_body, response_headers)
        except OSError:
            # A non-blocking listener reports no pending connection as OSError.
            # Request-level socket errors are also safe to ignore: the next
            # browser request can retry without affecting the button loop.
            pass
        except Exception as exc:
            if client is not None:
                try:
                    _send_response(
                        client,
                        500,
                        "text/html; charset=utf-8",
                        _error_page("Web configuration error", str(exc)),
                    )
                except OSError:
                    pass
        finally:
            if client is not None:
                client.close()

        restart_requested = self.restart_requested
        self.restart_requested = False
        return restart_requested

    def handle_request(self, method, path, body="", headers=None):
        update_manager = self._get_update_manager()
        if not self._is_authorized(headers or {}):
            return 401, "text/html; charset=utf-8", _error_page(
                "Authentication required",
                "Enter the configured web password to access this board.",
            )

        route = path.split("?", 1)[0]

        if method == "GET" and route in ("/", "/index.html"):
            message = ""
            if "saved=1" in path:
                message = "Settings saved. The board will restart to apply them."
            return 200, "text/html; charset=utf-8", render_config_page(
                self.config,
                message,
                update_manager.status(),
            )

        if method == "GET" and route == "/update":
            return 200, "text/html; charset=utf-8", render_update_page(
                update_manager.status()
            )

        if method == "GET" and route == "/api/update/status":
            return 200, "application/json", _json_dumps(
                update_manager.status()
            )

        if method == "POST" and route == "/api/update/check":
            try:
                status = update_manager.check_remote()
                return 200, "application/json", _json_dumps(status)
            except ota_manager.OTAError as exc:
                return 400, "application/json", _json_dumps({"error": str(exc)})
            except Exception as exc:
                return 502, "application/json", _json_dumps({"error": str(exc)})

        if method == "POST" and route == "/api/update/upload":
            try:
                status = update_manager.stage_bundle(json.loads(body or "{}"))
                return 200, "application/json", _json_dumps(status)
            except (ValueError, ota_manager.OTAError) as exc:
                return 400, "application/json", _json_dumps({"error": str(exc)})

        if method == "POST" and route == "/api/update/install":
            try:
                status = update_manager.commit_staged()
                self.restart_requested = True
                return 200, "application/json", _json_dumps(status)
            except ota_manager.OTAError as exc:
                return 400, "application/json", _json_dumps({"error": str(exc)})

        if method == "GET" and route == "/debug":
            return 200, "text/html; charset=utf-8", render_debug_page(self.config, self.status_provider())

        if method in ("GET", "POST") and route == "/api/printers":
            try:
                form = parse_form(body) if method == "POST" else {}
                printers = self._get_printers(form)
                return 200, "application/json", _json_dumps(printers)
            except ValueError as exc:
                return 400, "application/json", _json_dumps({"error": str(exc)})
            except Exception as exc:
                return 502, "application/json", _json_dumps({"error": str(exc)})

        if method == "POST" and route == "/save":
            form = parse_form(body)
            try:
                new_config = build_config(form, self.config)
            except ValueError as exc:
                return 400, "text/html; charset=utf-8", _error_page("Invalid configuration", str(exc))
            save_config(self.config_path, new_config)
            self.config = new_config
            self.restart_requested = True
            return 200, "text/html; charset=utf-8", render_config_page(
                self.config,
                "Settings saved. The board will restart to apply them.",
                update_manager.status(),
            )

        return 404, "text/html; charset=utf-8", _error_page("Not found", "The requested page does not exist.")

    def _get_update_manager(self):
        manager = getattr(self, "update_manager", None)
        if manager is None:
            manager = ota_manager.OTAUpdateManager()
            self.update_manager = manager
        return manager

    def _is_authorized(self, headers):
        configured_password = self.config.get("web", {}).get(
            "password",
            DEFAULT_WEB_PASSWORD,
        )
        if not configured_password:
            configured_password = DEFAULT_WEB_PASSWORD
        expected = _basic_auth_header(configured_password)
        return headers.get("authorization", "").strip() == expected

    def _get_printers(self, form):
        if not form:
            return self.api.get_printers()

        api_config = self.config.get("api", {})
        base_url = _required_url(
            _required_text(form, "api_base_url", api_config.get("base_url", ""), "API base URL")
        )
        api_key = _optional_secret(form, "api_key", api_config.get("key", ""))
        request_timeout = api_config.get("request_timeout_seconds", 3)
        api_client = self.api.__class__(api_key, base_url, request_timeout)
        return api_client.get_printers()


def parse_form(body):
    values = {}
    if not body:
        return values

    for item in body.split("&"):
        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key, value = item, ""
        values[_url_decode(key)] = _url_decode(value)

    return values


def build_config(form, current_config):
    config = _copy_dict(current_config)
    wifi = config.setdefault("wifi", {})
    api = config.setdefault("api", {})
    printer = config.setdefault("printer", {})
    led = config.setdefault("led", {})
    button = config.setdefault("button", {})
    web = config.setdefault("web", {})

    wifi["ssid"] = _required_text(form, "wifi_ssid", wifi.get("ssid", ""), "Wi-Fi SSID")
    wifi["password"] = _optional_secret(form, "wifi_password", wifi.get("password", ""))
    wifi["hostname"] = validate_hostname(
        _required_text(form, "hostname", wifi.get("hostname", DEFAULT_HOSTNAME), "Hostname")
    )

    api["base_url"] = _required_url(
        _required_text(form, "api_base_url", api.get("base_url", ""), "API base URL")
    )
    api["key"] = _optional_secret(form, "api_key", api.get("key", ""))

    printer_id = _parse_int(
        _required_text(form, "printer_id", printer.get("id", ""), "Printer"),
        "Printer",
    )
    if printer_id < 1:
        raise ValueError("Printer must be a positive number.")
    printer["id"] = printer_id

    led_pin = _parse_pin(
        _required_text(form, "led_pin", led.get("pin", ""), "LED pin"),
        "LED pin",
    )
    button_pin = _parse_pin(
        _required_text(form, "button_pin", button.get("pin", ""), "Button pin"),
        "Button pin",
    )
    if led_pin == button_pin:
        raise ValueError("LED pin and button pin must be different.")
    led["pin"] = led_pin
    button["pin"] = button_pin
    web["password"] = _optional_secret(
        form,
        "web_password",
        web.get("password", DEFAULT_WEB_PASSWORD) or DEFAULT_WEB_PASSWORD,
    )

    return config


def render_config_page(config, message="", update_status=None):
    wifi = config.get("wifi", {})
    api = config.get("api", {})
    printer = config.get("printer", {})
    led = config.get("led", {})
    button = config.get("button", {})

    saved_message = ""
    if message:
        saved_message = '<p class="message">{}</p>'.format(_escape_html(message))

    content = """
        <h1>Bambutton configuration</h1>
        <p>Configure this board over Wi-Fi. Changes are saved to the board and applied after restart.</p>
        __SAVED_MESSAGE__
        <form method="post" action="/save">
          <fieldset>
            <legend>Network</legend>
            <label>Hostname <input name="hostname" value="__HOSTNAME__" required></label>
            <label>Wi-Fi SSID <input name="wifi_ssid" value="__SSID__" required></label>
            <label>Wi-Fi password <input type="password" name="wifi_password" placeholder="Leave blank to keep current"></label>
          </fieldset>
          <fieldset>
            <legend>Bambuddy API</legend>
            <label>Base URL <input name="api_base_url" value="__BASE_URL__" required></label>
            <label>API key <input id="api_key" type="password" name="api_key" placeholder="Leave blank to keep current"></label>
            <label>Printer
              <select id="printer_id" name="printer_id" required>
                <option value="__PRINTER_ID__">Current printer (__PRINTER_ID__)</option>
              </select>
            </label>
            <button type="button" id="load-printers">Load printers from Bambuddy</button>
            <span id="printer-status"></span>
          </fieldset>
          <fieldset>
            <legend>Button hardware</legend>
            <label>LED pin <input name="led_pin" inputmode="numeric" value="__LED_PIN__" required></label>
            <label>Button pin <input name="button_pin" inputmode="numeric" value="__BUTTON_PIN__" required></label>
          </fieldset>
          <fieldset>
            <legend>Web authentication</legend>
            <p>Requests to this configuration server require this password. Leave it blank to keep the current password.</p>
            <label>Web password <input type="password" name="web_password" placeholder="Leave blank to keep current"></label>
          </fieldset>
          <button type="submit">Save and restart</button>
        </form>
        __UPDATE_SECTION__
        <p><a href="/debug">Open debug information</a></p>
        <script>
          const printerSelect = document.getElementById("printer_id");
          const printerStatus = document.getElementById("printer-status");
          document.getElementById("load-printers").addEventListener("click", async () => {
            printerStatus.textContent = "Loading...";
            try {
              const currentPrinterId = String(printerSelect.value);
              const requestBody = new URLSearchParams();
              requestBody.set("api_base_url", document.querySelector("[name=api_base_url]").value);
              const apiKey = document.getElementById("api_key").value;
              if (apiKey) requestBody.set("api_key", apiKey);
              const response = await fetch("/api/printers", {
                method: "POST",
                headers: {"Content-Type": "application/x-www-form-urlencoded"},
                body: requestBody,
              });
              const data = await response.json();
              if (!response.ok) throw new Error(data.error || "Bambuddy rejected the request");
              const printers = Array.isArray(data) ? data : (data.printers || data.results || data.items || []);
              const validPrinters = printers.filter((printer) => printer.id !== undefined);
              if (!validPrinters.length) throw new Error("No printers returned by Bambuddy");
              printerSelect.replaceChildren();
              let currentPrinterFound = false;
              validPrinters.forEach((printer) => {
                const option = document.createElement("option");
                option.value = printer.id;
                option.selected = String(printer.id) === currentPrinterId;
                currentPrinterFound = currentPrinterFound || option.selected;
                option.textContent = (printer.friendly_name || printer.name || printer.display_name || "Printer") + " (" + printer.id + ")";
                printerSelect.appendChild(option);
              });
              if (!currentPrinterFound && currentPrinterId) {
                const option = document.createElement("option");
                option.value = currentPrinterId;
                option.textContent = "Current printer (" + currentPrinterId + ", not returned)";
                option.selected = true;
                printerSelect.insertBefore(option, printerSelect.firstChild);
              }
              printerStatus.textContent = " Loaded.";
            } catch (error) {
              printerStatus.textContent = " " + error.message;
            }
          });
        </script>
        """
    replacements = {
        "__SAVED_MESSAGE__": saved_message,
        "__HOSTNAME__": _escape_html(wifi.get("hostname", DEFAULT_HOSTNAME)),
        "__SSID__": _escape_html(wifi.get("ssid", "")),
        "__BASE_URL__": _escape_html(api.get("base_url", "")),
        "__PRINTER_ID__": _escape_html(printer.get("id", "")),
        "__LED_PIN__": _escape_html(led.get("pin", "")),
        "__BUTTON_PIN__": _escape_html(button.get("pin", "")),
        "__UPDATE_SECTION__": render_update_section(update_status or {}),
    }
    for marker, value in replacements.items():
        content = content.replace(marker, value)

    return _page("Bambutton configuration", content)


def render_update_page(status):
    return _page(
        "Bambutton update",
        "<h1>Bambutton application update</h1>{}<p><a href=\"/\">Back to configuration</a></p>".format(
            render_update_section(status)
        ),
    )


def render_update_section(status):
    status = status if isinstance(status, dict) else {}
    current = _escape_html(status.get("current_version") or "legacy/unknown")
    active_slot = _escape_html(status.get("active_slot") or "legacy")
    inactive_slot = "app_b" if status.get("active_slot") == "app_a" else "app_a"
    slots = status.get("slots", {})
    if not isinstance(slots, dict):
        slots = {}
    inactive_status = slots.get(inactive_slot, {})
    if not isinstance(inactive_status, dict):
        inactive_status = {}
    inactive_state = (
        "staged"
        if status.get("staged_slot") == inactive_slot
        else "ready" if inactive_status.get("ready") else "empty"
    )
    inactive_summary = "{} — {}".format(inactive_slot, inactive_state)
    if inactive_status.get("version"):
        inactive_summary += " (version {})".format(
            inactive_status["version"]
        )
    inactive_summary = _escape_html(inactive_summary)
    install_disabled = (
        ""
        if status.get("staged_slot") in ota_manager.SLOT_NAMES
        else " disabled"
    )
    error = status.get("last_error") or {}
    error_text = error.get("message", "") if isinstance(error, dict) else str(error)
    error_html = (
        '<p class="error">Last update error: {}</p>'.format(_escape_html(error_text))
        if error_text else ""
    )
    return """
        <fieldset id="updates">
          <legend>Application updates</legend>
          <p>Current version: <strong id="update-version">{current}</strong></p>
          <p>Active slot: <strong id="update-slot">{slot}</strong></p>
          <p>Inactive slot: <strong id="update-inactive-slot">{inactive}</strong></p>
          <p>Updates replace application files only in the inactive application slot. Your Wi-Fi, API, printer, and web settings are preserved.</p>
          <p><strong>Warning:</strong> anyone who can access this authenticated LAN page can install an application update.</p>
          {error}
          <button type="button" id="check-update">Check official release</button>
          <label>Local update bundle
            <input id="update-file" type="file" accept="application/json,.json">
          </label>
          <button type="button" id="upload-update">Stage local bundle</button>
          <p id="update-status" aria-live="polite"></p>
          <progress id="update-progress" max="100" value="0" hidden style="width: 100%" aria-label="Update progress"></progress>
          <button type="button" id="install-update"{install_disabled}>Install staged update and restart</button>
          <p><a href="/update">Open update page</a></p>
        </fieldset>
        <script>
          const updateStatus = document.getElementById("update-status");
          const installButton = document.getElementById("install-update");
          const inactiveSlotStatus = document.getElementById("update-inactive-slot");
          const progress = document.getElementById("update-progress");
          const setUpdateStatus = (message) => {{ updateStatus.textContent = message; }};
          const showIndeterminateProgress = () => {{
            progress.hidden = false;
            progress.removeAttribute("value");
          }};
          const hideProgress = () => {{
            progress.hidden = true;
            progress.max = 100;
            progress.value = 0;
          }};
          const updateRequest = async (path, options) => {{
            const response = await fetch(path, options || {{}});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Update request failed");
            return data;
          }};
          const updateSlotStatus = (data) => {{
            const inactive = data.active_slot === "app_a" ? "app_b" : "app_a";
            const slot = (data.slots || {{}})[inactive] || {{}};
            const state = data.staged_slot === inactive ? "staged" : slot.ready ? "ready" : "empty";
            const version = slot.version ? " (version " + slot.version + ")" : "";
            inactiveSlotStatus.textContent = inactive + " — " + state + version;
            installButton.disabled = !data.staged_slot;
          }};
          const staged = (data) => {{
            updateSlotStatus(data);
            hideProgress();
            if (data.staged_slot) setUpdateStatus("Verified update staged in " + data.staged_slot + ".");
          }};
          document.getElementById("check-update").addEventListener("click", async () => {{
            setUpdateStatus("Checking and staging the official release...");
            showIndeterminateProgress();
            try {{ staged(await updateRequest("/api/update/check", {{method: "POST"}})); }}
            catch (error) {{ hideProgress(); setUpdateStatus(error.message); }}
          }});
          const uploadBundle = (body) => new Promise((resolve, reject) => {{
            const request = new XMLHttpRequest();
            request.open("POST", "/api/update/upload");
            request.setRequestHeader("Content-Type", "application/json");
            request.upload.addEventListener("progress", (event) => {{
              if (!event.lengthComputable) {{
                showIndeterminateProgress();
                return;
              }}
              progress.hidden = false;
              progress.max = event.total;
              progress.value = event.loaded;
              const percent = Math.floor(event.loaded * 100 / event.total);
              setUpdateStatus("Uploading local bundle: " + percent + "%");
            }});
            request.upload.addEventListener("load", () => {{
              showIndeterminateProgress();
              setUpdateStatus("Upload complete; verifying and staging...");
            }});
            request.addEventListener("load", () => {{
              let data;
              try {{ data = JSON.parse(request.responseText); }}
              catch (_error) {{ reject(new Error("The device returned an invalid response.")); return; }}
              if (request.status < 200 || request.status >= 300) {{
                reject(new Error(data.error || "Update request failed"));
                return;
              }}
              resolve(data);
            }});
            request.addEventListener("error", () => reject(new Error("The update upload failed.")));
            request.send(body);
          }});
          document.getElementById("upload-update").addEventListener("click", async () => {{
            const file = document.getElementById("update-file").files[0];
            if (!file) {{ setUpdateStatus("Choose a JSON update bundle first."); return; }}
            setUpdateStatus("Uploading and verifying the local bundle...");
            showIndeterminateProgress();
            try {{ staged(await uploadBundle(await file.text())); }}
            catch (error) {{ hideProgress(); setUpdateStatus(error.message); }}
          }});
          installButton.addEventListener("click", async () => {{
            if (!window.confirm("Install the staged application and restart the board?")) return;
            setUpdateStatus("Switching application slots and restarting...");
            installButton.disabled = true;
            showIndeterminateProgress();
            try {{ await updateRequest("/api/update/install", {{method: "POST"}}); }}
            catch (error) {{ hideProgress(); setUpdateStatus(error.message); installButton.disabled = false; }}
          }});
        </script>
    """.format(
        current=current,
        slot=active_slot,
        inactive=inactive_summary,
        install_disabled=install_disabled,
        error=error_html,
    )


def render_debug_page(config, status):
    wifi = config.get("wifi", {})
    api = config.get("api", {})
    printer = config.get("printer", {})
    safe_values = {
        "Configured hostname": wifi.get("hostname", DEFAULT_HOSTNAME),
        "Wi-Fi SSID": wifi.get("ssid", ""),
        "API base URL": api.get("base_url", ""),
        "Printer ID": printer.get("id", ""),
        "LED pin": config.get("led", {}).get("pin", ""),
        "Button pin": config.get("button", {}).get("pin", ""),
    }
    if not isinstance(status, dict):
        status = {"status": status}

    rows = []
    for label, value in safe_values.items():
        rows.append("<tr><th>{}</th><td>{}</td></tr>".format(_escape_html(label), _escape_html(value)))
    for label, value in status.items():
        rows.append("<tr><th>{}</th><td>{}</td></tr>".format(_escape_html(label), _escape_html(value)))

    return _page(
        "Bambutton debug information",
        "<h1>Bambutton debug information</h1><table>{}</table><p><a href=\"/\">Back to configuration</a></p>".format(
            "".join(rows)
        ),
    )


def validate_hostname(hostname):
    if not hostname or len(hostname) > 63:
        raise ValueError("Hostname must be between 1 and 63 characters.")
    if not _is_alphanumeric(hostname[0]) or not _is_alphanumeric(hostname[-1]):
        raise ValueError("Hostname must start and end with a letter or number.")
    for character in hostname:
        if not (_is_alphanumeric(character) or character == "-"):
            raise ValueError("Hostname may contain only letters, numbers, and hyphens.")
    return hostname


def _required_text(form, key, current, label):
    if key not in form:
        value = current
    else:
        value = form[key].strip()
    if not value:
        raise ValueError("{} is required.".format(label))
    return value


def _optional_secret(form, key, current):
    value = form.get(key)
    if value is None or value == "":
        return current
    return value


def _required_url(value):
    if " " in value or not (value.startswith("http://") or value.startswith("https://")):
        raise ValueError("API base URL must start with http:// or https:// and contain no spaces.")
    return value.rstrip("/")


def _parse_int(value, label):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("{} must be a number.".format(label))


def _parse_pin(value, label):
    pin = _parse_int(value, label)
    if pin < 0 or pin > 21:
        raise ValueError("{} must be between 0 and 21.".format(label))
    return pin


def _is_alphanumeric(value):
    return ("a" <= value <= "z") or ("A" <= value <= "Z") or ("0" <= value <= "9")


def _copy_dict(source):
    result = {}
    for key, value in source.items():
        result[key] = _copy_dict(value) if isinstance(value, dict) else value
    return result


def _read_request(client):
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = client.recv(512)
        if not chunk:
            break
        request += chunk
        if len(request) > MAX_REQUEST_BYTES:
            raise ValueError("Request is too large")

    header_end = request.find(b"\r\n\r\n")
    if header_end < 0:
        raise ValueError("Incomplete HTTP request")

    header_text = request[:header_end].decode("utf-8")
    lines = header_text.split("\r\n")
    request_line = lines[0].split(" ")
    if len(request_line) != 3:
        raise ValueError("Invalid HTTP request line")

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower().strip()] = value.strip()

    try:
        body_length = int(headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("Invalid content length")

    route = request_line[1].split("?", 1)[0]
    max_body_bytes = (
        ota_manager.MAX_BUNDLE_BODY_BYTES
        if route == "/api/update/upload"
        else MAX_REQUEST_BYTES
    )
    if body_length < 0 or body_length > max_body_bytes:
        raise ValueError("Request body is too large")

    body = bytearray(request[header_end + 4:])
    while len(body) < body_length:
        chunk = client.recv(min(512, body_length - len(body)))
        if not chunk:
            break
        body.extend(chunk)

    if len(body) != body_length:
        raise ValueError("Incomplete HTTP request body")

    return request_line[0], request_line[1], body.decode("utf-8"), headers


def _send_response(client, status, content_type, body, headers=None):
    status_text = {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        404: "Not Found",
        500: "Internal Server Error",
        502: "Bad Gateway",
    }.get(status, "Response")
    payload = body.encode("utf-8") if isinstance(body, str) else body
    response = (
        "HTTP/1.1 {} {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
    ).format(status, status_text, content_type, len(payload)).encode("utf-8")
    for key, value in (headers or {}).items():
        response += "{}: {}\r\n".format(key, value).encode("utf-8")
    response += b"\r\n"
    _send_all(client, response + payload)


def _send_all(client, payload):
    sent = 0
    while sent < len(payload):
        sent += client.send(payload[sent:])


def _page(title, content):
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    html {{ background: #f5f5f5; }}
    body {{
      width: 100%; max-width: 48rem; min-height: 100vh; margin: 0 auto;
      padding: 1rem; font: 16px/1.5 sans-serif; color: #222; background: #fff;
    }}
    h1 {{
      font-size: clamp(1.5rem, 7vw, 2rem); line-height: 1.2;
      overflow-wrap: anywhere;
    }}
    fieldset {{
      min-width: 0; margin: 1rem 0; padding: .75rem;
      border: 1px solid #bbb; border-radius: 6px;
    }}
    legend {{ padding: 0 .25rem; font-weight: 700; }}
    label {{ display: block; margin: .9rem 0; }}
    input, select, button {{ font: inherit; }}
    input, select {{
      display: block; width: 100%; min-height: 2.75rem;
      margin-top: .35rem; padding: .55rem .65rem;
    }}
    button {{
      display: block; width: 100%; min-height: 2.75rem;
      margin: .5rem 0; padding: .55rem .8rem;
      white-space: normal; overflow-wrap: anywhere;
    }}
    .message {{
      background: #e5f5e5; padding: .8rem; border-radius: 4px;
      overflow-wrap: anywhere;
    }}
    #printer-status {{ display: block; margin-top: .5rem; overflow-wrap: anywhere; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{
      width: 40%; border: 1px solid #bbb; padding: .5rem;
      text-align: left; vertical-align: top; overflow-wrap: anywhere;
    }}
    td {{ width: 60%; }}
    @media (min-width: 40rem) {{
      body {{ padding: 2rem 1.5rem; }}
      input, select {{ max-width: 28rem; }}
      button {{ display: inline-block; width: auto; }}
      #printer-status {{ display: inline; margin-top: 0; margin-left: .5rem; }}
    }}
  </style>
</head>
<body>{}</body>
</html>""".format(_escape_html(title), content)


def _error_page(title, message):
    return _page(title, "<h1>{}</h1><p>{}</p><p><a href=\"/\">Back to configuration</a></p>".format(
        _escape_html(title),
        _escape_html(message),
    ))


def _json_dumps(value):
    try:
        return json.dumps(value, indent=2)
    except TypeError:
        return json.dumps(value)


def _url_decode(value):
    value = value.replace("+", " ")
    result = bytearray()
    index = 0
    while index < len(value):
        if value[index] == "%" and index + 2 < len(value):
            try:
                result.append(int(value[index + 1:index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        result.extend(value[index].encode("utf-8"))
        index += 1
    return result.decode("utf-8")


def _escape_html(value):
    value = str(value)
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _basic_auth_header(password):
    credentials = (WEB_AUTH_USERNAME + ":" + str(password)).encode("utf-8")
    if hasattr(_base64, "b2a_base64"):
        encoded = _base64.b2a_base64(credentials).strip()
    else:
        encoded = _base64.b64encode(credentials)
    return "Basic " + encoded.decode("ascii")
