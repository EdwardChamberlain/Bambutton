"""Crash-safe application updates for the Bambutton MicroPython runtime.

The updater deliberately keeps the boot loader and this module outside the
application slots.  A release is written to the inactive slot, verified, and
made active by renaming a small pointer file.  A reset before the application
confirms its boot therefore rolls back to the previous slot.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import urequests as requests
except ImportError:
    try:
        import requests
    except ImportError:
        requests = None

import os
import sys


BOOTLOADER_VERSION = 1
UPDATE_FORMAT = 1
APP_FILES = (
    "api.py",
    "app_main.py",
    "bambuddy_api.py",
    "config_loader.py",
    "gpio_button.py",
    "led_flasher.py",
    "periodic_timer.py",
    "web_config.py",
    "wifi.py",
)
REQUIRED_APP_FILES = ("app_main.py", "web_config.py")
UPDATE_ROOT = ".bambutton"
ACTIVE_POINTER = UPDATE_ROOT + "/active.json"
PENDING_POINTER = UPDATE_ROOT + "/pending.json"
LAST_ERROR = UPDATE_ROOT + "/last_error.json"
SLOT_NAMES = ("app_a", "app_b")
REMOTE_BUNDLE_URL = (
    "https://github.com/EdwardChamberlain/Bambutton/releases/latest/"
    "download/bambutton-ota.json"
)
MAX_FILE_BYTES = 32 * 1024
MAX_BUNDLE_BYTES = 128 * 1024


class OTAError(Exception):
    pass


class OTAUpdateManager:
    def __init__(
        self,
        root=".",
        reset=None,
        request_get=None,
    ):
        self.root = root.rstrip("/") or "."
        self.reset = reset
        self.request_get = request_get or _request_get
        self.staged_slot = None

    def status(self):
        active = self._read_json(ACTIVE_POINTER)
        pending = self._read_json(PENDING_POINTER)
        error = self._read_json(LAST_ERROR)
        slots = {}
        for slot in SLOT_NAMES:
            manifest = self._read_json(self._slot_path(slot, "manifest.json"))
            slots[slot] = {
                "ready": isinstance(manifest, dict),
                "version": manifest.get("version") if manifest else None,
            }

        active_slot = active.get("slot") if active else None
        current_version = None
        if active_slot in slots:
            current_version = slots[active_slot].get("version")

        return {
            "bootloader_version": BOOTLOADER_VERSION,
            "current_version": current_version,
            "active_slot": active_slot,
            "legacy": active is None,
            "pending": pending,
            "staged_slot": self.staged_slot,
            "slots": slots,
            "last_error": error,
        }

    def check_remote(self, url=REMOTE_BUNDLE_URL):
        if not url.startswith("https://"):
            raise OTAError("Remote update URLs must use HTTPS")
        response = self.request_get(url)
        try:
            status_code = getattr(response, "status_code", 200)
            if status_code < 200 or status_code >= 300:
                raise OTAError("Remote update returned HTTP {}".format(status_code))
            body = response.text
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        bundle = _parse_json_body(body)
        self.stage_bundle(bundle)
        return self.status()

    def stage_bundle(self, bundle):
        normalized = validate_bundle(bundle)
        self._ensure_directory(UPDATE_ROOT)

        active = self._read_json(ACTIVE_POINTER)
        active_slot = active.get("slot") if active else None
        target = _other_slot(active_slot)
        temporary = self._slot_path(target + ".tmp")

        self._remove_tree(temporary)
        self._ensure_directory(temporary)
        try:
            for filename, file_info in normalized["files"].items():
                path = self._safe_join(temporary, filename)
                self._write_base64_file(path, file_info["content"])
                self._verify_file(path, file_info)

            self._write_json(self._slot_path(target + ".tmp", "manifest.json"), {
                "format": normalized["format"],
                "version": normalized["version"],
                "release_notes": normalized.get("release_notes", ""),
                "minimum_bootloader": normalized["minimum_bootloader"],
                "files": {
                    name: {
                        "size": info["size"],
                        "sha256": info["sha256"],
                    }
                    for name, info in normalized["files"].items()
                },
            })
            self._remove_tree(self._slot_path(target))
            self._rename(temporary, self._slot_path(target))
        except Exception:
            self._remove_tree(temporary)
            raise

        self.staged_slot = target
        self._clear_file(LAST_ERROR)
        return self.status()

    def migrate_legacy(self):
        """Move a flat-root application into slot A without touching it."""
        self._ensure_directory(UPDATE_ROOT)
        temporary = self._slot_path("app_a.tmp")
        self._remove_tree(temporary)
        self._ensure_directory(temporary)
        manifest_files = {}
        try:
            for filename in APP_FILES:
                source_path = self._full_path(filename)
                try:
                    with open(source_path, "rb") as source:
                        content = source.read()
                except OSError:
                    continue
                destination = self._safe_join(temporary, filename)
                with open(destination, "wb") as output:
                    output.write(content)
                manifest_files[filename] = {
                    "size": len(content),
                    "sha256": _sha256_hex(content),
                }

            for required in REQUIRED_APP_FILES:
                if required not in manifest_files:
                    self._remove_tree(temporary)
                    return False

            self._write_json(self._slot_path("app_a.tmp", "manifest.json"), {
                "format": UPDATE_FORMAT,
                "version": "legacy",
                "release_notes": "Migrated from the flat-root application",
                "minimum_bootloader": BOOTLOADER_VERSION,
                "files": manifest_files,
            })
            self._remove_tree(self._slot_path("app_a"))
            self._rename(temporary, self._slot_path("app_a"))
            self._write_json(PENDING_POINTER + ".tmp", {
                "candidate": "app_a",
                "previous": None,
                "attempted": False,
            })
            self._rename(PENDING_POINTER + ".tmp", PENDING_POINTER)
            self._write_json(ACTIVE_POINTER + ".tmp", {"slot": "app_a"})
            self._rename(ACTIVE_POINTER + ".tmp", ACTIVE_POINTER)
            return True
        except Exception:
            self._remove_tree(temporary)
            raise

    def commit_staged(self):
        if self.staged_slot not in SLOT_NAMES:
            raise OTAError("No verified application is staged")

        active = self._read_json(ACTIVE_POINTER)
        previous = active.get("slot") if active else None
        pending = {
            "candidate": self.staged_slot,
            "previous": previous,
            "attempted": False,
        }
        self._write_json(PENDING_POINTER + ".tmp", pending)
        self._rename(PENDING_POINTER + ".tmp", PENDING_POINTER)

        self._write_json(ACTIVE_POINTER + ".tmp", {
            "slot": self.staged_slot,
        })
        self._rename(ACTIVE_POINTER + ".tmp", ACTIVE_POINTER)
        self.staged_slot = None
        return self.status()

    def confirm_boot(self):
        pending = self._read_json(PENDING_POINTER)
        if not pending:
            return False

        active = self._read_json(ACTIVE_POINTER)
        if not active or active.get("slot") != pending.get("candidate"):
            raise OTAError("Boot confirmation does not match active slot")

        self._clear_file(PENDING_POINTER)
        self._clear_file(LAST_ERROR)
        return True

    def recover_pending_boot(self):
        pending = self._read_json(PENDING_POINTER)
        if not pending:
            return False

        previous = pending.get("previous")
        candidate = pending.get("candidate")
        if previous in SLOT_NAMES:
            self._write_json(ACTIVE_POINTER + ".tmp", {"slot": previous})
            self._rename(ACTIVE_POINTER + ".tmp", ACTIVE_POINTER)
        else:
            self._clear_file(ACTIVE_POINTER)

        self._write_json(LAST_ERROR, {
            "message": "Application failed before confirming its boot",
            "candidate": candidate,
        })
        self._clear_file(PENDING_POINTER)
        return True

    def launch(self):
        """Import the active application, rolling back failed candidates."""
        active = self._read_json(ACTIVE_POINTER)
        if not active:
            self.migrate_legacy()
            active = self._read_json(ACTIVE_POINTER)
        slot = active.get("slot") if active else None

        pending = self._read_json(PENDING_POINTER)
        if pending:
            if slot != pending.get("candidate"):
                # Power may have failed after pending.json was written but
                # before the active pointer was switched. The old app remains
                # authoritative and the incomplete transaction is discarded.
                self._clear_file(PENDING_POINTER)
            elif pending.get("attempted"):
                self.recover_pending_boot()
                self._reset_after_recovery()
            else:
                pending["attempted"] = True
                self._write_json(PENDING_POINTER + ".tmp", pending)
                self._rename(PENDING_POINTER + ".tmp", PENDING_POINTER)

        if slot not in SLOT_NAMES:
            return self._launch_legacy()

        slot_path = self._slot_path(slot)
        if not self._read_json(self._slot_path(slot, "manifest.json")):
            raise OTAError("Active application slot is incomplete")
        if slot_path not in sys.path:
            sys.path.insert(0, slot_path)
        return __import__("app_main")

    def _launch_legacy(self):
        return __import__("app_main")

    def _reset_after_recovery(self):
        if self.reset:
            self.reset()
        raise OTAError("Application rollback requested")

    def _slot_path(self, slot, filename=None):
        path = self.root + "/" + UPDATE_ROOT + "/" + slot
        if filename:
            path += "/" + filename
        return path

    def _safe_join(self, directory, filename):
        if filename not in APP_FILES or "/" in filename or "\\" in filename:
            raise OTAError("Application file is not allowlisted: {}".format(filename))
        return directory + "/" + filename

    def _write_base64_file(self, path, encoded):
        try:
            content = binascii.a2b_base64(encoded)
        except Exception:
            raise OTAError("Application file is not valid base64")
        if len(content) > MAX_FILE_BYTES:
            raise OTAError("Application file is too large")
        with open(path, "wb") as output:
            output.write(content)

    def _verify_file(self, path, file_info):
        with open(path, "rb") as source:
            content = source.read()
        if len(content) != file_info["size"]:
            raise OTAError("Application file size mismatch")
        if _sha256_hex(content) != file_info["sha256"]:
            raise OTAError("Application file checksum mismatch")

    def _ensure_directory(self, path):
        full_path = self.root + "/" + path if not path.startswith(self.root) else path
        parts = full_path.strip("/").split("/")
        current = "/" if full_path.startswith("/") else ""
        for part in parts:
            if not part:
                continue
            current += ("/" if current and not current.endswith("/") else "") + part
            try:
                os.mkdir(current)
            except OSError:
                pass

    def _remove_tree(self, path):
        try:
            entries = os.listdir(path)
        except OSError:
            try:
                os.remove(path)
            except OSError:
                pass
            return

        for entry in entries:
            child = path + "/" + entry
            try:
                os.listdir(child)
                self._remove_tree(child)
            except OSError:
                try:
                    os.remove(child)
                except OSError:
                    pass
        try:
            os.rmdir(path)
        except OSError:
            pass

    def _rename(self, source, destination):
        source = self._full_path(source)
        destination = self._full_path(destination)
        try:
            os.rename(source, destination)
        except OSError as exc:
            raise OTAError("Could not atomically switch update state: {}".format(exc))

    def _read_json(self, path):
        path = self._full_path(path)
        try:
            with open(path) as source:
                return json.load(source)
        except (OSError, ValueError):
            return None

    def _write_json(self, path, value):
        full_path = self._full_path(path)
        parent = full_path.rsplit("/", 1)[0]
        self._ensure_directory(parent)
        with open(full_path, "w") as output:
            output.write(_json_dumps(value))
            output.write("\n")

    def _clear_file(self, path):
        full_path = self._full_path(path)
        try:
            os.remove(full_path)
        except OSError:
            pass

    def _full_path(self, path):
        return self.root + "/" + path if not path.startswith(self.root) else path


def validate_bundle(bundle):
    if not isinstance(bundle, dict):
        raise OTAError("Update bundle must be a JSON object")
    if bundle.get("format") != UPDATE_FORMAT:
        raise OTAError("Unsupported update bundle format")
    version = bundle.get("version")
    if not isinstance(version, str) or not version.strip():
        raise OTAError("Update bundle version is required")
    minimum = bundle.get("minimum_bootloader", BOOTLOADER_VERSION)
    if minimum > BOOTLOADER_VERSION:
        raise OTAError("Update requires a newer bootloader")
    files = bundle.get("files")
    if not isinstance(files, dict) or not files:
        raise OTAError("Update bundle contains no application files")
    missing = [name for name in REQUIRED_APP_FILES if name not in files]
    if missing:
        raise OTAError("Update bundle is missing: {}".format(", ".join(missing)))

    total_size = 0
    for filename, info in files.items():
        if filename not in APP_FILES or "/" in filename or "\\" in filename:
            raise OTAError("Application file is not allowlisted: {}".format(filename))
        if not isinstance(info, dict):
            raise OTAError("Invalid metadata for {}".format(filename))
        content = info.get("content")
        digest = info.get("sha256")
        size = info.get("size")
        if not isinstance(content, str) or not isinstance(digest, str):
            raise OTAError("Invalid content metadata for {}".format(filename))
        try:
            decoded_size = len(binascii.a2b_base64(content))
        except Exception:
            raise OTAError("Invalid base64 content for {}".format(filename))
        if not isinstance(size, int) or size != decoded_size:
            raise OTAError("Invalid size for {}".format(filename))
        if size > MAX_FILE_BYTES:
            raise OTAError("Application file is too large: {}".format(filename))
        if _sha256_hex(binascii.a2b_base64(content)) != digest:
            raise OTAError("Application file checksum mismatch: {}".format(filename))
        total_size += size

    if total_size > MAX_BUNDLE_BYTES:
        raise OTAError("Update bundle is too large")

    result = dict(bundle)
    result["format"] = UPDATE_FORMAT
    result["minimum_bootloader"] = minimum
    return result


def _other_slot(active_slot):
    return "app_b" if active_slot == "app_a" else "app_a"


def _sha256_hex(content):
    digest = hashlib.sha256(content).digest()
    return binascii.hexlify(digest).decode("ascii")


def _json_dumps(value):
    try:
        return json.dumps(value, separators=(",", ":"))
    except TypeError:
        return json.dumps(value)


def _parse_json_body(body):
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise OTAError("Remote update did not return valid JSON: {}".format(exc))


def _request_get(url):
    if requests is None:
        raise OTAError("HTTP client is unavailable")
    return requests.get(url, timeout=15)
