# Bambutton
A physical plate-clear button for Bambuddy

![Bambutton in use on a P1S](assets/inuse.png)

Bambutton turns a small ESP32-C3 board into a dedicated wireless control for your printer. The LED ring flashes to show when a plate needs clearing, and one button press marks the plate as clear in Bambuddy so the next queued job can be despatched automatically.

It gives each printer a simple shop-floor control that is easy to see, quick to press, and smoother than opening the Bambuddy interface every time.

## Contents

- [Flashing Tool](#flashing-tool)
- [Manual Flashing](#manual-flashing)
  - [Configure the board](#configure-the-board)
  - [Run without auto-start](#run-without-auto-start)
- [Web GUI](#web-gui)
- [Release Packaging](#release-packaging)
- [Hardware](#hardware)
  - [Purchased Parts](#purchased-parts)
  - [Printed Parts](#printed-parts)
  - [Wiring Notes](#wiring-notes)

## Flashing Tool

For the simplest setup, download the [latest release](https://github.com/EdwardChamberlain/Bambutton/releases/latest)
and run the Bambutton setup assistant. It detects the connected ESP32-C3 automatically, flashes the bundled
MicroPython firmware and application files, and offers two setup modes:

- **Web GUI setup** flashes the board without a saved configuration. Configure
  it from the board's web page after flashing.
- **Config-based setup** flashes an existing `config.json`. The assistant can
  save an example configuration for you to edit first.

The release tool does not require Python, `mpremote`, or `esptool`. Connect the
board with a data-capable USB cable before starting the flash.

To run the assistant from source during development:

```bash
python -m pip install -r requirements.txt
python src/bambutton_config_gui.py
```

## Manual Flashing

Use this route for development or when you prefer the command line. You need
Python, a data-capable USB cable, and an ESP32-C3 connected over USB.

Create and activate a virtual environment, then install the flashing tools:

```bash
python -m venv .venv
```

On macOS or Linux, activate it with:

```bash
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.venv\Scripts\Activate.ps1
```

Then install the flashing tools:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Configure the board

Edit `micro/config.json` with the Wi-Fi network, Bambuddy API URL and key, the
printer ID, and any hardware pin changes. The default wiring is GPIO 3 for the
LED and GPIO 4 for the button. `micro/config_example.json` is a clean template
if you need one.

Erase the board, flash the bundled ESP32-C3 MicroPython firmware, and copy the
application files:

```bash
python -m esptool --chip esp32c3 --port /dev/tty.usbmodemXXXX erase_flash
python -m esptool --chip esp32c3 --port /dev/tty.usbmodemXXXX write_flash -z 0x0 firmware/ESP32_GENERIC_C3-20260406-v1.28.0.bin
python scripts/push_micro.py --clean
```

Replace `/dev/tty.usbmodemXXXX` with the board's serial port. `mpremote` can
usually find the port automatically; if it cannot, pass it to the copy script:

```bash
python scripts/push_micro.py --clean --device /dev/tty.usbmodemXXXX
```

The copy script resets the board when it finishes. To update only the
configuration later:

```bash
mpremote cp micro/config.json :
mpremote reset
```

The repository includes a firmware image for the ESP32-C3 Generic board. Check
the [latest MicroPython ESP32-C3 release](https://micropython.org/download/ESP32_GENERIC_C3/)
if you want to use a newer compatible image.

### Run without auto-start

To copy support files without installing `main.py` as the board's auto-starting
application, then run it from the host:

```bash
python scripts/push_micro.py --clean --no-main
python scripts/run_main.py
```

Pass `--device /dev/tty.usbmodemXXXX` to either script when automatic port
detection is unavailable.

## Web GUI

After flashing with Web GUI setup, the board starts a setup access point when it
cannot connect to configured Wi-Fi. Connect to the board's wifi (for
example, `bambutton-ABCD`) with and use username `admin`, password `bambutton`, then open
`http://192.168.4.1/`. Enter the Wi-Fi, Bambuddy API,
printer, and pin settings and choose **Save and restart**.

Once connected to Wi-Fi, open the board's hostname or assigned IP address. The
page can load printers from Bambuddy and update the board without USB. The debug page reports
runtime state without exposing secrets.

### Application updates

The web page's application update section can check the latest official release
or stage a local `bambutton-ota.json` bundle. Updates are written to the
inactive application slot, verified using file sizes and SHA-256 hashes, and
activated by a crash-safe append-only slot pointer. The previous slot is retained until
the new application confirms a healthy boot, so interrupted transfers and failed
restarts roll back automatically. Wi-Fi, API, printer, and web settings remain
in `config.json` and are never part of an application update.

The first OTA-capable installation must be flashed over USB so the stable
bootloader and migration code are installed. The USB helper stages the complete
runtime before installing the boot hook, preserves an existing legacy
`main.py`, and migrates the application into slot A on the next boot. Full
MicroPython firmware updates still require USB flashing.

## Release Packaging

Package versions are derived from Git tags via `hatch-vcs`. A tag beginning with
`v` starts the GitHub release workflow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow attaches Windows and macOS setup-tool archives, the verified
`bambutton-ota.json` application bundle, plus a Python wheel and source
distribution. To build the Python distribution locally:

```bash
python -m pip install ".[dev]"
python -m build
```

Build an application bundle locally with:

```bash
python scripts/build_ota_bundle.py --version 0.2.0 --output dist/bambutton-ota.json
```

## Hardware

### Purchased Parts

- [ESP32-C3 Super Mini](https://www.aliexpress.com/item/1005008805263277.html?spm=a2g0o.order_list.order_list_main.5.61041802T9J6qU)
- [LED Button](https://www.aliexpress.com/item/1005004920346156.html?) - select the **16 mm, 3-6V momentary** option. The case and assembly instructions are designed for this button size.

### Printed Parts

The top and bottom housing files are available on [makerworld](https://makerworld.com/en/models/2747607-bambutton-on-machine-bambuddy-plate-tracking).

These parts are designed to fit the hardware listed above.

You can print the housing in any colour or material you like. I found it useful to apply a small piece of double-sided tape to the ESP32-C3 board to hold it in place during assembly.

The small alignment holes are designed to accept short pieces of 1.75 mm filament (6 mm should do it!), which can be used as simple dowel pins to align the top and bottom halves.

The housing can be secured with 4 × M3×12 cap head bolts. These may not be required if the filament dowels are a tight enough fit.

I have also included a printed tool for doing up the M16 nut on the button as otherwise it is a bit difficult!

### Wiring Notes

The default configuration matches this final wiring:

```text
GPIO3 -> LED -> GND
GPIO4 -> button -> 3V3
```

Use GPIO numbers, not physical pin positions.

#### Button wiring:
- Connect one side of the momentary switch to GPIO 4 or your configured pin.
- Connect the other side of the switch to 3V3.
- The firmware enables the ESP32-C3 internal pull-down, so the button reads low when idle and high when pressed.
- The interrupt is configured for the rising edge, so it triggers on button press.

#### LED wiring:
- The LED output defaults to GPIO 3.
- Wire GPIO 3 to the LED anode through a suitable current-limiting resistor, then wire the LED cathode to GND.
- If wiring the LED inside the external button, connect it only according to the button's voltage/current requirements.
- Do not feed 5V into an ESP32-C3 GPIO. ESP32-C3 GPIO is 3.3V logic.
- If the button LED needs more current than a GPIO can safely provide, drive it through a transistor/MOSFET instead of directly from the GPIO.

> Note: When Wi-Fi is unavailable, the LED blinks at twice the plate-clear alert rate to show the connection failure. When connected, its standby state is tied to the printer's chamber light state, so turning off the printer light turns off the standby light on the button.

#### Power and USB:

- Use a data-capable USB cable for programming. Charge-only USB cables will power the board but will not appear to `mpremote`.
- Power the ESP32-C3 from USB during setup and flashing.
- Disconnect power before changing wiring.
- Once configured a "power only" cable will be ok as no data is transferred.
- You can power this from the P1S internal USB port.
