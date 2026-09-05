import network
import time


DEFAULT_HOSTNAME = "bambutton"


class WiFi:
    def __init__(
        self,
        ssid,
        password,
        status_led=None,
        timeout_seconds=10,
        connected_led_value=0,
        failed_led_value=1,
    ):
        self.ssid = ssid
        self.password = password
        self.status_led = status_led
        self.timeout_seconds = timeout_seconds
        self.connected_led_value = connected_led_value
        self.failed_led_value = failed_led_value
        self.wlan = network.WLAN(network.STA_IF)

    def connect(self):
        # Set this before activating the interface so DHCP and mDNS can use it.
        network.hostname(DEFAULT_HOSTNAME)
        self.wlan.active(True)
        # self.wlan.config(txpower=8.5)

        if not self.wlan.isconnected():
            print("Connecting to Wi-Fi:", self.ssid)
            self.wlan.connect(self.ssid, self.password)
            self._wait_for_connection()

        self._set_led(self.connected_led_value)
        print("Connected to Wi-Fi")
        print("Network config:", self.wlan.ifconfig())
        return self.wlan

    def ensure_connected(self):
        if self.is_connected():
            return self.wlan

        print("Wi-Fi connection lost; reconnecting")
        self.wlan.disconnect()
        return self.connect()

    def is_connected(self):
        return self.wlan.isconnected()

    def ifconfig(self):
        return self.wlan.ifconfig()

    def _wait_for_connection(self):
        started_at = time.ticks_ms()

        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), started_at) > self.timeout_seconds * 1000:
                self._set_led(self.failed_led_value)
                raise RuntimeError("Wi-Fi connection timed out")

            self._toggle_led()
            time.sleep(0.25)

    def _toggle_led(self):
        if self.status_led:
            self.status_led.value(not self.status_led.value())

    def _set_led(self, value):
        if self.status_led:
            self.status_led.value(value)
