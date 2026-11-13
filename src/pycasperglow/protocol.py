"""Pure protocol logic for Casper Glow BLE communication.

Handles protobuf varint/fixed32/ZigZag encoding and decoding, session token
extraction, notification field parsing, clock synchronisation, Rise (wake-up
alarm) scheduling, and action packet construction. No I/O.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone

from .const import (
    MAX_RISE_SLOTS,
    MAX_RISES_PER_PACKET,
    READY_MARKER,
    RISE_LINGER_MINUTES,
)

# Protobuf field numbers inside nova_message_payload (field 4 of nova_message)
STATE_RESPONSE_FIELD = 19
SET_RISE_FIELD = 20
SET_CLOCK_FIELD = 21
RISE_CONFIG_FIELD = 24
REQUEST_RISE_CONFIG_FIELD = 25

# Bit flags for nova_rise_config.rise_config_flags
RISE_CONFIG_FLAG_FIRST_PACKET = 0x01
RISE_CONFIG_FLAG_LAST_PACKET = 0x02

# Bit flags for nova_rise.rise_flags
RISE_FLAG_ENABLED = 0x01
RISE_FLAG_REPEATS_WEEKLY = 0x02
RISE_FLAG_LINGER_PACKED_60_5 = 0x04

# Sentinel uint32 (-1 as unsigned 32-bit) indicating no upcoming DST transition
NO_DST_TRANSITION = 0xFFFFFFFF


class Weekday(enum.IntEnum):
    """Day of the week matching Python's ``datetime.weekday()`` convention."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True)
class RiseAlarm:
    """Configuration for a Casper Glow wake-up ("Rise") alarm.

    The Casper Glow begins its warm sunrise fade-in 30 minutes *before* the
    configured ``(hour, minute)`` target wake-up time, reaches peak brightness
    at ``(hour, minute)``, and stays lit for ``linger_minutes`` before turning
    off.

    When ``weekdays`` is empty, the alarm triggers once (today if the target
    time is still ahead, otherwise tomorrow). When ``weekdays`` contains one or
    more :class:`Weekday` values, the alarm repeats weekly on those days.
    """

    hour: int
    minute: int
    linger_minutes: int = 10
    enabled: bool = True
    weekdays: tuple[Weekday, ...] = ()
    sync_id: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23:
            raise ValueError(f"hour must be in 0..23, got {self.hour}")
        if not 0 <= self.minute <= 59:
            raise ValueError(f"minute must be in 0..59, got {self.minute}")
        if (
            self.linger_minutes < 0
            or self.linger_minutes % 5 != 0
            or self.linger_minutes > 295
        ):
            raise ValueError(
                f"linger_minutes must be a multiple of 5 in 0..295, "
                f"got {self.linger_minutes}"
            )
        if not 0 <= self.sync_id <= 0xFFFF:
            raise ValueError(f"sync_id must be in 0..65535, got {self.sync_id}")
        normalized = tuple(sorted({Weekday(day) for day in self.weekdays}))
        object.__setattr__(self, "weekdays", normalized)

    @property
    def repeats_weekly(self) -> bool:
        """Return True if this alarm repeats weekly on one or more weekdays."""
        return bool(self.weekdays)


@dataclass(frozen=True)
class ParsedRiseConfigPacket:
    """Decoded ``nova_rise_config`` notification packet from the device."""

    start: int
    first_packet: bool
    last_packet: bool
    entries: tuple[tuple[int, int], ...]


def parse_varint(data: bytes, start: int = 0) -> tuple[int, int]:
    """Decode a protobuf varint from data starting at the given offset.

    Returns (value, next_offset).
    Raises ValueError if data is truncated.
    """
    result = 0
    shift = 0
    pos = start
    while pos < len(data):
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not byte & 0x80:
            return result, pos
        shift += 7
    raise ValueError("Truncated varint")


def encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    if value < 0:
        raise ValueError("Varint must be non-negative")
    parts: list[int] = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value)
    return bytes(parts)


def encode_zigzag32(value: int) -> int:
    """Encode a signed 32-bit integer as an unsigned 32-bit ZigZag integer."""
    if not -(1 << 31) <= value < (1 << 31):
        raise ValueError(f"Value out of signed 32-bit range: {value}")
    return ((value << 1) ^ (value >> 31)) & 0xFFFFFFFF


def decode_zigzag32(value: int) -> int:
    """Decode an unsigned 32-bit protobuf ZigZag integer to a signed int."""
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"Value out of unsigned 32-bit range: {value}")
    return (value >> 1) ^ -(value & 1)


def encode_fixed32(value: int) -> bytes:
    """Encode an unsigned 32-bit integer as 4 little-endian bytes (wire type 5)."""
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"fixed32 value out of range: {value}")
    return value.to_bytes(4, "little")


def payload_contains_ready_marker(payload: bytes) -> bool:
    """Check if a notification payload contains the ready marker."""
    return READY_MARKER in payload


def extract_token_from_notify(payload: bytes) -> int | None:
    """Extract the session token from a notification payload.

    The notification payload is a protobuf structure. The session token
    is carried in field 1 (tag byte 0x08) as a varint, typically near the
    start of the payload. Returns None if no token field is found.
    """
    pos = 0
    while pos < len(payload):
        try:
            tag_byte, pos = parse_varint(payload, pos)
        except ValueError:
            return None
        field_number = tag_byte >> 3
        wire_type = tag_byte & 0x07

        if wire_type == 0:  # varint
            try:
                value, pos = parse_varint(payload, pos)
            except ValueError:
                return None
            if field_number == 1:
                return value
        elif wire_type == 1:  # fixed64
            if pos + 8 > len(payload):
                return None
            pos += 8
        elif wire_type == 2:  # length-delimited
            try:
                length, pos = parse_varint(payload, pos)
            except ValueError:
                return None
            if pos + length > len(payload):
                return None
            pos += length
        elif wire_type == 5:  # fixed32
            if pos + 4 > len(payload):
                return None
            pos += 4
        else:
            # Unknown wire type — can't continue safely
            return None
    return None


def parse_protobuf_fields(data: bytes) -> dict[int, list[int | bytes]]:
    """Parse a protobuf payload into a dict of field_number -> values.

    Supports wire types 0 (varint), 1 (fixed64), 2 (length-delimited), and
    5 (fixed32). Each field number maps to a list of values since protobuf
    fields can repeat. Varint, fixed32, and fixed64 fields produce ``int``
    values; length-delimited fields produce ``bytes``.

    Returns the fields parsed before any malformed trailing data.
    """
    fields: dict[int, list[int | bytes]] = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = parse_varint(data, pos)
        except ValueError:
            return fields
        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # varint
            try:
                value, pos = parse_varint(data, pos)
            except ValueError:
                return fields
            fields.setdefault(field_number, []).append(value)
        elif wire_type == 1:  # fixed64
            if pos + 8 > len(data):
                return fields
            val64 = int.from_bytes(data[pos : pos + 8], "little")
            fields.setdefault(field_number, []).append(val64)
            pos += 8
        elif wire_type == 2:  # length-delimited
            try:
                length, pos = parse_varint(data, pos)
            except ValueError:
                return fields
            if pos + length > len(data):
                return fields
            fields.setdefault(field_number, []).append(data[pos : pos + length])
            pos += length
        elif wire_type == 5:  # fixed32
            if pos + 4 > len(data):
                return fields
            val32 = int.from_bytes(data[pos : pos + 4], "little")
            fields.setdefault(field_number, []).append(val32)
            pos += 4
        else:
            # Unknown wire type — stop parsing
            return fields
    return fields


def parse_state_response(notification: bytes) -> dict[int, list[int | bytes]] | None:
    """Extract and decode the state response (field 19) from a notification.

    The notification wraps the state response inside field 4 (the body).
    Field 19 sits inside field 4, not at the top level.

    Returns the parsed sub-fields of the field-19 body, or None if
    the notification does not contain a state response.
    """
    top = parse_protobuf_fields(notification)

    # Field 19 is nested inside field 4's body
    field4_values = top.get(4)
    if not field4_values:
        return None
    field4_body = field4_values[-1]
    if not isinstance(field4_body, bytes):
        return None

    inner = parse_protobuf_fields(field4_body)
    state_values = inner.get(STATE_RESPONSE_FIELD)
    if not state_values:
        return None
    body = state_values[-1]
    if not isinstance(body, bytes):
        return None
    return parse_protobuf_fields(body)


def build_action_packet(token: int, action_body: bytes) -> bytes:
    """Build a full command packet from a session token and action body.

    Packet structure (protobuf):
      field 1 (varint) = 1           (constant, tag 0x08)
      field 2 (varint) = token       (session token, tag 0x10)
      field 4 (length-delimited) = action_body  (tag 0x22)
    """
    return (
        b"\x08\x01"
        + b"\x10"
        + encode_varint(token)
        + b"\x22"
        + encode_varint(len(action_body))
        + action_body
    )


# Protobuf tags for length-delimited payload sub-messages (wire type 2)
_FIELD_18_TAG = encode_varint((18 << 3) | 2)
_FIELD_20_TAG = encode_varint((SET_RISE_FIELD << 3) | 2)
_FIELD_21_TAG = encode_varint((SET_CLOCK_FIELD << 3) | 2)
_FIELD_24_TAG = encode_varint((RISE_CONFIG_FIELD << 3) | 2)


def build_brightness_body(
    brightness_pct: int,
    dimming_time_ms: int,
) -> bytes:
    """Build an action body to set brightness and dimming time.

    The brightness command uses protobuf field 18 with:
      sub-field 2 = brightness percentage (60–100, in steps of 10)
      sub-field 3 = dimming time in milliseconds

    Verified against iOS app BLE captures.
    """
    inner = (
        b"\x10"
        + encode_varint(brightness_pct)
        + b"\x18"
        + encode_varint(dimming_time_ms)
    )
    return _FIELD_18_TAG + encode_varint(len(inner)) + inner


def _ensure_aware(now: datetime | None) -> datetime:
    """Return a timezone-aware datetime, defaulting to local system time."""
    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is None or now.utcoffset() is None:
        return now.astimezone()
    return now


def _utc_offset_seconds(dt: datetime) -> int:
    offset = dt.utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds())


def _find_next_dst_transition(aware_dt: datetime) -> tuple[int, int]:
    """Find the next UTC offset transition within 370 days for ``aware_dt.tzinfo``.

    Returns ``(transition_utc_epoch, new_offset_seconds)``, or
    ``(NO_DST_TRANSITION, 0)`` if the timezone has a fixed offset or no
    transition within the next 370 days.
    """
    tz = aware_dt.tzinfo
    if tz is None or isinstance(tz, timezone):
        return NO_DST_TRANSITION, 0

    start_ts = int(aware_dt.timestamp())
    base_offset = _utc_offset_seconds(aware_dt)

    def _offset_at(ts: int) -> int:
        return _utc_offset_seconds(datetime.fromtimestamp(ts, tz=tz))

    step = 2 * 86_400  # 2-day coarse scan
    horizon = start_ts + 370 * 86_400
    lo = start_ts
    hi = min(start_ts + step, horizon)
    while lo < horizon:
        if _offset_at(hi) != base_offset:
            while lo + 1 < hi:
                mid = (lo + hi) // 2
                if _offset_at(mid) == base_offset:
                    lo = mid
                else:
                    hi = mid
            return hi & 0xFFFFFFFF, _offset_at(hi)
        lo = hi
        hi = min(hi + step, horizon)

    return NO_DST_TRANSITION, 0


def build_set_clock_body(now: datetime | None = None) -> bytes:
    """Build a ``nova_set_clock`` (payload field 21) action body.

    Synchronises the light's real-time clock, local UTC offset, and next DST
    transition — required by firmware for scheduled Rise alarms to trigger at
    the expected wall-clock time.

    Inner fields of ``nova_set_clock``:
      field 1 (``clock``, uint32 varint) = current UTC Unix epoch seconds
      field 2 (``local_offset_from_utc``, sint32 ZigZag) = current UTC offset (s)
      field 3 (``next_dst_event``, uint32 varint) = next DST epoch or 0xFFFFFFFF
      field 4 (``next_local_offset_from_utc``, sint32 ZigZag) = next offset (s)
    """
    aware_now = _ensure_aware(now)
    clock_utc = int(aware_now.timestamp()) & 0xFFFFFFFF
    local_offset = _utc_offset_seconds(aware_now)
    next_dst_event, next_local_offset = _find_next_dst_transition(aware_now)

    inner = (
        b"\x08"
        + encode_varint(clock_utc)
        + b"\x10"
        + encode_varint(encode_zigzag32(local_offset))
        + b"\x18"
        + encode_varint(next_dst_event)
        + b"\x20"
        + encode_varint(encode_zigzag32(next_local_offset))
    )
    return _FIELD_21_TAG + encode_varint(len(inner)) + inner


def encode_rise_config_flags(*, first_packet: bool, last_packet: bool) -> int:
    """Encode ``nova_rise_config.rise_config_flags`` bitmask."""
    flags = RISE_CONFIG_FLAG_FIRST_PACKET if first_packet else 0
    if last_packet:
        flags |= RISE_CONFIG_FLAG_LAST_PACKET
    return flags


def encode_rise_flags(
    *,
    enabled: bool,
    repeats_weekly: bool,
    sync_id: int,
) -> int:
    """Encode ``nova_rise.rise_flags`` bitmask.

    Bits:
      bit 0 (0x01)   = enabled
      bit 1 (0x02)   = repeats weekly
      bit 2 (0x04)   = linger_packed_60_5 (linger / 5 stored in time_utc seconds)
      bits 16..31    = 16-bit sync_id grouping unrolled weekday slots
    """
    if not 0 <= sync_id <= 0xFFFF:
        raise ValueError(f"sync_id must be in 0..65535, got {sync_id}")
    flags = RISE_FLAG_LINGER_PACKED_60_5
    if enabled:
        flags |= RISE_FLAG_ENABLED
    if repeats_weekly:
        flags |= RISE_FLAG_REPEATS_WEEKLY
    flags |= (sync_id & 0xFFFF) << 16
    return flags


def decode_rise_flags(flags: int) -> tuple[bool, bool, bool, int]:
    """Decode ``rise_flags`` into ``(enabled, repeats_weekly, packed, sync_id)``."""
    enabled = bool(flags & RISE_FLAG_ENABLED)
    repeats_weekly = bool(flags & RISE_FLAG_REPEATS_WEEKLY)
    linger_packed = bool(flags & RISE_FLAG_LINGER_PACKED_60_5)
    sync_id = (flags >> 16) & 0xFFFF
    return enabled, repeats_weekly, linger_packed, sync_id


def calculate_rise_time_utc(
    hour: int,
    minute: int,
    linger_minutes: int,
    *,
    now: datetime | None = None,
    weekday: Weekday | None = None,
) -> int:
    """Compute ``nova_rise.time_utc`` matching the Casper Glow Multi-Rise protocol.

    Multi-Rise stores local wall-clock ``(year, month, day, hour, minute)``
    directly in a UTC epoch timestamp (timezone-shifted so alarms stay anchored
    to wall-clock time across DST), with ``linger_minutes // 5`` packed into
    the seconds component (`0..59`).
    """
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be in 0..23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be in 0..59, got {minute}")
    if linger_minutes < 0 or linger_minutes % 5 != 0 or linger_minutes > 295:
        raise ValueError(
            f"linger_minutes must be a multiple of 5 in 0..295, got {linger_minutes}"
        )

    aware_now = _ensure_aware(now)
    now_local_as_utc = aware_now.replace(tzinfo=UTC)
    candidate = now_local_as_utc.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )

    if weekday is None:
        if candidate < now_local_as_utc:
            candidate += timedelta(days=1)
    else:
        target_day = Weekday(weekday)
        days_offset = int(target_day) - now_local_as_utc.weekday()
        candidate += timedelta(days=days_offset)
        if candidate < now_local_as_utc:
            candidate += timedelta(days=7)

    return (int(candidate.timestamp()) + (linger_minutes // 5)) & 0xFFFFFFFF


def assign_rise_sync_ids(alarms: Sequence[RiseAlarm]) -> list[RiseAlarm]:
    """Ensure every :class:`RiseAlarm` has a unique non-zero 16-bit ``sync_id``.

    Existing non-zero ``sync_id`` values are preserved; alarms with
    ``sync_id == 0`` are assigned sequential unused positive 16-bit IDs
    (starting from 1 so they are also positive signed ``short`` values in the
    official Android/iOS apps).
    """
    used = {alarm.sync_id for alarm in alarms if alarm.sync_id != 0}
    next_id = 1
    result: list[RiseAlarm] = []
    for alarm in alarms:
        if alarm.sync_id != 0:
            result.append(alarm)
            continue
        while next_id in used:
            next_id += 1
            if next_id > 0xFFFF:
                raise ValueError("Exhausted 16-bit sync_id space")
        used.add(next_id)
        result.append(replace(alarm, sync_id=next_id))
    return result


def build_rise_entry(time_utc: int, rise_flags: int) -> bytes:
    """Build a single ``nova_rise`` protobuf sub-message."""
    return (
        b"\x0d"
        + encode_fixed32(time_utc)
        + b"\x10"
        + encode_varint(rise_flags & 0xFFFFFFFF)
    )


def build_rise_config_bodies(
    alarms: Sequence[RiseAlarm],
    *,
    now: datetime | None = None,
) -> list[bytes]:
    """Build one or more ``nova_rise_config`` (payload field 24) action bodies.

    * Validates each alarm's ``linger_minutes`` against :data:`RISE_LINGER_MINUTES`.
    * Auto-assigns non-zero ``sync_id`` values to alarms with ``sync_id == 0``.
    * Unrolls weekly repeating alarms into one ``nova_rise`` slot per weekday
      (enforcing :data:`MAX_RISE_SLOTS` = 16 total slots).
    * Splits slots into chunks of up to :data:`MAX_RISES_PER_PACKET` = 8 slots
      so every packet stays well within the 161-byte BLE MTU.
    * When ``alarms`` is empty, returns a single empty ``nova_rise_config``
      packet with ``first_packet | last_packet`` (`0x03`) that clears all
      Multi-Rise alarms on the device.
    """
    for alarm in alarms:
        if alarm.linger_minutes not in RISE_LINGER_MINUTES:
            raise ValueError(
                f"Invalid linger_minutes {alarm.linger_minutes}; "
                f"must be one of {RISE_LINGER_MINUTES}"
            )

    aware_now = _ensure_aware(now)
    assigned = assign_rise_sync_ids(alarms)

    encoded_entries: list[bytes] = []
    for alarm in assigned:
        flags = encode_rise_flags(
            enabled=alarm.enabled,
            repeats_weekly=alarm.repeats_weekly,
            sync_id=alarm.sync_id,
        )
        if not alarm.weekdays:
            time_utc = calculate_rise_time_utc(
                alarm.hour,
                alarm.minute,
                alarm.linger_minutes,
                now=aware_now,
                weekday=None,
            )
            encoded_entries.append(build_rise_entry(time_utc, flags))
        else:
            for day in alarm.weekdays:
                time_utc = calculate_rise_time_utc(
                    alarm.hour,
                    alarm.minute,
                    alarm.linger_minutes,
                    now=aware_now,
                    weekday=day,
                )
                encoded_entries.append(build_rise_entry(time_utc, flags))

    if len(encoded_entries) > MAX_RISE_SLOTS:
        raise ValueError(
            f"Total unrolled Rise slots ({len(encoded_entries)}) exceeds "
            f"device maximum of {MAX_RISE_SLOTS}"
        )

    total = len(encoded_entries)
    packet_count = max(1, (total + MAX_RISES_PER_PACKET - 1) // MAX_RISES_PER_PACKET)
    bodies: list[bytes] = []
    for idx in range(packet_count):
        start = idx * MAX_RISES_PER_PACKET
        chunk = encoded_entries[start : start + MAX_RISES_PER_PACKET]
        cfg_flags = encode_rise_config_flags(
            first_packet=(idx == 0),
            last_packet=(idx == packet_count - 1),
        )
        inner = (
            b"\x08"
            + encode_varint(start)
            + b"\x10"
            + encode_varint(cfg_flags)
            + b"".join(b"\x1a" + encode_varint(len(entry)) + entry for entry in chunk)
        )
        bodies.append(_FIELD_24_TAG + encode_varint(len(inner)) + inner)

    return bodies


def build_delete_legacy_rise_body() -> bytes:
    """Build a ``nova_set_rise`` (field 20) body deleting a legacy v1 alarm."""
    inner = b"\x20" + encode_varint(0xFFFFFFFF)
    return _FIELD_20_TAG + encode_varint(len(inner)) + inner


def parse_rise_config_notification(
    notification: bytes,
) -> ParsedRiseConfigPacket | None:
    """Extract and decode ``nova_rise_config`` (field 24) from a notification.

    Returns :class:`ParsedRiseConfigPacket`, or ``None`` if the notification
    does not carry a ``nova_rise_config`` sub-message.
    """
    top = parse_protobuf_fields(notification)
    field4_values = top.get(4)
    if not field4_values:
        return None
    field4_body = field4_values[-1]
    if not isinstance(field4_body, bytes):
        return None

    inner = parse_protobuf_fields(field4_body)
    rise_cfg_values = inner.get(RISE_CONFIG_FIELD)
    if not rise_cfg_values:
        return None
    cfg_body = rise_cfg_values[-1]
    if not isinstance(cfg_body, bytes):
        return None

    cfg = parse_protobuf_fields(cfg_body)
    start_vals = cfg.get(1)
    start = (
        start_vals[0]
        if start_vals is not None and isinstance(start_vals[0], int)
        else 0
    )

    flag_vals = cfg.get(2)
    if flag_vals is not None and isinstance(flag_vals[0], int):
        raw_cfg_flags = flag_vals[0]
        first_packet = bool(raw_cfg_flags & RISE_CONFIG_FLAG_FIRST_PACKET)
        last_packet = bool(raw_cfg_flags & RISE_CONFIG_FLAG_LAST_PACKET)
    else:
        first_packet = True
        last_packet = True

    entries: list[tuple[int, int]] = []
    for raw_entry in cfg.get(3, []):
        if not isinstance(raw_entry, bytes):
            continue
        entry_fields = parse_protobuf_fields(raw_entry)
        t_vals = entry_fields.get(1)
        f_vals = entry_fields.get(2)
        if (
            t_vals is not None
            and isinstance(t_vals[0], int)
            and f_vals is not None
            and isinstance(f_vals[0], int)
        ):
            entries.append((t_vals[0], f_vals[0]))

    return ParsedRiseConfigPacket(
        start=start,
        first_packet=first_packet,
        last_packet=last_packet,
        entries=tuple(entries),
    )


def decode_rise_alarms(
    raw_entries: Sequence[tuple[int, int]],
) -> list[RiseAlarm]:
    """Convert raw ``(time_utc, rise_flags)`` entries into :class:`RiseAlarm` items.

    Mirrors ``RiseMessageUtil.parseRiseSettings`` in the Casper Glow app:
    entries with a non-zero ``sync_id`` are grouped by ``sync_id``, combining
    their weekdays and setting ``enabled = True`` if any slot in the group is
    enabled. Entries with ``sync_id == 0`` remain standalone alarms.
    """
    parsed_single: list[RiseAlarm] = []
    for time_utc, rise_flags in raw_entries:
        enabled, repeats_weekly, linger_packed, sync_id = decode_rise_flags(rise_flags)
        linger_minutes = (time_utc % 60) * 5 if linger_packed else 0
        dt_utc = datetime.fromtimestamp(time_utc, tz=UTC)
        weekdays: tuple[Weekday, ...] = (
            (Weekday(dt_utc.weekday()),) if repeats_weekly else ()
        )
        parsed_single.append(
            RiseAlarm(
                hour=dt_utc.hour,
                minute=dt_utc.minute,
                linger_minutes=linger_minutes,
                enabled=enabled,
                weekdays=weekdays,
                sync_id=sync_id,
            )
        )

    standalone: list[RiseAlarm] = []
    grouped_by_id: dict[int, list[RiseAlarm]] = {}
    for alarm in parsed_single:
        if alarm.sync_id != 0:
            grouped_by_id.setdefault(alarm.sync_id, []).append(alarm)
        else:
            standalone.append(alarm)

    for group in grouped_by_id.values():
        first = group[0]
        combined_days = tuple(sorted({day for item in group for day in item.weekdays}))
        any_enabled = any(item.enabled for item in group)
        standalone.append(
            RiseAlarm(
                hour=first.hour,
                minute=first.minute,
                linger_minutes=first.linger_minutes,
                enabled=any_enabled,
                weekdays=combined_days,
                sync_id=first.sync_id,
            )
        )

    return standalone
