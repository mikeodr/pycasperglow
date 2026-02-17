"""Shared CLI helpers for example scripts."""

from __future__ import annotations

import argparse
import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bleak import BLEDevice


def build_parser(description: str) -> argparse.ArgumentParser:
    """Create an argument parser with common discovery/filter flags."""
    parser = argparse.ArgumentParser(description=description)
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
    return parser


def filter_devices(
    devices: list[BLEDevice], args: argparse.Namespace
) -> list[BLEDevice]:
    """Filter discovered devices by name and/or address glob patterns.

    When both --name and --address are given, a device must match both.
    """
    result: list[BLEDevice] = []
    for dev in devices:
        if args.name is not None:
            dev_name = (dev.name or "").lower()
            if not fnmatch.fnmatch(dev_name, args.name.lower()):
                continue
        if args.address is not None and not fnmatch.fnmatch(
            dev.address.upper(), args.address.upper()
        ):
            continue
        result.append(dev)
    return result
