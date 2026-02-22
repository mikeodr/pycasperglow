"""Pure protocol logic for Casper Glow BLE communication.

Handles protobuf varint encoding/decoding, session token extraction,
notification field parsing, and action packet construction. No I/O.
"""

from __future__ import annotations

from .const import READY_MARKER

# Protobuf field number for the state response sub-message
STATE_RESPONSE_FIELD = 19


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


def payload_contains_ready_marker(payload: bytes) -> bool:
    """Check if a notification payload contains the ready marker."""
    return READY_MARKER in payload


def extract_token_from_notify(payload: bytes) -> int | None:
    """Extract the session token from a notification payload.

    The notification payload is a protobuf-like structure. The session token
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
        elif wire_type == 2:  # length-delimited
            try:
                length, pos = parse_varint(payload, pos)
            except ValueError:
                return None
            pos += length
        else:
            # Unknown wire type — can't continue safely
            return None
    return None


def parse_protobuf_fields(data: bytes) -> dict[int, list[int | bytes]]:
    """Parse a protobuf-like payload into a dict of field_number -> values.

    Supports wire type 0 (varint) and wire type 2 (length-delimited).
    Each field number maps to a list of values since protobuf fields can repeat.
    Varint fields produce ``int`` values; length-delimited fields produce ``bytes``.

    Returns an empty dict if the payload is malformed.
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
        elif wire_type == 2:  # length-delimited
            try:
                length, pos = parse_varint(data, pos)
            except ValueError:
                return fields
            if pos + length > len(data):
                return fields
            fields.setdefault(field_number, []).append(data[pos : pos + length])
            pos += length
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

    Packet structure (protobuf-like):
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


# Protobuf tag for field 18 (wire type 2) — two-byte varint: (18 << 3) | 2 = 146
_FIELD_18_TAG = encode_varint((18 << 3) | 2)


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
