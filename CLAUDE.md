# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pycasperglow is an async Python library for controlling Casper Glow lights via BLE. It is built on bleak and bleak-retry-connector, and is designed to be used as a backend for a Home Assistant integration.

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
- **Brightness and dimming are deferred** — command bytes have not been captured yet.
