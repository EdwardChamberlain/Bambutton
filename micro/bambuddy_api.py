from api import API

try:
    import ujson as json
except ImportError:
    import json


class BambuddyAPIError(Exception):
    def __init__(self, message, status_code=None, body=None):
        self.status_code = status_code
        self.body = body
        self.message = message
        super().__init__(self.message)


class BambuddyAPI(API):
    # --- Internal methods ---
    def _get(self, path):
        try:
            status_code, body = self.api_get(path)
        except Exception as exc:
            raise BambuddyAPIError("API GET request failed: {}".format(exc))

        return self._handle_response(status_code, body)

    def _post(self, path, payload=None):
        try:
            status_code, body = self.api_post(path, payload)
        except Exception as exc:
            raise BambuddyAPIError("API POST request failed: {}".format(exc))

        return self._handle_response(status_code, body)

    def _handle_response(self, status_code, body):
        parsed_body = self._parse_body(body)

        if status_code < 200 or status_code >= 300:
            raise BambuddyAPIError(
                self._error_message(status_code, parsed_body),
                status_code,
                parsed_body,
            )

        return parsed_body

    def _error_message(self, status_code, body):
        if isinstance(body, dict):
            for key in ("detail", "error", "message"):
                if key in body:
                    return body[key]

        return "API request failed with status {}".format(status_code)

    def _parse_body(self, body):
        if body is None or body == "":
            return None

        try:
            return json.loads(body)
        except ValueError:
            return body

    # --- Public API methods ---
    @property
    def printers(self):
        return self.get_printers()

    def get_printers(self):
        return self._get("printers/")

    def get_printer(self, printer_id):
        return self._get(f"printers/{printer_id}")

    def get_printer_status(self, printer_id):
        return self._get(f"printers/{printer_id}/status")

    def printer_is_awaiting_plate_clear(self, printer_id):
        status = self.get_printer_status(printer_id)
        return status.get("awaiting_plate_clear", False)

    def clear_plate(self, printer_id):
        return self._post(f"printers/{printer_id}/clear-plate")

    def chamber_light_is_lit(self, printer_id):
        status = self.get_printer_status(printer_id)
        return status.get("chamber_light", False)

    def resume_print(self, printer_id):
        return self._post(f"printers/{printer_id}/print/resume")
