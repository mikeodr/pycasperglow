#!/usr/bin/env python3
"""Discover Casper Glow lights and turn them off."""

import asyncio
import logging

from _cli import build_parser, matches_filter

from pycasperglow import CasperGlow, discover_glows

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    parser = build_parser("Discover Casper Glow lights and turn them off.")
    args = parser.parse_args()

    _LOGGER.info("Scanning for Casper Glow lights (%.0fs)...", args.timeout)
    found = 0
    async for dev in discover_glows(timeout=args.timeout):
        if not matches_filter(dev, args):
            continue
        found += 1
        glow = CasperGlow(dev)
        _LOGGER.info("Turning off %s (%s)...", dev.name, dev.address)
        try:
            await glow.turn_off()
            _LOGGER.info("  Success.")
        except Exception:
            _LOGGER.exception("  Failed to turn off %s", dev.address)

    if not found:
        _LOGGER.info("No Casper Glow lights found.")


if __name__ == "__main__":
    asyncio.run(main())
