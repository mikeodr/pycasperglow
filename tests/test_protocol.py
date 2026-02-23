"""Tests for protocol encoding/decoding functions."""

import pytest

from pycasperglow.const import ACTION_BODY_OFF, ACTION_BODY_ON
from pycasperglow.protocol import (
    build_action_packet,
    build_brightness_body,
    encode_varint,
    extract_token_from_notify,
    parse_protobuf_fields,
    parse_state_response,
    parse_varint,
    payload_contains_ready_marker,
)


class TestVarint:
    """Varint encode/decode tests."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, b"\x00"),
            (1, b"\x01"),
            (127, b"\x7f"),
            (128, b"\x80\x01"),
            (300, b"\xac\x02"),
            (16384, b"\x80\x80\x01"),
        ],
    )
    def test_encode(self, value: int, expected: bytes) -> None:
        assert encode_varint(value) == expected

    @pytest.mark.parametrize(
        ("data", "expected_value", "expected_pos"),
        [
            (b"\x00", 0, 1),
            (b"\x01", 1, 1),
            (b"\x7f", 127, 1),
            (b"\x80\x01", 128, 2),
            (b"\xac\x02", 300, 2),
        ],
    )
    def test_parse(self, data: bytes, expected_value: int, expected_pos: int) -> None:
        value, pos = parse_varint(data)
        assert value == expected_value
        assert pos == expected_pos

    def test_roundtrip(self) -> None:
        for v in [0, 1, 127, 128, 255, 300, 100000]:
            encoded = encode_varint(v)
            decoded, _ = parse_varint(encoded)
            assert decoded == v

    def test_parse_with_offset(self) -> None:
        data = b"\xff\x08\x96\x01"  # junk byte, then field tag 0x08, then varint 150
        value, pos = parse_varint(data, start=2)
        assert value == 150
        assert pos == 4

    def test_parse_truncated(self) -> None:
        with pytest.raises(ValueError, match="Truncated"):
            parse_varint(b"\x80")  # continuation bit set but no next byte

    def test_parse_empty(self) -> None:
        with pytest.raises(ValueError, match="Truncated"):
            parse_varint(b"")

    def test_encode_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            encode_varint(-1)


class TestReadyMarker:
    """Ready marker detection tests."""

    @pytest.mark.parametrize(
        "payload",
        [
            bytes.fromhex("72020800"),
            bytes.fromhex("0801") + bytes.fromhex("72020800") + b"\x00",
        ],
        ids=["exact", "embedded"],
    )
    def test_contains_marker(self, payload: bytes) -> None:
        assert payload_contains_ready_marker(payload)

    @pytest.mark.parametrize(
        "payload",
        [b"\x08\x01\x10\x02", b""],
        ids=["absent", "empty"],
    )
    def test_no_marker(self, payload: bytes) -> None:
        assert not payload_contains_ready_marker(payload)


class TestTokenExtraction:
    """Session token extraction tests."""

    def test_simple_payload(self) -> None:
        # Field 1 (tag=0x08) with varint value 42
        payload = b"\x08\x2a"
        assert extract_token_from_notify(payload) == 42

    def test_payload_with_ready_marker(self) -> None:
        # Field 1 = 150, then a length-delimited field (the ready marker area)
        payload = b"\x08\x96\x01" + bytes.fromhex("72020800")
        token = extract_token_from_notify(payload)
        assert token == 150

    def test_no_field_1(self) -> None:
        # Field 2 (tag=0x10) only
        payload = b"\x10\x05"
        assert extract_token_from_notify(payload) is None

    def test_empty_payload(self) -> None:
        assert extract_token_from_notify(b"") is None

    def test_truncated_payload(self) -> None:
        assert extract_token_from_notify(b"\x08\x80") is None


class TestBuildActionPacket:
    """Action packet building tests."""

    @pytest.mark.parametrize(
        "body", [ACTION_BODY_ON, ACTION_BODY_OFF], ids=["on", "off"]
    )
    def test_build_command_packet(self, body: bytes) -> None:
        packet = build_action_packet(42, body)
        # field1=1, field2=token(42), field4=len-delimited(body)
        expected = b"\x08\x01\x10\x2a\x22\x04" + body
        assert packet == expected

    def test_large_token(self) -> None:
        packet = build_action_packet(300, b"\x1a\x02\x08\x02")
        # field1=0x08 0x01, field2=0x10 + varint(300)=\xac\x02
        assert packet[:5] == b"\x08\x01\x10\xac\x02"


class TestParseProtobufFields:
    """Generic protobuf field parser tests."""

    def test_single_varint_field(self) -> None:
        # field 1, varint = 42
        data = b"\x08\x2a"
        fields = parse_protobuf_fields(data)
        assert fields == {1: [42]}

    def test_multiple_varint_fields(self) -> None:
        # field 1 = 1, field 2 = 5
        data = b"\x08\x01\x10\x05"
        fields = parse_protobuf_fields(data)
        assert fields == {1: [1], 2: [5]}

    def test_length_delimited_field(self) -> None:
        # field 4, length-delimited, 4 bytes
        body = bytes.fromhex("1a020802")
        data = b"\x22\x04" + body
        fields = parse_protobuf_fields(data)
        assert fields == {4: [body]}

    def test_mixed_fields(self) -> None:
        # field 1 = token (varint), field 2 = 1 (varint), field 14 = ready marker body
        data = b"\x08\x2a\x10\x01\x72\x02\x08\x00"
        fields = parse_protobuf_fields(data)
        assert fields[1] == [42]
        assert fields[2] == [1]
        assert fields[14] == [b"\x08\x00"]

    def test_repeated_field(self) -> None:
        # field 1 appears twice
        data = b"\x08\x01\x08\x02"
        fields = parse_protobuf_fields(data)
        assert fields == {1: [1, 2]}

    def test_empty_payload(self) -> None:
        assert parse_protobuf_fields(b"") == {}

    def test_truncated_varint(self) -> None:
        # Continuation bit set but no next byte
        fields = parse_protobuf_fields(b"\x08\x80")
        assert fields == {}

    def test_truncated_length_delimited(self) -> None:
        # field 4, claims 10 bytes but only 2 available
        data = b"\x22\x0a\xab\xcd"
        fields = parse_protobuf_fields(data)
        assert fields == {}

    def test_notification_with_ready_marker(self) -> None:
        """Parse a realistic notification with token + ready marker."""
        payload = b"\x08\x96\x01" + bytes.fromhex("72020800")
        fields = parse_protobuf_fields(payload)
        assert fields[1] == [150]
        assert fields[14] == [b"\x08\x00"]


class TestParseStateResponse:
    """State response parsing tests."""

    def _make_state_notification(self, state_body: bytes, token: int = 42) -> bytes:
        """Build a notification with field 1 (token) and field 4 wrapping field 19."""
        from pycasperglow.protocol import STATE_RESPONSE_FIELD

        tag_19 = (STATE_RESPONSE_FIELD << 3) | 2  # wire type 2
        field4_body = (
            encode_varint(tag_19) + encode_varint(len(state_body)) + state_body
        )
        return (
            b"\x08"
            + encode_varint(token)
            + b"\x22"
            + encode_varint(len(field4_body))
            + field4_body
        )

    def test_extracts_field_19(self) -> None:
        # state body: sub-field 1 = 3 (response type), sub-field 3 = 0 (off)
        state_body = b"\x08\x03\x18\x00"
        notification = self._make_state_notification(state_body)

        result = parse_state_response(notification)
        assert result is not None
        assert result[1] == [3]
        assert result[3] == [0]

    def test_returns_none_without_field_19(self) -> None:
        # Just a token field, no field 4
        notification = b"\x08\x2a"
        assert parse_state_response(notification) is None

    def test_off_state(self) -> None:
        # sub-field 3 = 0 → OFF, sub-field 8 = 100 (always 100, not battery)
        state_body = b"\x08\x03\x18\x00\x40\x64"
        notification = self._make_state_notification(state_body)

        result = parse_state_response(notification)
        assert result is not None
        assert result[3] == [0]
        assert result[8] == [100]  # constant — always 100, NOT the battery level

    def test_on_state(self) -> None:
        # sf1 = 1 → ON, sf3 = 900000 (dim time)
        # battery is encoded in sf7 inner-field 2 (discrete enum: 6=full, 3=low)
        battery_inner = b"\x10\x05"  # inner field 2 = 5
        battery_sf7 = b"\x3a" + encode_varint(len(battery_inner)) + battery_inner
        state_body = (
            b"\x08\x01"  # sf1 = 1 (on)
            + b"\x18\xa0\xf76"  # sf3 = 900000
            + battery_sf7  # sf7: battery level enum = 5
        )
        notification = self._make_state_notification(state_body)

        result = parse_state_response(notification)
        assert result is not None
        assert result[1] == [1]
        assert result[3] == [900000]
        assert 7 in result
        inner = parse_protobuf_fields(result[7][0])
        assert inner[2] == [5]  # battery level enum

    def test_empty_payload(self) -> None:
        assert parse_state_response(b"") is None

    def test_field4_without_field19(self) -> None:
        # field 4 body has no field 19 → returns None
        field4_body = b"\x08\x03"  # just sub-field 1
        notification = (
            b"\x08\x2a" + b"\x22" + encode_varint(len(field4_body)) + field4_body
        )
        assert parse_state_response(notification) is None

    @pytest.mark.parametrize(
        ("raw_hex", "expected_fields"),
        [
            (
                "08f091b04310011891a0e78c01"
                "22179a01140803100018002000"
                "280030003a04080010064064",
                {
                    1: [3],
                    3: [0],
                    7: [b"\x08\x00\x10\x06"],
                    8: [100],
                },  # off, full battery
            ),
            (
                "08c392b043100118aac89c15"
                "221b9a0118080110dbc20418"
                "a0f7362000280030003a0408"
                "0310064064",
                {
                    1: [1],
                    3: [900000],
                    4: [0],
                    7: [b"\x08\x03\x10\x06"],
                    8: [100],
                },  # on, full battery
            ),
            (
                "08f091b0431001189fb7e0cd07"
                "221b9a01180801109cba0a18"
                "a0f7362001280030003a0408"
                "0010064064",
                {
                    1: [1],
                    3: [900000],
                    4: [1],
                    7: [b"\x08\x00\x10\x06"],
                    8: [100],
                },  # paused, full battery
            ),
            (
                "08f091b043100118ecc8f89808"
                "22179a01140803100018002000"
                "280030003a04080010034064",
                {
                    1: [3],
                    7: [b"\x08\x00\x10\x03"],
                    8: [100],
                },  # off, low battery (level 3)
            ),
        ],
        ids=["off", "on", "paused", "off-low-battery"],
    )
    def test_real_device_notification(
        self, raw_hex: str, expected_fields: dict[int, list[int | bytes]]
    ) -> None:
        """Parse actual notifications captured from a real Glow device."""
        result = parse_state_response(bytes.fromhex(raw_hex))
        assert result is not None
        for field, value in expected_fields.items():
            assert result[field] == value

    def test_battery_level_in_subfield7(self) -> None:
        """Battery level is inner field 2 of sub-field 7 (discrete enum)."""
        # Build a state body with sf7 inner-field2 = 3 (low battery)
        battery_inner = b"\x10\x03"  # field 2 = 3
        battery_sf7 = b"\x3a" + encode_varint(len(battery_inner)) + battery_inner
        state_body = b"\x08\x03" + battery_sf7  # sf1=3 (off) + sf7
        notification = self._make_state_notification(state_body)

        result = parse_state_response(notification)
        assert result is not None
        assert 7 in result
        inner = parse_protobuf_fields(result[7][0])
        assert inner[2] == [3]  # low battery


class TestBuildBrightnessBody:
    """Brightness body construction tests.

    Verified against iOS app BLE captures.
    """

    @pytest.mark.parametrize(
        ("pct", "expected_hex"),
        [
            (60, "920106103c18a0f736"),
            (70, "920106104618a0f736"),
            (80, "920106105018a0f736"),
            (90, "920106105a18a0f736"),
            (100, "920106106418a0f736"),
        ],
    )
    def test_brightness_15min(self, pct: int, expected_hex: str) -> None:
        """Exact byte output verified against iOS app BLE captures; dimming=15 min."""
        body = build_brightness_body(pct, 900_000)
        assert body == bytes.fromhex(expected_hex)
        inner_fields = parse_protobuf_fields(parse_protobuf_fields(body)[18][0])
        assert inner_fields[2] == [pct]
        assert inner_fields[3] == [900_000]

    def test_dimming_30min(self) -> None:
        body = build_brightness_body(100, 1_800_000)
        # 1800000 ms as varint
        expected_inner = b"\x10\x64" + b"\x18" + encode_varint(1_800_000)
        tag = bytes.fromhex("9201")
        expected = tag + encode_varint(len(expected_inner)) + expected_inner
        assert body == expected

    def test_body_parseable_by_protobuf_parser(self) -> None:
        """The brightness body is well-formed length-delimited protobuf."""
        body = build_brightness_body(90, 900_000)
        fields = parse_protobuf_fields(body)
        assert 18 in fields
        inner = fields[18][0]
        assert isinstance(inner, bytes)
