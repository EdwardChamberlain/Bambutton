class Pin:
    OUT=1; IN=0; PULL_UP=2; PULL_DOWN=3; IRQ_RISING=4; IRQ_FALLING=8
    def __init__(self, num, mode=None, pull=None):
        self.num=num; self.mode=mode; self.pull=pull; self._v=0; self._handler=None
    def value(self, v=None):
        if v is None: return self._v
        self._v = 1 if v else 0
    def irq(self, trigger=None, handler=None):
        self._handler=handler
class WDT:
    def __init__(self, timeout=0): pass
    def feed(self): pass
class Timer:
    PERIODIC=1; ONE_SHOT=0
    def __init__(self, id=-1): self.id=id; self.cb=None
    def init(self, period=0, mode=1, callback=None): self.cb=callback
    def deinit(self): pass
