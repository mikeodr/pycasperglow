"""Tests for protocol encoding/decoding functions."""

import pytest

from pycasperglow.protocol import (
    build_action_packet,
    encode_varint,
    extract_token_from_notify,
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

    def test_exact_match(self) -> None:
        assert payload_contains_ready_marker(bytes.fromhex("72020800"))

    def test_embedded(self) -> None:
        payload = bytes.fromhex("0801") + bytes.fromhex("72020800") + b"\x00"
        assert payload_contains_ready_marker(payload)

    def test_absent(self) -> None:
        assert not payload_contains_ready_marker(b"\x08\x01\x10\x02")

    def test_empty(self) -> None:
        assert not payload_contains_ready_marker(b"")


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

    def test_build_on(self) -> None:
        from pycasperglow.const import ACTION_BODY_ON

        packet = build_action_packet(42, ACTION_BODY_ON)
        # tag 0x08 + varint(42)=0x2a + ON body
        assert packet == b"\x08\x2a" + ACTION_BODY_ON

    def test_build_off(self) -> None:
        from pycasperglow.const import ACTION_BODY_OFF

        packet = build_action_packet(42, ACTION_BODY_OFF)
        assert packet == b"\x08\x2a" + ACTION_BODY_OFF

    def test_large_token(self) -> None:
        packet = build_action_packet(300, b"\x1a\x02\x08\x02")
        # tag 0x08 + varint(300)=\xac\x02
        assert packet[:3] == b"\x08\xac\x02"
