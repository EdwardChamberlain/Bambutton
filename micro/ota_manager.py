"""Crash-safe application updates for the Bambutton MicroPython runtime.

The updater deliberately keeps the boot loader and this module outside the
application slots. A release is written to the inactive slot, verified, and
made active by appending a new pointer record. Pointer records are never
overwritten: a partial new record is ignored and the previous valid record
remains authoritative. A reset before the application confirms its boot
therefore rolls back to the previous slot.
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
REQUIRED_APP_FILES = APP_FILES
UPDATE_ROOT = ".bambutton"
BOOTSTRAP_ROOT = UPDATE_ROOT + "/bootstrap"
BOOTSTRAP_INSTALL_MARKER = UPDATE_ROOT + "/bootstrap-install.marker"
ACTIVE_POINTER = UPDATE_ROOT + "/active.json"
PENDING_POINTER = UPDATE_ROOT + "/pending.json"
LAST_ERROR = UPDATE_ROOT + "/last_error.json"
ACTIVE_RECORDS = "active"
TRANSACTION_RECORDS = "transaction"
ERROR_RECORDS = "error"
SLOT_NAMES = ("app_a", "app_b")
REMOTE_BUNDLE_URL = (
    "https://github.com/EdwardChamberlain/Bambutton/releases/latest/"
    "download/bambutton-ota.json"
)
MAX_FILE_BYTES = 40 * 1024
MAX_BUNDLE_BYTES = 128 * 1024
# Keep the downloaded JSON below the web server's 128 KiB request-body ceiling.
MAX_BUNDLE_BODY_BYTES = 96 * 1024
OTA_STAGING_OVERHEAD_BYTES = 48 * 1024


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
        active = self._read_active()
        pending = self._read_pending()
        error = self._read_last_error()
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
            "legacy": active is None or active.get("slot") not in SLOT_NAMES,
            "pending": pending,
            "staged_slot": self.staged_slot,
            "slots": slots,
            "last_error": error,
        }

    def check_remote(self, url=REMOTE_BUNDLE_URL):
        try:
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
            if _json_body_size(body) > MAX_BUNDLE_BODY_BYTES:
                raise OTAError("Update bundle payload is too large")
            bundle = _parse_json_body(body)
            self.stage_bundle(bundle)
            return self.status()
        except Exception as exc:
            self._record_error(str(exc))
            raise

    def stage_bundle(self, bundle):
        try:
            normalized = validate_bundle(bundle)
            self._ensure_directory(UPDATE_ROOT)

            active = self._read_active()
            active_slot = active.get("slot") if active else None
            target = _other_slot(active_slot)
            temporary = self._slot_path(target + ".tmp")

            self._remove_tree(temporary)
            total_size = sum(info["size"] for info in normalized["files"].values())
            self._ensure_staging_space(total_size + OTA_STAGING_OVERHEAD_BYTES)
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
            self._clear_error()
            return self.status()
        except Exception as exc:
            self._record_error(str(exc))
            raise

    def migrate_legacy(self, source_root=None):
        """Stage a flat-root application as an unconfirmed slot-A candidate."""
        source_root = source_root or self.root
        legacy_entry = self._legacy_entry_for_migration(source_root)
        self._ensure_directory(UPDATE_ROOT)
        temporary = self._slot_path("app_a.tmp")
        self._remove_tree(temporary)
        self._ensure_directory(temporary)
        manifest_files = {}
        try:
            for filename in APP_FILES:
                source_path = source_root + "/" + filename
                try:
                    with open(source_path, "rb") as source:
                        content = source.read()
                except OSError:
                    continue
                destination = self._safe_join(temporary, filename)
                with open(destination, "wb") as output:
                    output.write(content)
                self._verify_file(destination, {
                    "size": len(content),
                    "sha256": _sha256_hex(content),
                })
                manifest_files[filename] = {
                    "size": len(content),
                    "sha256": _sha256_hex(content),
                }

            for required in REQUIRED_APP_FILES:
                if required not in manifest_files:
                    self._remove_tree(temporary)
                    self._record_error(
                        "Legacy application is missing: {}".format(required)
                    )
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
            self._write_transaction({
                "state": "prepared",
                "candidate": "app_a",
                "previous": None,
                "legacy_entry": legacy_entry,
                "attempted": False,
            })
            self._write_active("app_a")
            return True
        except Exception as exc:
            self._remove_tree(temporary)
            self._record_error(str(exc))
            raise

    def commit_staged(self):
        try:
            if self.staged_slot not in SLOT_NAMES:
                raise OTAError("No verified application is staged")

            active = self._read_active()
            previous = active.get("slot") if active else None
            transaction = {
                "state": "prepared",
                "candidate": self.staged_slot,
                "previous": previous,
                "attempted": False,
            }
            self._write_transaction(transaction)
            self._write_active(self.staged_slot)
            self.staged_slot = None
            self._clear_error()
            return self.status()
        except Exception as exc:
            self._record_error(str(exc))
            raise

    def confirm_boot(self):
        pending = self._read_pending()
        if not pending:
            return False

        active = self._read_active()
        if not active or active.get("slot") != pending.get("candidate"):
            raise OTAError("Boot confirmation does not match active slot")

        pending = dict(pending)
        pending["state"] = "confirmed"
        pending["attempted"] = False
        self._write_transaction(pending)
        self._clear_error()
        return True

    def recover_pending_boot(self):
        pending = self._read_pending()
        if not pending:
            return False

        previous = pending.get("previous")
        candidate = pending.get("candidate")
        if previous in SLOT_NAMES:
            self._write_active(previous)
        else:
            self._write_active(
                None,
                legacy=True,
                legacy_entry=pending.get("legacy_entry"),
            )

        self._write_transaction({
            "state": "rolled_back",
            "message": "Application failed before confirming its boot",
            "candidate": candidate,
            "previous": previous,
            "attempted": True,
        })
        self._record_error(
            "Application failed before confirming its boot",
            candidate=candidate,
        )
        return True

    def launch(self):
        """Import the active application, rolling back failed candidates."""
        active = self._read_active()
        if not active:
            bootstrap = self._full_path(BOOTSTRAP_ROOT)
            if self._is_directory(bootstrap):
                if self.migrate_legacy(source_root=bootstrap):
                    self._remove_tree(bootstrap)
                    self._clear_file(BOOTSTRAP_INSTALL_MARKER)
            else:
                self.migrate_legacy()
            active = self._read_active()
        if active and active.get("slot") in SLOT_NAMES:
            self._clear_file(BOOTSTRAP_INSTALL_MARKER)
        slot = active.get("slot") if active else None

        pending = self._read_pending()
        if pending:
            state = pending.get("state", "prepared")
            if state in ("confirmed", "rolled_back", "cleared"):
                pending = None
            elif slot != pending.get("candidate"):
                # Power may have failed after the transaction record was written but
                # before the active pointer was switched. The old app remains
                # authoritative and the incomplete transaction is discarded.
                pending = dict(pending)
                pending["state"] = "rolled_back"
                self._write_transaction(pending)
            elif pending.get("attempted"):
                self.recover_pending_boot()
                self._reset_after_recovery()
            else:
                pending["attempted"] = True
                pending["state"] = "attempted"
                self._write_transaction(pending)

        if slot not in SLOT_NAMES:
            return self._launch_legacy()

        slot_path = self._slot_path(slot)
        try:
            self._verify_slot(slot)
            if slot_path not in sys.path:
                sys.path.insert(0, slot_path)
            return __import__("app_main")
        except Exception:
            pending = self._read_pending()
            if pending and pending.get("candidate") == slot:
                self.recover_pending_boot()
                self._reset_after_recovery()
            raise

    def _verify_slot(self, slot):
        manifest = self._read_json(self._slot_path(slot, "manifest.json"))
        if not isinstance(manifest, dict):
            raise OTAError("Active application slot is incomplete")
        files = manifest.get("files")
        if (
            not isinstance(files, dict)
            or len(files) != len(REQUIRED_APP_FILES)
            or any(filename not in files for filename in REQUIRED_APP_FILES)
        ):
            raise OTAError("Active application slot is incomplete")

        for filename in REQUIRED_APP_FILES:
            info = files.get(filename)
            if not isinstance(info, dict):
                raise OTAError("Invalid manifest entry for {}".format(filename))
            path = self._safe_join(self._slot_path(slot), filename)
            self._verify_file(path, info)

    def _launch_legacy(self):
        active = self._read_active()
        legacy_main = self.root + "/" + UPDATE_ROOT + "/legacy_main.py"
        if (
            (active and active.get("legacy_entry") == "legacy_main")
            or (active is None and self._path_exists(legacy_main))
        ):
            legacy_path = self._full_path(UPDATE_ROOT)
            if legacy_path not in sys.path:
                sys.path.insert(0, legacy_path)
            return __import__("legacy_main")
        if active and active.get("legacy_entry") == "main":
            return __import__("main")
        return __import__("app_main")

    def _reset_after_recovery(self):
        if self.reset:
            self.reset()
        raise OTAError("Application rollback requested")

    def _legacy_entry_for_migration(self, source_root):
        if self._path_exists(self.root + "/" + UPDATE_ROOT + "/legacy_main.py"):
            return "legacy_main"

        if source_root == self.root:
            if self._path_exists(self.root + "/app_main.py"):
                return "app_main"
            if self._path_exists(self.root + "/main.py"):
                return "main"
            return None

        legacy_main = self.root + "/main.py"
        staged_main = source_root + "/main.py"
        if (
            self._path_exists(legacy_main)
            and self._path_exists(staged_main)
            and not self._files_equal(legacy_main, staged_main)
        ):
            return "main"

        legacy_app = self.root + "/app_main.py"
        staged_app = source_root + "/app_main.py"
        if (
            self._path_exists(legacy_app)
            and self._path_exists(staged_app)
            and not self._files_equal(legacy_app, staged_app)
        ):
            return "app_main"
        return None

    def _path_exists(self, path):
        try:
            os.stat(path)
            return True
        except OSError:
            return False

    def _ensure_staging_space(self, required_bytes):
        statvfs = getattr(os, "statvfs", None)
        if statvfs is None:
            raise OTAError("Could not verify OTA staging space")
        try:
            filesystem = statvfs(self.root)
            available_bytes = filesystem[0] * filesystem[3]
        except Exception as exc:
            raise OTAError("Could not verify OTA staging space: {}".format(exc))
        if available_bytes < required_bytes:
            raise OTAError(
                "Not enough free space to stage the update "
                "({} bytes available, {} required)".format(
                    available_bytes, required_bytes
                )
            )

    def _files_equal(self, path_a, path_b):
        try:
            with open(path_a, "rb") as first:
                first_content = first.read()
            with open(path_b, "rb") as second:
                return first_content == second.read()
        except OSError:
            return False

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

    def _is_directory(self, path):
        try:
            os.listdir(path)
            return True
        except OSError:
            return False

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

    def _read_active(self):
        record = self._read_latest_record(ACTIVE_RECORDS)
        if record is not None:
            return record

        legacy = self._read_json(ACTIVE_POINTER)
        if isinstance(legacy, dict) and legacy.get("slot") in SLOT_NAMES:
            return legacy
        return None

    def _read_pending(self):
        record = self._read_transaction()
        if record is not None and record.get("state") in ("prepared", "attempted"):
            return record
        return None

    def _read_transaction(self):
        record = self._read_latest_record(TRANSACTION_RECORDS)
        if record is not None:
            return record

        legacy = self._read_json(PENDING_POINTER)
        if not isinstance(legacy, dict):
            return None
        legacy = dict(legacy)
        legacy["state"] = "attempted" if legacy.get("attempted") else "prepared"
        return legacy

    def _read_last_error(self):
        record = self._read_latest_record(ERROR_RECORDS)
        if record is not None:
            return None if record.get("cleared") else record
        return self._read_json(LAST_ERROR)

    def _write_active(self, slot, legacy=False, legacy_entry=None):
        value = {"slot": slot}
        if legacy:
            value["legacy"] = True
        if legacy_entry in ("main", "app_main", "legacy_main"):
            value["legacy_entry"] = legacy_entry
        self._write_state_record(ACTIVE_RECORDS, value)

    def _write_transaction(self, value):
        self._write_state_record(TRANSACTION_RECORDS, value)

    def _record_error(self, message, candidate=None):
        value = {"message": message}
        if candidate is not None:
            value["candidate"] = candidate
        try:
            self._write_state_record(ERROR_RECORDS, value)
        except Exception:
            pass

    def _clear_error(self):
        try:
            self._write_state_record(ERROR_RECORDS, {"cleared": True})
        except Exception:
            self._clear_file(LAST_ERROR)

    def _write_state_record(self, kind, value):
        self._ensure_directory(UPDATE_ROOT)
        sequence = self._next_sequence()
        path = self._full_path(
            UPDATE_ROOT + "/" + kind + "." + str(sequence) + ".json"
        )
        with open(path, "w") as output:
            output.write(_json_dumps(value))
            output.write("\n")

    def _read_latest_record(self, kind):
        records = []
        prefix = kind + "."
        try:
            names = os.listdir(self._full_path(UPDATE_ROOT))
        except OSError:
            return None
        for name in names:
            if not name.startswith(prefix) or not name.endswith(".json"):
                continue
            sequence_text = name[len(prefix):-5]
            try:
                sequence = int(sequence_text)
            except (TypeError, ValueError):
                continue
            records.append((sequence, name))

        records.sort(reverse=True)
        for _sequence, name in records:
            value = self._read_json(UPDATE_ROOT + "/" + name)
            if not isinstance(value, dict):
                continue
            if kind == ACTIVE_RECORDS:
                slot = value.get("slot")
                if slot not in SLOT_NAMES and not (
                    slot is None and value.get("legacy")
                ):
                    continue
            elif kind == TRANSACTION_RECORDS:
                if value.get("state") not in (
                    "prepared", "attempted", "confirmed", "rolled_back", "cleared"
                ):
                    continue
            return value
        return None

    def _next_sequence(self):
        highest = 0
        try:
            names = os.listdir(self._full_path(UPDATE_ROOT))
        except OSError:
            names = []
        for name in names:
            parts = name.split(".")
            if len(parts) != 3 or parts[0] not in (
                ACTIVE_RECORDS, TRANSACTION_RECORDS, ERROR_RECORDS
            ) or parts[2] != "json":
                continue
            try:
                highest = max(highest, int(parts[1]))
            except (TypeError, ValueError):
                pass
        return highest + 1

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


def _json_body_size(body):
    if isinstance(body, bytes):
        return len(body)
    if not isinstance(body, str):
        return MAX_BUNDLE_BODY_BYTES + 1

    size = 0
    for character in body:
        codepoint = ord(character)
        size += (
            1 if codepoint < 0x80 else
            2 if codepoint < 0x800 else
            3 if codepoint < 0x10000 else
            4
        )
        if size > MAX_BUNDLE_BODY_BYTES:
            return size
    return size


def _request_get(url):
    if requests is None:
        raise OTAError("HTTP client is unavailable")
    return requests.get(url, timeout=15)
