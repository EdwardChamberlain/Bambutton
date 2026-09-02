"""Shared helpers used by the runner (normal mode) and the setup portal."""


def normalize_base_url(raw):
    url = str(raw).strip()
    if not url:
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url
    url = url.rstrip("/")
    if not url.endswith("/api/v1"):
        url = url + "/api/v1"
    return url


def extract_list(payload):
    if isinstance(payload, dict):
        for key in ("printers", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    if isinstance(payload, list):
        return payload
    return []


def printer_label(printer):
    return str(
        printer.get("friendly_name")
        or printer.get("name")
        or printer.get("display_name")
        or ("ID %s" % printer.get("id"))
    )


def build_name_map(printers):
    name_map = {}
    for printer in printers:
        if not isinstance(printer, dict) or "id" not in printer:
            continue
        for field in ("friendly_name", "name", "display_name"):
            value = printer.get(field)
            if value:
                name_map[str(value).strip().lower()] = printer["id"]
    return name_map


def is_numeric(ref):
    return isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit())


def match_printer_id(ref, name_map):
    """Numeric id used directly; a name resolved exact-then-contains."""
    if isinstance(ref, int):
        return ref
    text = str(ref).strip()
    if text == "":
        return None
    if text.isdigit():
        return int(text)
    key = text.lower()
    if key in name_map:
        return name_map[key]
    matches = [pid for name, pid in name_map.items() if key in name]
    if len(matches) == 1:
        return matches[0]
    return None
