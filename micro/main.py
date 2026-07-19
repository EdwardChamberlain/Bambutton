import time
from machine import WDT
import bambuddy_api
import config_loader
import gpio_button
import led_flasher
import wifi
import periodic_timer


config = config_loader.load_config()

# -- Runtime Flags ---
PRINTER_AWAITING_PLATE_CLEAR = False
PENDING_BUTTON_PRESS = False
CHAMBER_LIGHT_IS_ON = True
PRINTER_STATUS_UPDATE_REQUIRED = True

# Feed this only from the healthy main loop. If a network request or the
# networking stack blocks, the board will reboot and reconnect from scratch.
watchdog = WDT(timeout=60_000)

# -- Initialize LED flasher ---
flasher = led_flasher.LedFlasher(
    pin_number=config["led"]["pin"],
    should_flash=lambda: (
        PRINTER_AWAITING_PLATE_CLEAR and not PENDING_BUTTON_PRESS
    ),
    interval_ms=config["led"]["flash_interval_ms"],
    inactive_value=lambda: CHAMBER_LIGHT_IS_ON,
)
flasher.start()


# -- Button handler ---
def IRQ_button_press(pin):
    global PENDING_BUTTON_PRESS
    global PRINTER_AWAITING_PLATE_CLEAR

    # This runs in the hardware interrupt. Keep it allocation-free so the LED
    # stops flashing even while a status request is still timing out.
    if PRINTER_AWAITING_PLATE_CLEAR:
        PRINTER_AWAITING_PLATE_CLEAR = False
        PENDING_BUTTON_PRESS = True


button = gpio_button.GPIOButton(
    pin_number=config["button"]["pin"],
    on_press=IRQ_button_press,
    debounce_ms=config["button"]["debounce_ms"],
    pull=config["button"]["pull"],
    trigger=config["button"]["trigger"],
)
button.start()


# -- Connect to Wi-Fi --
try:
    network = wifi.WiFi(
        ssid=config["wifi"]["ssid"],
        password=config["wifi"]["password"],
        status_led=None,
        timeout_seconds=config["wifi"]["timeout_seconds"],
    )
    network.connect()

except Exception as exc:
    print("Wi-Fi connection failed:", exc)
    flasher.on()
    raise

# -- Initialize API client --
api = bambuddy_api.BambuddyAPI(
    config["api"]["key"],
    config["api"]["base_url"],
    config["api"]["request_timeout_seconds"],
)


# --- Setup Polling Loop ---
def IRQ_printer_update_tick():
    global PRINTER_STATUS_UPDATE_REQUIRED
    PRINTER_STATUS_UPDATE_REQUIRED = True


poll_timer = periodic_timer.PeriodicTimer(
    period_ms=config["printer"]["poll_interval_seconds"] * 1000,
    callback=IRQ_printer_update_tick,
)
poll_timer.start()


# --- Main loop handlers ---
def with_network_connection(request):
    network.ensure_connected()
    return request()


def handle_pending_button_press():
    global PENDING_BUTTON_PRESS
    global PRINTER_STATUS_UPDATE_REQUIRED

    try:
        with_network_connection(
            lambda: api.clear_plate(config["printer"]["id"])
        )
        PRINTER_STATUS_UPDATE_REQUIRED = True

    except Exception as exc:
        print("Failed to send plate clear request:", exc)

    PENDING_BUTTON_PRESS = False


def handle_printer_status_update():
    global PRINTER_AWAITING_PLATE_CLEAR, PRINTER_STATUS_UPDATE_REQUIRED
    global CHAMBER_LIGHT_IS_ON

    try:
        response = with_network_connection(
            lambda: api.get_printer_status(config["printer"]["id"])
        )
        PRINTER_AWAITING_PLATE_CLEAR = response["awaiting_plate_clear"]
        CHAMBER_LIGHT_IS_ON = response["chamber_light"]

        print("Printer awaiting plate clear:", PRINTER_AWAITING_PLATE_CLEAR, "Chamber light is on:", CHAMBER_LIGHT_IS_ON)

    except Exception as exc:
        print("Failed to fetch printer status:", exc)

    PRINTER_STATUS_UPDATE_REQUIRED = False


# -- Main loop --
while True:
    watchdog.feed()

    # Push button press to API if pending
    if PENDING_BUTTON_PRESS:
        handle_pending_button_press()

    # Check printer status
    if PRINTER_STATUS_UPDATE_REQUIRED:
        handle_printer_status_update()

    time.sleep_ms(25)
