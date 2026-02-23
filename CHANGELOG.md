# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.7] - 2026-02-23

### Added

- `BatteryLevel` enum with four members (`PCT_25`, `PCT_50`, `PCT_75`, `PCT_100`) mapping raw device values (3–6) to their corresponding percentage. Exported from the top-level package.

### Fixed

- Battery level was always reported as 100 due to reading the wrong protobuf field (sub-field 8, a device constant). Now correctly read from sub-field 7 inner field 2 — a 4-step discrete enum.
- `set_dimming_time()` no longer silently defaults to 100 % brightness when brightness is unknown; it now raises `ValueError` with a descriptive message requiring `set_brightness()` to be called first.

### Changed

- `GlowState.battery_level` type changed from `int | None` to `BatteryLevel | None`.
- `examples/discovery.py` battery display updated to use `BatteryLevel` string representation (`"25%"`, `"50%"`, etc.).

## [0.3.6] - 2026-02-23

### Changed

- Remaining dimming time is no longer updated when selecting new dimming option, this reflects true device operation

## [0.3.5] - 2026-02-23

### Changed

- Lowered minimum python version to 3.12
- Set development status to beta

## [0.3.4] - 2026-02-22

### Fixes

- Correct dimming time remaining

### Updated

- Makefile format fix
- Claude instructions

## [0.3.3] - 2026-02-22

### Fixes

- Linting error

### Added

- Makefile and git hooks to make less mistakes

## [0.3.2] - 2026-02-22

### Fixed

- Configured dimming time should not be passed back as remaining dimming time left.

## [0.3.1] - 2026-02-17

### Added

- Concurrency lock for command and state updates

## [0.3.0] - 2026-02-16

### Added

- State query support via `query_state()` — decodes power, paused, dimming time, and battery level from BLE notifications.
- `build_brightness_body()` protocol function for constructing verified brightness/dimming command packets (protobuf field 18).
- `set_brightness()` — set brightness percentage (60, 70, 80, 90, 100), verified against iOS app BLE captures.
- `set_dimming_time()` — set dimming time (15, 30, 45, 60, 90 minutes), verified against iOS app BLE captures.
- `battery_level` field on `GlowState` (parsed from sub-field 8 of state response).
- `raw_state` field on `GlowState` for storing the raw notification bytes.
- `BRIGHTNESS_LEVELS` constant exported from the package.
- Generic protobuf field parser (`parse_protobuf_fields()`) and state response decoder (`parse_state_response()`) in protocol module.
- `discovery.py` example script with `--state` flag for querying device state.
- Shared CLI helpers (`examples/_cli.py`) with `--timeout`, `--name`, and `--address` filter flags.
- `debug/capture_notifications.py` tool for dumping decoded BLE notifications.

### Changed

- All example scripts now use shared CLI flags (`--timeout`, `--name`, `--address`) for filtering devices.
- `set_brightness()` now accepts percentage values (60–100) instead of levels (1–5).

### Removed

- Unverified brightness and dimming time constants (`ACTION_BODY_DIM_*`, `ACTION_BODY_BRIGHTNESS_*`, `DIMMING_TIME_TO_ACTION`, `BRIGHTNESS_TO_ACTION`) replaced with capture-verified protocol implementation.

### Fixed

- Copy-paste bug in `discover_and_turn_off.py` (was logging "turning on" messages).

## [0.2.1] - 2026-02-16

### Fixed

- Removed unused imports flagged by ruff.

## [0.2.0] - 2026-02-16

### Added

- `pause()` and `resume()` methods for controlling dimming sequences.
- `GlowState` dataclass for tracking device state (on/off, paused).
- Callback registration via `register_callback()` for state change notifications.
- `handshake()` method for testing connectivity without sending a command.
- `set_ble_device()` for updating the BLE device reference.
- `set_dimming_time()` and `set_brightness()` method stubs (raise `NotImplementedError` pending capture validation).

### Fixed

- Action packet structure now matches the real device protocol: field 1 = constant 1, field 2 = session token, field 4 = length-delimited action body.
- Corrected pause action byte from `0x06` to `0x05`.
- Corrected resume action byte from `0x08` to `0x06`.

## [0.1.0] - 2026-02-16

### Added

- Initial release.
- `CasperGlow` async client with `turn_on()` and `turn_off()`.
- BLE discovery via `discover_glows()` and `is_casper_glow()`.
- Protobuf varint encoding/decoding and session token extraction.
- Support for external `BleakClient` (Home Assistant integration).
- Typed package with `py.typed` marker.

[0.3.7]: https://github.com/mikeodr/pycasperglow/compare/v0.3.6...v0.3.7
[0.3.6]: https://github.com/mikeodr/pycasperglow/compare/v0.3.5...v0.3.6
[0.3.5]: https://github.com/mikeodr/pycasperglow/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/mikeodr/pycasperglow/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/mikeodr/pycasperglow/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/mikeodr/pycasperglow/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/mikeodr/pycasperglow/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/mikeodr/pycasperglow/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/mikeodr/pycasperglow/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/mikeodr/pycasperglow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mikeodr/pycasperglow/releases/tag/v0.1.0
