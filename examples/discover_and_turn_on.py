#!/usr/bin/env python3
"""Discover Casper Glow lights and turn them on."""

import asyncio
import logging

from _cli import build_parser, filter_devices

from pycasperglow import CasperGlow, discover_glows

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    parser = build_parser("Discover Casper Glow lights and turn them on.")
    args = parser.parse_args()

    _LOGGER.info("Scanning for Casper Glow lights (%.0fs)...", args.timeout)
    devices = await discover_glows(timeout=args.timeout)

    if not devices:
        _LOGGER.info("No Casper Glow lights found.")
        return

    devices = filter_devices(devices, args)

    if not devices:
        _LOGGER.info("No devices matched the given filter(s).")
        return

    _LOGGER.info("Found %d light(s):", len(devices))
    for dev in devices:
        _LOGGER.info("  %s (%s)", dev.name, dev.address)

    for dev in devices:
        glow = CasperGlow(dev)
        _LOGGER.info("Turning on %s (%s)...", dev.name, dev.address)
        try:
            await glow.turn_on()
            _LOGGER.info("  Success.")
        except Exception:
            _LOGGER.exception("  Failed to turn on %s", dev.address)


if __name__ == "__main__":
    asyncio.run(main())
