# v1.0.0 release qualification

The release workflow runs CI against the tagged commit and refuses to publish
unless the tag points at the current `main` commit and
[`release-validation.json`](release-validation.json) records a passing hardware
rehearsal against that exact commit and tag. Update the record in a commit on `main` after the
checks below pass, then tag that verified commit.

## Automated checks

- The required `CI / Quality` check passes on the pull request and the final
  `main` commit.
- The `CI / Desktop smoke (windows-latest)` and
  `CI / Desktop smoke (macos-latest)` checks pass.
- CI reports per-file coverage for every Python source file in `micro/`,
  `src/`, and `scripts/`; each file has at least 25% coverage and total coverage
  is at least 70%.
- The wheel and source distribution install and contain the firmware and
  MicroPython runtime resources.
- The exact OTA JSON asset built for the tag passes the device validator.

## ESP32-C3 rehearsal

Run these checks on the named board with a data-capable USB cable. Record the
board model/revision, MicroPython firmware image/version, test date, commit,
and result in `release-validation.json`.

- Erase the board and perform a fresh USB install with the release tool.
- Upgrade over USB from the last published release while preserving settings.
- Save settings, interrupt power during the save, and verify the board boots
  with either the old or new complete settings.
- Request a plate clear with the API unavailable, restore Bambuddy/Wi-Fi, and
  verify the queued press resolves once without losing the LED indication.
- Install an OTA update from the web UI, including a web UI file larger than
  the former 32 KiB limit; verify boot confirmation and active-slot contents.
- Interrupt an OTA update and verify the prior application remains bootable.
- Use the released Windows and macOS setup tools with the board and confirm
  that each completes a USB install and starts the configured application.

`release-validation.json` intentionally starts in `pending` state. A software
CI pass cannot substitute for these checks on the ESP32-C3 and desktop
platforms.
