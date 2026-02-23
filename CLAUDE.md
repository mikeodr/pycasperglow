# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pycasperglow is an async Python library for controlling Casper Glow lights via BLE. It is built on bleak and bleak-retry-connector, and is designed to be used as a backend for a Home Assistant integration.

## Running tests

Always execute tests within a venv.

## Commit messages

The commit message format is outlined in CONTRIBUTING.md

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# Run all tests with coverage
pytest tests/ -v --cov=pycasperglow

# Run a single test file
pytest tests/test_protocol.py -v

# Run a single test
pytest tests/test_device.py::TestCasperGlow::test_turn_on_writes_correct_packets -v

# Type checking (strict mode configured in pyproject.toml)
mypy src/ --strict

# Linting
ruff check src/ tests/

# Lint with auto-fix
ruff check --fix src/ tests/
```

## Architecture

This is a src-layout package (`src/pycasperglow/`). The library has a clean separation between protocol logic and I/O:

- **`protocol.py`** — Pure functions (no I/O) for protobuf varint encoding/decoding, session token extraction from BLE notifications, and action packet construction. All protocol logic is testable without mocks.
- **`device.py`** — `CasperGlow` async client that orchestrates the BLE connection state machine: connect → subscribe notifications → write reconnect packet → wait for ready marker → extract token → send action packet → disconnect. Accepts an optional external `BleakClient` for Home Assistant integration (when provided, the client is not disconnected by the library).
- **`discovery.py`** — `is_casper_glow()` for identifying devices by service UUID or name prefix ("Jar"), and `discover_glows()` for standalone scanning (not used by HA).
- **`const.py`** — All BLE UUIDs, packet constants as `bytes` objects, and timeout values.
- **`exceptions.py`** — `CasperGlowError` base, with `ConnectionError`, `HandshakeTimeoutError`, and `CommandError` subclasses.

## Key Design Decisions

- **Fresh connection per command** — each `turn_on()`/`turn_off()` call establishes a new connection, per Home Assistant BLE best practices.
- **External client ownership** — when a `BleakClient` is passed to `CasperGlow`, the library never disconnects it. Only self-created connections are cleaned up in the `finally` block.
- **pytest-asyncio auto mode** — async tests don't need `@pytest.mark.asyncio` decorators.
- **Brightness command includes dimming time** — the BLE protocol sends brightness and dimming time together in a single field-18 protobuf message. `set_brightness()` and `set_dimming_time()` each default the other value when unknown.
- **Battery level from state query** — the battery level is a 4-step discrete enum (`BatteryLevel`) encoded in sub-field 7 of the state response (a nested protobuf message whose inner field 2 holds the value). Raw values map to percentages: 3 = 25 %, 4 = 50 %, 5 = 75 %, 6 = 100 %. Sub-field 8 is always 100 across all captures and is NOT the battery level. Brightness is not reported in the state query response.
- **Sub-field 7 structure (confirmed)** — sub-field 7 of the state response is a nested protobuf message with two fields: inner field 1 is a per-device constant (verified unchanged across all brightness levels 60–100 on the same device), and inner field 2 is the battery level enum. Inner field 1 is NOT brightness.
- **Brightness not in state** — exhaustive live testing (all 5 brightness levels: 60, 70, 80, 90, 100) on a real device confirmed that **no field in the state notification changes with brightness**. The device simply does not report current brightness. `GlowState.brightness_level` is populated only by tracking values sent via `set_brightness()`; it remains `None` after a fresh connection until `set_brightness()` is called.
