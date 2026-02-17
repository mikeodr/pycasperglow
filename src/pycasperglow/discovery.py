"""BLE discovery helpers for Casper Glow lights."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .const import DEVICE_NAME_PREFIX, SERVICE_UUID


def is_casper_glow(device: BLEDevice, adv: AdvertisementData) -> bool:
    """Return True if the device appears to be a Casper Glow."""
    if adv.service_uuids and SERVICE_UUID.lower() in (
        u.lower() for u in adv.service_uuids
    ):
        return True
    name = adv.local_name or device.name or ""
    return name.startswith(DEVICE_NAME_PREFIX)


async def discover_glows(timeout: float = 10.0) -> AsyncIterator[BLEDevice]:
    """Scan for Casper Glow devices, yielding each as it is found.

    Devices are yielded immediately on detection rather than waiting for
    the full *timeout* to elapse.  The scan stops once *timeout* seconds
    have passed with no new device discovered.

    Standalone use only (not for HA).
    """
    queue: asyncio.Queue[BLEDevice] = asyncio.Queue()
    seen: set[str] = set()

    def _on_detection(device: BLEDevice, adv: AdvertisementData) -> None:
        if device.address not in seen and is_casper_glow(device, adv):
            seen.add(device.address)
            queue.put_nowait(device)

    scanner = BleakScanner(detection_callback=_on_detection)
    await scanner.start()
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                device = await asyncio.wait_for(queue.get(), timeout=remaining)
                yield device
            except TimeoutError:
                break
    finally:
        await scanner.stop()
