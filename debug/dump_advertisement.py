#!/usr/bin/env python3
"""Scan for BLE devices and dump advertisement data for Casper Glow lights.

Prints all advertised service UUIDs, manufacturer data, and service data
so we can determine the correct UUID for Home Assistant discovery.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
_LOGGER = logging.getLogger(__name__)

DEVICE_NAME_PREFIX = "Jar"
KNOWN_SERVICE_UUID = "9bb30001-fee9-4c24-8361-443b5b7c88f6"


def _on_detection(device: BLEDevice, adv: AdvertisementData) -> None:
    name = adv.local_name or device.name or ""
    # Show anything with "Jar" in the name, or the known service UUID
    is_match = name.startswith(DEVICE_NAME_PREFIX) or (
        adv.service_uuids
        and KNOWN_SERVICE_UUID.lower() in (u.lower() for u in adv.service_uuids)
    )
    if not is_match:
        return

    _LOGGER.info("=" * 60)
    _LOGGER.info("Device: %s (%s)", name, device.address)
    _LOGGER.info("RSSI: %s", adv.rssi)
    _LOGGER.info("Advertised service UUIDs: %s", adv.service_uuids)
    _LOGGER.info("Service data: %s", {k: v.hex() for k, v in adv.service_data.items()})
    _LOGGER.info(
        "Manufacturer data: %s",
        {k: v.hex() for k, v in adv.manufacturer_data.items()},
    )
    _LOGGER.info("TX power: %s", adv.tx_power)
    _LOGGER.info("Platform data: %s", adv.platform_data)
    _LOGGER.info("=" * 60)


async def main() -> None:
    timeout = 30.0
    _LOGGER.info(
        "Scanning for BLE devices for %.0fs (looking for '%s*' or known UUID)...",
        timeout,
        DEVICE_NAME_PREFIX,
    )
    scanner = BleakScanner(detection_callback=_on_detection)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    _LOGGER.info("Scan complete.")


if __name__ == "__main__":
    asyncio.run(main())
