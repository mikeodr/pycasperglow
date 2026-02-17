#!/usr/bin/env python3
"""Test pause and resume on a Casper Glow light.

Turns the light on, waits, pauses the dimming sequence,
waits, resumes it, then turns the light off.
"""

import asyncio
import logging

from _cli import build_parser, matches_filter

from pycasperglow import CasperGlow, discover_glows

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

PAUSE_DELAY = 5.0


async def main() -> None:
    parser = build_parser("Test pause and resume on a Casper Glow light.")
    args = parser.parse_args()

    _LOGGER.info("Scanning for Casper Glow lights (%.0fs)...", args.timeout)
    found = 0
    async for dev in discover_glows(timeout=args.timeout):
        if not matches_filter(dev, args):
            continue
        found += 1
        glow = CasperGlow(dev)
        _LOGGER.info("Testing %s (%s)...", dev.name, dev.address)
        try:
            _LOGGER.info("  Turning on...")
            await glow.turn_on()
            _LOGGER.info("  On. Waiting %.0fs before pause...", PAUSE_DELAY)
            await asyncio.sleep(PAUSE_DELAY)

            _LOGGER.info("  Pausing...")
            await glow.pause()
            input("  Paused. Press Enter to resume...")

            _LOGGER.info("  Resuming...")
            await glow.resume()
            _LOGGER.info("  Resumed. Waiting %.0fs before turn off...", PAUSE_DELAY)
            await asyncio.sleep(PAUSE_DELAY)

            _LOGGER.info("  Turning off...")
            await glow.turn_off()
            _LOGGER.info("  Off. Done.")
        except Exception:
            _LOGGER.exception("  Failed during test sequence for %s", dev.address)

    if not found:
        _LOGGER.info("No Casper Glow lights found.")


if __name__ == "__main__":
    asyncio.run(main())
