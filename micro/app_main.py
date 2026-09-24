import machine
import time
import bambuddy_api
import config_loader
import gpio_button
import led_flasher
import ota_manager
import wifi
import periodic_timer
import web_config


config = config_loader.load_config()

# -- Runtime Flags ---
PRINTER_AWAITING_PLATE_CLEAR = False
PENDING_BUTTON_PRESS = False
CHAMBER_LIGHT_IS_ON = True
PRINTER_STATUS_UPDATE_REQUIRED = True
network = None


def should_flash_connection_failure():
    # Keep the connection failure indication active during boot, before the
    # Wi-Fi helper has been created, and whenever the interface drops later.
    return network is None or not network.is_connected()


def should_flash_plate_clear():
    return PRINTER_AWAITING_PLATE_CLEAR and not PENDING_BUTTON_PRESS


# Feed this from the main loop and during each bounded Wi-Fi attempt/backoff.
# If a request or the networking stack blocks, the board will reboot.
watchdog = machine.WDT(timeout=60_000)

# -- Initialize LED flasher ---
flasher = led_flasher.LedFlasher(
    pin_number=config["led"]["pin"],
    should_flash=should_flash_plate_clear,
    interval_ms=config["led"]["flash_interval_ms"],
    inactive_value=lambda: CHAMBER_LIGHT_IS_ON,
    fast_should_flash=should_flash_connection_failure,
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
network = wifi.WiFi(
    ssid=config["wifi"]["ssid"],
    password=config["wifi"]["password"],
    hostname=config["wifi"].get("hostname", wifi.DEFAULT_HOSTNAME),
    ap_password=config["wifi"].get("ap_password", wifi.DEFAULT_AP_PASSWORD),
    status_led=None,
    timeout_seconds=config["wifi"]["timeout_seconds"],
)
printer_api_ready = config_loader.is_runtime_config_ready(config)
if printer_api_ready:
    network.connect_with_fallback(watchdog_feed=watchdog.feed)
else:
    # Keep the setup UI reachable until a complete, explicit printer
    # configuration has been saved. In particular, do not poll or clear the
    # baked-in/default printer ID while settings are incomplete.
    network.start_access_point()
if network.is_ap_mode():
    print("Wi-Fi unavailable; connect to the setup access point to update settings")
    flasher.on()

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
    if network.is_ap_mode():
        raise RuntimeError("Wi-Fi setup access point is active")

    network.ensure_connected(watchdog_feed=watchdog.feed, fallback_to_ap=True)
    if network.is_ap_mode():
        raise RuntimeError("Wi-Fi setup access point is active")
    return request()


def handle_pending_button_press():
    global PENDING_BUTTON_PRESS
    global PRINTER_STATUS_UPDATE_REQUIRED

    if not printer_api_ready:
        PENDING_BUTTON_PRESS = False
        return

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

    if not printer_api_ready:
        PRINTER_STATUS_UPDATE_REQUIRED = False
        return

    try:
        response = with_network_connection(
            lambda: api.get_printer_status(config["printer"]["id"])
        )
        PRINTER_AWAITING_PLATE_CLEAR = response["awaiting_plate_clear"]
        CHAMBER_LIGHT_IS_ON = response["chamber_light"]

        print(
            "Printer awaiting plate clear:",
            PRINTER_AWAITING_PLATE_CLEAR,
            "Chamber light is on:",
            CHAMBER_LIGHT_IS_ON,
        )

    except Exception as exc:
        print("Failed to fetch printer status:", exc)

    PRINTER_STATUS_UPDATE_REQUIRED = False


def debug_status():
    try:
        network_config = network.ifconfig()
    except Exception as exc:
        network_config = ("unavailable: {}".format(exc),)

    status = {
        "Network mode": network.mode(),
        "Wi-Fi connected": network.is_connected(),
        "IP address": network_config[0] if network_config else "unavailable",
        "Awaiting plate clear": PRINTER_AWAITING_PLATE_CLEAR,
        "Button press pending": PENDING_BUTTON_PRESS,
        "Chamber light on": CHAMBER_LIGHT_IS_ON,
        "Status update pending": PRINTER_STATUS_UPDATE_REQUIRED,
    }
    status.update({
        "Application version": ota_manager.OTAUpdateManager().status().get(
            "current_version", "legacy"
        ),
    })
    return status


try:
    update_manager = ota_manager.OTAUpdateManager(reset=machine.reset)
    web_server = web_config.WebConfigServer(
        config=config,
        api=api,
        status_provider=debug_status,
        update_manager=update_manager,
    )
    print("Web configuration available at http://{}/".format(network.ifconfig()[0]))
except Exception as exc:
    update_manager = ota_manager.OTAUpdateManager(reset=machine.reset)
    web_server = None
    print("Web configuration server unavailable:", exc)

# -- Main loop --
boot_confirmed = False
while True:
    watchdog.feed()

    restart_requested = web_server is not None and web_server.poll()

    # Push button press to API if pending
    if not restart_requested and not network.is_ap_mode() and PENDING_BUTTON_PRESS:
        handle_pending_button_press()

    # Check printer status
    if (
        not restart_requested
        and not network.is_ap_mode()
        and PRINTER_STATUS_UPDATE_REQUIRED
    ):
        handle_printer_status_update()

    # Confirm only after services have initialized and the first complete main
    # loop pass has run. An early runtime exception or watchdog reset remains
    # eligible for bootloader rollback.
    if web_server is not None and not boot_confirmed:
        update_manager.confirm_boot()
        boot_confirmed = True

    if restart_requested:
        print("Restart requested")
        time.sleep_ms(100)
        machine.reset()

    time.sleep_ms(25)
