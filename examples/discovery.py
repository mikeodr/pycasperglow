#!/usr/bin/env python3
"""Discover Casper Glow lights and print their details."""

import asyncio
import logging

from _cli import build_parser, matches_filter

from pycasperglow import CasperGlow, discover_glows

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    parser = build_parser("Discover Casper Glow lights and print their details.")
    parser.add_argument(
        "-s",
        "--state",
        action="store_true",
        help="Query each discovered device for its current state",
    )
    args = parser.parse_args()

    _LOGGER.info("Scanning for Casper Glow lights (%.0fs)...", args.timeout)
    found = 0
    async for dev in discover_glows(timeout=args.timeout):
        if not matches_filter(dev, args):
            continue
        found += 1
        _LOGGER.info("Found: %s (%s)", dev.name, dev.address)

        if args.state:
            glow = CasperGlow(dev)
            _LOGGER.info("Querying state for %s (%s)...", dev.name, dev.address)
            try:
                state = await glow.query_state()
                _LOGGER.info(
                    "  Power: %s",
                    _fmt(state.is_on, {True: "ON", False: "OFF"}),
                )
                _LOGGER.info("  Brightness: %s", _fmt(state.brightness_level))
                _LOGGER.info("  Battery: %s", _fmt(state.battery_level))
                _LOGGER.info("  Paused: %s", _fmt(state.is_paused))
                _LOGGER.info("  Dimming time: %s", _fmt(state.dimming_time_minutes))
            except Exception:
                _LOGGER.exception("  Failed to query state for %s", dev.address)

    if not found:
        _LOGGER.info("No Casper Glow lights found.")


def _fmt(
    value: object,
    labels: dict[object, str] | None = None,
) -> str:
    """Format a state value for display."""
    if value is None:
        return "unknown"
    if labels and value in labels:
        return labels[value]
    return str(value)


if __name__ == "__main__":
    asyncio.run(main())
