# Third-party software notices

Bambutton includes and redistributes third-party software under the terms of
its respective licence. These licences are separate from Bambutton's MIT
licence. The desktop application build places the licence files supplied by
its installed runtime dependencies in `third_party_licenses/` alongside this
notice.

| Component | Version | Licence | Upstream licence/source |
| --- | --- | --- | --- |
| esptool | 5.2.0 | GPL-2.0-or-later | [Licence and source](https://github.com/espressif/esptool/tree/v5.2.0) |
| FreeSimpleGUI | 5.2.0.post1 | LGPL-3.0-or-later | [Licence and source](https://github.com/spyoungtech/FreeSimpleGUI/blob/main/license.txt) |
| mpremote | 1.28.0 | MIT | [MicroPython source](https://github.com/micropython/micropython/tree/v1.28.0/tools/mpremote) |
| MicroPython ESP32-C3 firmware | v1.28.0 | MIT plus port-specific notices | See [`firmware/THIRD_PARTY_NOTICES.md`](firmware/THIRD_PARTY_NOTICES.md) and the [upstream licence](https://github.com/micropython/micropython/blob/v1.28.0/LICENSE). |

The application also installs transitive Python runtime dependencies. Their
licence files are collected from the installed distribution metadata when the
desktop application is built. Source and wheel distributions declare the
runtime dependencies in `pyproject.toml`; each dependency retains its own
licence and copyright terms.
