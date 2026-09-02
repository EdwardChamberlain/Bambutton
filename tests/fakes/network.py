STA_IF=0
AP_IF=1
AUTH_WPA2_PSK=3
def hostname(name=None):
    return name
class WLAN:
    def __init__(self, mode=0):
        self.mode=mode; self._conn=False; self._cfg={"essid":"Bambutton-Setup"}
    def active(self, v=None): return True
    def isconnected(self): return self._conn
    def connect(self, ssid, pw): self._conn=True
    def disconnect(self): self._conn=False
    def ifconfig(self): return ("192.168.4.1","255.255.255.0","192.168.4.1","192.168.4.1")
    def config(self, *a, **k):
        if a: return self._cfg.get(a[0], "")
        self._cfg.update(k); return None
    def scan(self):
        return [(b"HomeWiFi", b"\x00"*6, 11, -55, 3, False),
                (b"HomeWiFi", b"\x00"*6, 6, -74, 3, False),
                (b"GuestWiFi", b"\x00"*6, 11, -56, 3, False),
                (b"", b"\x00"*6, 11, -58, 3, False)]
