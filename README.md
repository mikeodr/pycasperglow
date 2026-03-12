# pycasperglow

Async Python library for controlling [Casper Glow](https://casper.com/products/glow) lights via BLE.

Built on [bleak](https://github.com/hbldh/bleak) and designed for use as a backend for [Home Assistant](https://www.home-assistant.io/) integrations.

## Installation

```bash
pip install pycasperglow
```

## Usage

### Discover devices

```python
import asyncio
from pycasperglow import discover_glows

async def main():
    async for device in discover_glows(timeout=10.0):
        print(f"{device.name} ({device.address})")

asyncio.run(main())
```

### Control a light

```python
import asyncio
from pycasperglow import CasperGlow, discover_glows

async def main():
    glow = None
    async for device in discover_glows():
        glow = CasperGlow(device)
        break
    if glow is None:
        print("No Casper Glow found")
        return
    await glow.turn_on()
    await asyncio.sleep(5)
    await glow.turn_off()

asyncio.run(main())
```

### Home Assistant integration

When used within Home Assistant's Bluetooth stack, pass the managed `BleakClient` to avoid connection conflicts:

```python
glow = CasperGlow(ble_device, client=bleak_client)
await glow.turn_on()
```

When an external client is provided, `pycasperglow` will not disconnect it — the caller retains ownership.

## API

### `CasperGlow(ble_device, client=None)`

Async client for a single Casper Glow light.

| Method / Property | Description |
|-------------------|-------------|
| `turn_on()` | Turn the light on |
| `turn_off()` | Turn the light off |
| `pause()` | Pause the active dimming sequence |
| `resume()` | Resume a paused dimming sequence |
| `set_brightness_and_dimming_time(level, dimming_time_minutes)` | Set brightness (60–100 %) and dimming duration (15, 30, 45, 60, or 90 min). Both required. |
| `query_state()` | Query current device state; returns `GlowState` |
| `handshake()` | Test connectivity without sending a command |
| `register_callback(cb)` | Register a callback invoked on every state update |
| `state` | Current `GlowState` property (last known, or default) |
| `name` | Device name (property) |
| `address` | BLE address (property) |

### `GlowState`

Dataclass returned by `query_state()` and passed to registered callbacks.

| Field | Type | Description |
|-------|------|-------------|
| `is_on` | `bool \| None` | `True` when on, `False` when off |
| `is_paused` | `bool \| None` | `True` when dimming is paused |
| `is_charging` | `bool \| None` | `True` when plugged in to charger |
| `battery_level` | `BatteryLevel \| None` | Discrete battery level |
| `brightness_level` | `int \| None` | Last-set brightness % (not reported by device) |
| `dimming_time_minutes` | `int \| None` | Remaining dimming time (from device) |
| `configured_dimming_time_minutes` | `int \| None` | Total configured duration |

### `BatteryLevel`

`IntEnum` with four members: `PCT_25`, `PCT_50`, `PCT_75`, `PCT_100`.
Each has a `.percentage` property returning `25`, `50`, `75`, or `100`.

### `discover_glows(timeout=10.0)`

Scan for Casper Glow devices. Async generator that yields `BLEDevice` objects as they are found. For standalone use — Home Assistant uses its own discovery.

### `is_casper_glow(device, adv)`

Returns `True` if a `BLEDevice` and `AdvertisementData` match a Casper Glow (by service UUID or name prefix).

### Exceptions

| Exception | Description |
|-----------|-------------|
| `CasperGlowError` | Base exception |
| `ConnectionError` | Connection or handshake failure |
| `HandshakeTimeoutError` | Device did not become ready in time |
| `CommandError` | Failed to send a command |

## Examples

See the [`examples/`](examples/) directory for runnable scripts. To discover nearby Casper Glow lights and turn them on:

```bash
python examples/discover_and_turn_on.py
```

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run checks:

```bash
pytest tests/ -v --cov=pycasperglow
mypy src/ tests/ examples/ --strict
ruff check src/ tests/ examples/
```

## Protocol

The BLE protocol was partially reverse-engineered from [dengjeffrey/casper-glow-pro](https://github.com/dengjeffrey/casper-glow-pro). The connection flow is:

1. Connect and subscribe to notifications on the read characteristic
2. Write the reconnect packet
3. Wait for a notification containing the ready marker
4. Extract the session token from the notification
5. Build and write the action packet (header + token + action body)
6. Disconnect

## License

MIT
