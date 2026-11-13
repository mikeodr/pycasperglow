#!/usr/bin/env python3
"""Manage and test Rise (wake-up) alarms on Casper Glow lights.

Examples:
  # List configured Rise alarms and current state
  python examples/rise.py list

  # Set a weekday 07:30 wake-up alarm with 10m linger (fade-in begins at 07:00)
  python examples/rise.py set 07:30 --days weekdays --linger 10

  # Trigger a Rise fade-in starting ~1 minute from now for quick hardware testing
  python examples/rise.py test

  # Clear all Rise alarms
  python examples/rise.py clear
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta

from _cli import build_parser, matches_filter

from pycasperglow import (
    RISE_LINGER_MINUTES,
    CasperGlow,
    RiseAlarm,
    Weekday,
    discover_glows,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
_LOGGER = logging.getLogger(__name__)

_DAY_ALIASES: dict[str, tuple[Weekday, ...]] = {
    "mon": (Weekday.MONDAY,),
    "monday": (Weekday.MONDAY,),
    "tue": (Weekday.TUESDAY,),
    "tues": (Weekday.TUESDAY,),
    "tuesday": (Weekday.TUESDAY,),
    "wed": (Weekday.WEDNESDAY,),
    "wednesday": (Weekday.WEDNESDAY,),
    "thu": (Weekday.THURSDAY,),
    "thur": (Weekday.THURSDAY,),
    "thurs": (Weekday.THURSDAY,),
    "thursday": (Weekday.THURSDAY,),
    "fri": (Weekday.FRIDAY,),
    "friday": (Weekday.FRIDAY,),
    "sat": (Weekday.SATURDAY,),
    "saturday": (Weekday.SATURDAY,),
    "sun": (Weekday.SUNDAY,),
    "sunday": (Weekday.SUNDAY,),
    "weekdays": (
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
    ),
    "weekends": (Weekday.SATURDAY, Weekday.SUNDAY),
    "daily": tuple(Weekday),
    "everyday": tuple(Weekday),
}

_DAY_SHORT: dict[Weekday, str] = {
    Weekday.MONDAY: "Mon",
    Weekday.TUESDAY: "Tue",
    Weekday.WEDNESDAY: "Wed",
    Weekday.THURSDAY: "Thu",
    Weekday.FRIDAY: "Fri",
    Weekday.SATURDAY: "Sat",
    Weekday.SUNDAY: "Sun",
}


def _parse_time_24h(raw: str) -> tuple[int, int]:
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"Invalid time '{raw}'; expected 24-hour HH:MM (e.g. 07:30)"
        )
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f"Invalid time '{raw}'; expected 24-hour HH:MM"
        ) from err
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise argparse.ArgumentTypeError(
            f"Time out of range '{raw}'; hour must be 0..23 and minute 0..59"
        )
    return hour, minute


def _parse_days(raw: str) -> tuple[Weekday, ...]:
    days: set[Weekday] = set()
    for token in raw.split(","):
        key = token.strip().lower()
        if not key or key in {"once", "none"}:
            continue
        matched = _DAY_ALIASES.get(key)
        if matched is None:
            valid = ", ".join(sorted(_DAY_ALIASES))
            raise argparse.ArgumentTypeError(
                f"Unknown day '{token}'; valid values: {valid}"
            )
        days.update(matched)
    return tuple(sorted(days))


def _format_alarm(alarm: RiseAlarm) -> str:
    days_str = (
        ",".join(_DAY_SHORT[d] for d in alarm.weekdays) if alarm.weekdays else "once"
    )
    status = "enabled" if alarm.enabled else "disabled"
    fade_dt = datetime(2000, 1, 1, alarm.hour, alarm.minute) - timedelta(minutes=30)
    return (
        f"{alarm.hour:02d}:{alarm.minute:02d} "
        f"(fade-in starts {fade_dt.hour:02d}:{fade_dt.minute:02d}, "
        f"linger={alarm.linger_minutes}m, repeat={days_str}, "
        f"{status}, sync_id={alarm.sync_id})"
    )


def _create_parser() -> argparse.ArgumentParser:
    parser = build_parser(
        "Manage and test Rise (wake-up) alarms on Casper Glow lights."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list",
        help="Query configured Rise alarms and current state from the light",
    )

    set_parser = subparsers.add_parser(
        "set",
        help="Schedule a Rise wake-up alarm (HH:MM peak brightness time)",
    )
    set_parser.add_argument(
        "time",
        type=_parse_time_24h,
        help=(
            "Target peak wake-up time in 24-hour HH:MM "
            "(sunrise fade-in begins 30m earlier)"
        ),
    )
    set_parser.add_argument(
        "--linger",
        type=int,
        choices=RISE_LINGER_MINUTES,
        default=10,
        help="Minutes to stay at full brightness after wake-up time (default: 10)",
    )
    set_parser.add_argument(
        "--days",
        type=_parse_days,
        default=(),
        help=(
            "Comma-separated repeat days "
            "(e.g. mon,tue,wed,thu,fri, weekdays, weekends, daily)"
        ),
    )
    set_parser.add_argument(
        "--disabled",
        action="store_true",
        help="Store the alarm in a disabled state",
    )
    set_parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Append to existing alarms on the light instead of replacing them",
    )
    set_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip reading back the Rise schedule after setting it",
    )

    test_parser = subparsers.add_parser(
        "test",
        help="Schedule a one-off Rise test alarm whose 30-min fade-in starts shortly",
    )
    test_parser.add_argument(
        "--start-in-minutes",
        type=int,
        default=1,
        help="Minutes from now until the 30-minute sunrise fade-in begins (default: 1)",
    )
    test_parser.add_argument(
        "--linger",
        type=int,
        choices=RISE_LINGER_MINUTES,
        default=5,
        help="Linger duration in minutes at peak brightness (default: 5)",
    )

    clear_parser = subparsers.add_parser(
        "clear",
        help="Clear all Rise wake-up alarms from the light",
    )
    clear_parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Also send a delete command for legacy v1 firmware Rise alarms",
    )

    subparsers.add_parser(
        "sync-clock",
        help="Synchronise the light's real-time clock and local timezone/DST offset",
    )
    return parser


async def _handle_device(glow: CasperGlow, args: argparse.Namespace) -> None:
    if args.command == "list":
        alarms = await glow.query_rises()
        state = await glow.query_state()
        anim = (
            state.animation_type.name if state.animation_type is not None else "unknown"
        )
        _LOGGER.info(
            "  State: is_on=%s, animation=%s, paused=%s, battery=%s, charging=%s",
            state.is_on,
            anim,
            state.is_paused,
            state.battery_level,
            state.is_charging,
        )
        if not alarms:
            _LOGGER.info("  Rise alarms: (none)")
        else:
            _LOGGER.info("  Rise alarms (%d):", len(alarms))
            for alarm in alarms:
                _LOGGER.info("    - %s", _format_alarm(alarm))
        return

    if args.command == "sync-clock":
        now = datetime.now().astimezone()
        await glow.sync_clock(now=now)
        _LOGGER.info("  Synced device clock to %s.", now.isoformat(timespec="seconds"))
        return

    if args.command == "clear":
        await glow.clear_rises(include_legacy=args.include_legacy)
        _LOGGER.info("  Cleared all Rise alarms.")
        return

    if args.command == "test":
        if args.start_in_minutes < 1:
            raise ValueError("--start-in-minutes must be >= 1")
        now = datetime.now().astimezone()
        next_min = (now + timedelta(minutes=args.start_in_minutes)).replace(
            second=0, microsecond=0
        )
        if next_min <= now:
            next_min += timedelta(minutes=1)
        peak_dt = next_min + timedelta(minutes=30)
        alarm = await glow.set_rise(
            peak_dt.hour,
            peak_dt.minute,
            linger_minutes=args.linger,
            now=now,
        )
        _LOGGER.info("  Scheduled test Rise: %s", _format_alarm(alarm))
        _LOGGER.info(
            "  Fade-in begins at %s (~%ds from now) and peaks at %s.",
            next_min.strftime("%H:%M:%S"),
            max(0, int((next_min - now).total_seconds())),
            peak_dt.strftime("%H:%M:%S"),
        )
        readback = await glow.query_rises()
        _LOGGER.info("  Verified %d alarm(s) stored on light.", len(readback))
        return

    if args.command == "set":
        hour, minute = args.time
        new_alarm = RiseAlarm(
            hour=hour,
            minute=minute,
            linger_minutes=args.linger,
            enabled=not args.disabled,
            weekdays=args.days,
        )
        alarms_to_set: list[RiseAlarm] = []
        if args.keep_existing:
            alarms_to_set.extend(await glow.query_rises())
        alarms_to_set.append(new_alarm)

        stored = await glow.set_rises(alarms_to_set)
        _LOGGER.info("  Configured %d Rise alarm(s):", len(stored))
        for item in stored:
            _LOGGER.info("    - %s", _format_alarm(item))

        if not args.no_verify:
            readback = await glow.query_rises()
            _LOGGER.info("  Verified %d alarm(s) stored on light.", len(readback))


async def main() -> None:
    parser = _create_parser()
    args = parser.parse_args()

    _LOGGER.info("Scanning for Casper Glow lights (%.0fs)...", args.timeout)
    found = 0
    async for dev in discover_glows(timeout=args.timeout):
        if not matches_filter(dev, args):
            continue
        found += 1
        glow = CasperGlow(dev)
        _LOGGER.info("Device %s (%s):", dev.name, dev.address)
        try:
            await _handle_device(glow, args)
        except Exception:
            _LOGGER.exception("  Failed while handling %s", dev.address)

    if not found:
        _LOGGER.info("No matching Casper Glow lights found.")


if __name__ == "__main__":
    asyncio.run(main())
