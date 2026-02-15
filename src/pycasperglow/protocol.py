"""Pure protocol logic for Casper Glow BLE communication.

Handles protobuf varint encoding/decoding, session token extraction,
and action packet construction. No I/O.
"""

from __future__ import annotations

from .const import READY_MARKER


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


def build_action_packet(token: int, action_body: bytes) -> bytes:
    """Build a full command packet from a session token and action body.

    Packet structure: header (field 1 varint = token) + action body.
    """
    # Field 1, wire type 0 (varint) -> tag byte = 0x08
    return b"\x08" + encode_varint(token) + action_body
