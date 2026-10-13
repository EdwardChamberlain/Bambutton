# Firmware notices

`ESP32_GENERIC_C3-20260406-v1.28.0.bin` redistributes the official MicroPython
v1.28.0 ESP32-C3 firmware. The upstream ESP32 port uses Espressif ESP-IDF; its
v1.28.0 port documentation identifies ESP-IDF v5.5.1 as the recommended
version.

The package includes these upstream notices and licence texts alongside the
firmware binary:

- `LICENSES/MicroPython-LICENSE-v1.28.0.txt` contains the full MicroPython
  MIT licence, copyright notice, and upstream summary of port-specific
  third-party licences.
- `LICENSES/ESP-IDF-LICENSE-v5.5.1.txt` contains Espressif's Apache 2.0
  licence.
- `LICENSES/ESP-IDF-COPYRIGHT-v5.5.1.rst` contains Espressif's firmware
  component copyright and licence disclosures, including Newlib, FreeRTOS,
  lwIP, wpa_supplicant, Mbed TLS, and other components.

These files are included in the Python wheel and source archive as well as the
desktop application distribution. Upstream references:
[MicroPython v1.28.0 licence](https://github.com/micropython/micropython/blob/v1.28.0/LICENSE),
[ESP-IDF v5.5.1 licence](https://github.com/espressif/esp-idf/blob/v5.5.1/LICENSE),
[ESP-IDF v5.5.1 copyright disclosures](https://github.com/espressif/esp-idf/blob/v5.5.1/docs/en/COPYRIGHT.rst).
