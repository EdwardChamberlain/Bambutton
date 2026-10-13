# Third-party software notices

Bambutton includes and redistributes third-party software under the terms of
its respective licence. These licences are separate from Bambutton's MIT
licence. The desktop application includes licence documents supplied by its
active runtime dependencies in `third_party_licenses/`. It also includes the
pinned pyserial licence text from `THIRD_PARTY_LICENSES/` and the firmware
notices and licence texts from `firmware/LICENSES/`.

| Component | Version | Licence | Upstream licence/source |
| --- | --- | --- | --- |
| esptool | 5.2.0 | GPL-2.0-or-later | [Licence and source](https://github.com/espressif/esptool/tree/v5.2.0); the matching source archive is published with each Bambutton desktop release. |
| FreeSimpleGUI | 5.2.0.post1 | LGPL-3.0-or-later | The desktop build includes the full licence text from the installed distribution metadata and its [upstream notice](https://github.com/spyoungtech/FreeSimpleGUI/blob/main/NOTICE). |
| pyserial | 3.5 | BSD-3-Clause | The full text is included at `third_party_licenses/pyserial-3.5-LICENSE.txt`; see the [upstream licence](https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt). |
| mpremote | 1.28.0 | MIT | [MicroPython source](https://github.com/micropython/micropython/tree/v1.28.0/tools/mpremote) |
| MicroPython ESP32-C3 firmware | v1.28.0 | MIT plus ESP-IDF component notices | See [`firmware/THIRD_PARTY_NOTICES.md`](firmware/THIRD_PARTY_NOTICES.md) and the included files under `firmware/LICENSES/`. |

The application also installs transitive Python runtime dependencies. Their
licence documents are collected from active runtime requirements when the
desktop application is built. Long licence texts stored in package metadata
are included too. Source and wheel distributions declare the runtime
dependencies in `pyproject.toml`; each dependency retains its own licence and
copyright terms.
