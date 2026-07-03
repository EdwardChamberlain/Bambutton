import time
import bambuddy_api
import config_loader
import gpio_button
import led_flasher
import wifi
import periodic_timer
import printer_status


config = config_loader.load_config()

# -- Runtime Flags ---
PRINTER_AWAITING_PLATE_CLEAR = False
PRINTER_STATUS = printer_status.PrinterStatus.IDLE
PENDING_BUTTON_PRESS = False
CHAMBER_LIGHT_IS_ON = True
PRINTER_STATUS_UPDATE_REQUIRED = True

# -- Initialize LED flasher ---
flasher = led_flasher.LedFlasher(
    pin_number=config["led"]["pin"],
    should_flash=lambda: PRINTER_STATUS == printer_status.PrinterStatus.PAUSE or PRINTER_AWAITING_PLATE_CLEAR,
    interval_ms=config["led"]["flash_interval_ms"],
    inactive_value=lambda: CHAMBER_LIGHT_IS_ON,
)
flasher.start()


# -- Button handler ---
def IRQ_button_press(pin):
    global PENDING_BUTTON_PRESS

    print("Button pressed on GPIO", config["button"]["pin"])
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
def handle_pending_button_press():
    global PENDING_BUTTON_PRESS
    global PRINTER_AWAITING_PLATE_CLEAR
    global PRINTER_STATUS_UPDATE_REQUIRED
    global PRINTER_STATUS

    if PRINTER_STATUS == printer_status.PrinterStatus.PAUSE:
        try:
            api.resume_print(config["printer"]["id"])
            PRINTER_STATUS_UPDATE_REQUIRED = True
            print("Sent resume request")

        except Exception as exc:
            print("Failed to send resume request:", exc)

    elif PRINTER_AWAITING_PLATE_CLEAR:
        try:
            PRINTER_AWAITING_PLATE_CLEAR = False
            api.clear_plate(config["printer"]["id"])
            PRINTER_STATUS_UPDATE_REQUIRED = True

        except Exception as exc:
            print("Failed to send plate clear request:", exc)

    else:
        print("Button press ignored - printer not paused or awaiting plate clear")

    PENDING_BUTTON_PRESS = False


def handle_printer_status_update():
    global PRINTER_AWAITING_PLATE_CLEAR, PRINTER_STATUS_UPDATE_REQUIRED
    global PRINTER_STATUS, CHAMBER_LIGHT_IS_ON

    try:
        response = api.get_printer_status(config["printer"]["id"])
        PRINTER_AWAITING_PLATE_CLEAR = response.get("awaiting_plate_clear", False)
        CHAMBER_LIGHT_IS_ON = response.get("chamber_light", True)
        PRINTER_STATUS = response.get("state", printer_status.PrinterStatus.IDLE)

        print("Printer status:", PRINTER_STATUS, "Awaiting plate clear:", PRINTER_AWAITING_PLATE_CLEAR, "Chamber light is on:", CHAMBER_LIGHT_IS_ON)

        if PRINTER_STATUS == printer_status.PrinterStatus.PAUSE:
            flasher.set_interval(500)
        elif PRINTER_AWAITING_PLATE_CLEAR:
            flasher.set_interval(config["led"]["flash_interval_ms"])

    except Exception as exc:
        print("Failed to fetch printer status:", exc)

    PRINTER_STATUS_UPDATE_REQUIRED = False


# -- Main loop --
while True:
    # Push button press to API if pending
    if PENDING_BUTTON_PRESS:
        handle_pending_button_press()

    # Check printer status
    if PRINTER_STATUS_UPDATE_REQUIRED:
        handle_printer_status_update()

    time.sleep_ms(25)
