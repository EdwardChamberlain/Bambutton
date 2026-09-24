"""Keep unit tests runnable on hosts whose Python lacks Tk support."""

import sys
from types import ModuleType


try:
    import _tkinter  # noqa: F401
except ImportError:
    class HeadlessFreeSimpleGUI(ModuleType):
        WIN_CLOSED = "WIN_CLOSED"
        BUTTON_TYPE_BROWSE_FILE = "browse-file"

        def __getattr__(self, name):
            def widget_or_callback(*args, **kwargs):
                return None

            return widget_or_callback

    sys.modules.setdefault(
        "FreeSimpleGUI", HeadlessFreeSimpleGUI("FreeSimpleGUI")
    )
