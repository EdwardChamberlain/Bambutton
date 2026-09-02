class _Resp:
    status_code=200; text="[]"
    def close(self): pass
def get(*a, **k): return _Resp()
def post(*a, **k): return _Resp()
