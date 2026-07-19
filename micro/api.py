import urequests


class API:
    def __init__(self, api_key, base_url, request_timeout_seconds=3):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.request_timeout_seconds = request_timeout_seconds

    def api_get(self, path, headers=None):
        response = None
        try:
            response = urequests.get(
                self.api_url(path),
                headers=self.api_headers(headers),
                timeout=self.request_timeout_seconds,
            )
            return response.status_code, response.text

        finally:
            if response:
                response.close()

    def api_post(self, path, payload=None, headers=None):
        response = None
        try:
            request_headers = self.api_headers(headers)
            request_headers["Content-Type"] = "application/json"
            response = urequests.post(
                self.api_url(path),
                json=payload,
                headers=request_headers,
                timeout=self.request_timeout_seconds,
            )
            return response.status_code, response.text

        finally:
            if response:
                response.close()

    def api_headers(self, extra_headers=None):
        headers = {
            "X-API-Key": self.api_key,
        }

        if extra_headers:
            headers.update(extra_headers)

        return headers

    def api_url(self, path):
        if path.startswith("http://") or path.startswith("https://"):
            return path

        return self.base_url + "/" + path.lstrip("/")
