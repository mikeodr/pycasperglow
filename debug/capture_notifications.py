#!/usr/bin/env python3
"""Connect to a Casper Glow and dump decoded BLE notifications.

This debug tool performs the handshake, optionally sends an action,
then sends a state query and pretty-prints every notification received.
Useful for reverse-engineering the notification payload format.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Allow imports from the examples dir for the shared CLI helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

from pycasperglow import CasperGlow, discover_glows
from pycasperglow.protocol import parse_protobuf_fields

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connect to a Casper Glow light and dump decoded notifications."
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=10.0,
        help="BLE scan duration in seconds (default: 10)",
    )
    parser.add_argument(
        "-n",
        "--name",
        type=str,
        default=None,
        help="Glob pattern to filter devices by name (e.g. 'Jar*')",
    )
    parser.add_argument(
        "-a",
        "--address",
        type=str,
        default=None,
        help="Glob pattern to filter devices by BLE address (e.g. 'AA:BB:*')",
    )
    parser.add_argument(
        "--action",
        choices=["on", "off", "pause", "resume", "none"],
        default="none",
        help="Optional action to send before querying state (default: none)",
    )
    return parser


def _dump_fields(data: bytes, label: str, indent: int = 0) -> None:
    """Pretty-print protobuf-like fields from a raw payload."""
    prefix = "  " * indent
    _LOGGER.info("%s%s raw hex: %s", prefix, label, data.hex())
    fields = parse_protobuf_fields(data)
    if not fields:
        _LOGGER.info("%s  (no parseable fields)", prefix)
        return
    for field_num in sorted(fields):
        for val in fields[field_num]:
            if isinstance(val, int):
                _LOGGER.info("%s  field %d (varint): %d", prefix, field_num, val)
            else:
                _LOGGER.info(
                    "%s  field %d (bytes[%d]): %s",
                    prefix,
                    field_num,
                    len(val),
                    val.hex(),
                )
                # Recurse one level into length-delimited sub-messages
                sub = parse_protobuf_fields(val)
                if sub:
                    for sf in sorted(sub):
                        for sv in sub[sf]:
                            if isinstance(sv, int):
                                _LOGGER.info(
                                    "%s    sub-field %d (varint): %d",
                                    prefix,
                                    sf,
                                    sv,
                                )
                            else:
                                _LOGGER.info(
                                    "%s    sub-field %d (bytes[%d]): %s",
                                    prefix,
                                    sf,
                                    len(sv),
                                    sv.hex(),
                                )


async def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _LOGGER.info("Scanning for Casper Glow lights (%.0fs)...", args.timeout)
    devices = await discover_glows(timeout=args.timeout)

    if not devices:
        _LOGGER.info("No Casper Glow lights found.")
        return

    # Apply optional filters
    from _cli import filter_devices

    devices = filter_devices(devices, args)

    if not devices:
        _LOGGER.info("No devices matched the given filter(s).")
        return

    _LOGGER.info("Found %d light(s):", len(devices))
    for dev in devices:
        _LOGGER.info("  %s (%s)", dev.name, dev.address)

    # Process first matching device
    dev = devices[0]
    glow = CasperGlow(dev)
    _LOGGER.info("Connecting to %s (%s)...", dev.name, dev.address)

    # Send optional action first
    if args.action != "none":
        _LOGGER.info("Sending action: %s", args.action)
        action_map = {
            "on": glow.turn_on,
            "off": glow.turn_off,
            "pause": glow.pause,
            "resume": glow.resume,
        }
        try:
            await action_map[args.action]()
            _LOGGER.info("Action sent successfully.")
        except Exception:
            _LOGGER.exception("Failed to send action")
            return

    # Query state
    _LOGGER.info("Querying state...")
    try:
        state = await glow.query_state()
        _LOGGER.info("State result: %s", state)
        if state.raw_state:
            _dump_fields(state.raw_state, "State notification")
    except Exception:
        _LOGGER.exception("Failed to query state")


if __name__ == "__main__":
    asyncio.run(main())
