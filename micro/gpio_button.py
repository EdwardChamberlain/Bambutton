from machine import Pin
import time


class GPIOButton:
    def __init__(
        self,
        pin_number,
        on_press,
        debounce_ms=100,
        pull=Pin.PULL_DOWN,
        trigger=Pin.IRQ_RISING,
    ):
        self.pin_number = pin_number
        self.on_press = on_press
        self.debounce_ms = debounce_ms
        pull = _resolve_pull(pull)
        if pull is None:
            self.pin = Pin(pin_number, Pin.IN)
        else:
            self.pin = Pin(pin_number, Pin.IN, pull)
        self.trigger = _resolve_trigger(trigger)
        self.last_press_ms = 0

    def start(self):
        self.pin.irq(trigger=self.trigger, handler=self._irq)

    def stop(self):
        self.pin.irq(handler=None)

    def _irq(self, pin):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_press_ms) < self.debounce_ms:
            return

        self.last_press_ms = now
        self.on_press(pin)


def _resolve_pull(pull):
    if isinstance(pull, str):
        pull = pull.lower()
        if pull == "up":
            return Pin.PULL_UP
        if pull == "down":
            return Pin.PULL_DOWN
        if pull in ("none", ""):
            return None
        raise ValueError("Unsupported button pull: {}".format(pull))

    return pull


def _resolve_trigger(trigger):
    if isinstance(trigger, str):
        trigger = trigger.lower()
        if trigger == "falling":
            return Pin.IRQ_FALLING
        if trigger == "rising":
            return Pin.IRQ_RISING
        if trigger == "both":
            return Pin.IRQ_FALLING | Pin.IRQ_RISING
        raise ValueError("Unsupported button trigger: {}".format(trigger))

    return trigger
