from machine import Pin
from periodic_timer import PeriodicTimer


class LedFlasher:
    def __init__(
        self,
        pin_number,
        should_flash,
        interval_ms=250,
        inactive_value=0,
    ):
        self.led = Pin(pin_number, Pin.OUT)
        self.should_flash = should_flash
        self.interval_ms = interval_ms
        self.inactive_value = inactive_value
        self.timer = PeriodicTimer(self.interval_ms, self._tick)

    def start(self):
        self.timer.start()

    def stop(self, led_value=None):
        self.timer.stop()

        if led_value is not None:
            self.led.value(led_value)

    def on(self):
        self.led.value(1)

    def off(self):
        self.led.value(0)

    def set_interval(self, interval_ms):
        self.interval_ms = interval_ms
        self.timer.set_period(interval_ms)

    def _tick(self):
        if self.should_flash():
            self.led.value(not self.led.value())
        else:
            if callable(self.inactive_value):
                self.led.value(self.inactive_value())
            else:
                self.led.value(self.inactive_value)
