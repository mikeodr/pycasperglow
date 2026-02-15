"""BLE discovery helpers for Casper Glow lights."""

from __future__ import annotations

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


async def discover_glows(timeout: float = 10.0) -> list[BLEDevice]:
    """Scan for Casper Glow devices. Standalone use only (not for HA)."""
    found: list[BLEDevice] = []
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for device, adv in devices.values():
        if is_casper_glow(device, adv):
            found.append(device)
    return found
