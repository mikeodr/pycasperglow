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
    devices = await discover_glows(timeout=10.0)
    for device in devices:
        print(f"{device.name} ({device.address})")

asyncio.run(main())
```

### Control a light

```python
import asyncio
from pycasperglow import CasperGlow, discover_glows

async def main():
    devices = await discover_glows()
    if not devices:
        print("No Casper Glow found")
        return

    glow = CasperGlow(devices[0])
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

- **`turn_on()`** — Turn the light on.
- **`turn_off()`** — Turn the light off.
- **`name`** — Device name (property).
- **`address`** — Device BLE address (property).

### `discover_glows(timeout=10.0)`

Scan for Casper Glow devices. Returns a list of `BLEDevice` objects. For standalone use — Home Assistant uses its own discovery.

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
mypy src/ --strict
ruff check src/ tests/
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
