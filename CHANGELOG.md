# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/mikeodr/pycasperglow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mikeodr/pycasperglow/releases/tag/v0.1.0
