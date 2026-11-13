"""Tests for protocol encoding/decoding functions."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pycasperglow.const import ACTION_BODY_OFF, ACTION_BODY_ON
from pycasperglow.protocol import (
    NO_DST_TRANSITION,
    RiseAlarm,
    Weekday,
    build_action_packet,
    build_brightness_body,
    build_delete_legacy_rise_body,
    build_rise_config_bodies,
    build_set_clock_body,
    calculate_rise_time_utc,
    decode_rise_alarms,
    decode_rise_flags,
    decode_zigzag32,
    encode_fixed32,
    encode_rise_flags,
    encode_varint,
    encode_zigzag32,
    extract_token_from_notify,
    parse_protobuf_fields,
    parse_rise_config_notification,
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
        assert isinstance(result[7][0], bytes)
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
            (
                "08f091b043100118baf8ed800622179a01140803100018002000280030003a04080010054064",
                {
                    1: [3],
                    5: [0],
                    7: [b"\x08\x00\x10\x05"],
                    8: [100],
                },  # off, 75% battery, not charging
            ),
            (
                "08c392b0431001189ef1c3e80222179a01140803100018002000280030003a04080310064064",
                {
                    1: [3],
                    5: [0],  # sf5 always 0, even when charging
                    # inner f1=3 (charging), inner f2=6 (100%)
                    7: [b"\x08\x03\x10\x06"],
                    8: [100],
                },  # off, 100% battery, charging (Jar_086c0943)
            ),
        ],
        ids=[
            "off",
            "on",
            "paused",
            "off-low-battery",
            "off-75pct-not-charging",
            "off-100pct-charging",
        ],
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
        assert isinstance(result[7][0], bytes)
        inner = parse_protobuf_fields(result[7][0])
        assert inner[2] == [3]  # low battery

    @pytest.mark.parametrize(
        ("sf7_inner_f1", "expected_sf7"),
        [
            (0, b"\x08\x00\x10\x06"),  # not charging
            (3, b"\x08\x03\x10\x06"),  # charging
        ],
        ids=["not-charging", "charging"],
    )
    def test_charging_indicator_in_sf7_inner_f1(
        self, sf7_inner_f1: int, expected_sf7: bytes
    ) -> None:
        """SF7 inner field 1 is the charging indicator.

        0=not charging, 3=charging observed.

        SF5 (tag 0x28) is always 0 in all real-device captures and is NOT the charging
        indicator.
        """
        battery_inner = b"\x08" + encode_varint(sf7_inner_f1) + b"\x10\x06"
        battery_sf7 = b"\x3a" + encode_varint(len(battery_inner)) + battery_inner
        state_body = b"\x08\x03" + battery_sf7  # sf1=3 (off) + sf7
        notification = self._make_state_notification(state_body)

        result = parse_state_response(notification)
        assert result is not None
        assert result[7] == [expected_sf7]


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
        outer = parse_protobuf_fields(body)[18][0]
        assert isinstance(outer, bytes)
        inner_fields = parse_protobuf_fields(outer)
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


class TestFixedAndZigZag:
    """Tests for fixed32, fixed64, and sint32 ZigZag wire formats."""

    @pytest.mark.parametrize(
        ("signed_val", "expected_zigzag"),
        [
            (0, 0),
            (-1, 1),
            (1, 2),
            (-2, 3),
            (-28800, 57599),
            (3600, 7200),
            (2147483647, 0xFFFFFFFE),
            (-2147483648, 0xFFFFFFFF),
        ],
    )
    def test_zigzag_roundtrip(self, signed_val: int, expected_zigzag: int) -> None:
        encoded = encode_zigzag32(signed_val)
        assert encoded == expected_zigzag
        assert decode_zigzag32(encoded) == signed_val

    def test_zigzag_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="signed 32-bit"):
            encode_zigzag32(1 << 31)
        with pytest.raises(ValueError, match="unsigned 32-bit"):
            decode_zigzag32(-1)

    def test_encode_fixed32(self) -> None:
        assert encode_fixed32(0x12345678) == b"\x78\x56\x34\x12"
        with pytest.raises(ValueError, match="fixed32"):
            encode_fixed32(-1)

    def test_parse_protobuf_fields_fixed32_and_fixed64(self) -> None:
        # field 1 fixed32 (0x0d), field 2 fixed64 (0x11), field 3 varint (0x18)
        payload = (
            b"\x0d"
            + encode_fixed32(1_700_000_002)
            + b"\x11"
            + (0x0102030405060708).to_bytes(8, "little")
            + b"\x18\x07"
        )
        fields = parse_protobuf_fields(payload)
        assert fields[1] == [1_700_000_002]
        assert fields[2] == [0x0102030405060708]
        assert fields[3] == [7]

    def test_truncated_fixed_fields_and_token_skip(self) -> None:
        # Truncated fixed32
        assert parse_protobuf_fields(b"\x0d\x01\x02") == {}
        # Truncated fixed64
        assert parse_protobuf_fields(b"\x11\x01\x02\x03") == {}
        # Token extraction skips preceding fixed32/fixed64 fields safely
        payload = (
            b"\x15"
            + encode_fixed32(123)
            + b"\x19"
            + (456).to_bytes(8, "little")
            + b"\x08\x2a"
        )
        assert extract_token_from_notify(payload) == 42
        # Truncated length-delimited in extract_token_from_notify returns None
        assert extract_token_from_notify(b"\x22\x0a\x01\x02") is None


class TestRiseAlarmModel:
    """Validation and normalisation tests for RiseAlarm."""

    def test_normalises_weekdays(self) -> None:
        alarm = RiseAlarm(
            hour=7,
            minute=30,
            weekdays=(Weekday.FRIDAY, Weekday.MONDAY, Weekday.FRIDAY),
        )
        assert alarm.weekdays == (Weekday.MONDAY, Weekday.FRIDAY)
        assert alarm.repeats_weekly is True

    def test_one_off_alarm(self) -> None:
        alarm = RiseAlarm(hour=6, minute=45)
        assert alarm.weekdays == ()
        assert alarm.repeats_weekly is False

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"hour": 24, "minute": 0},
            {"hour": -1, "minute": 0},
            {"hour": 7, "minute": 60},
            {"hour": 7, "minute": 0, "linger_minutes": 7},
            {"hour": 7, "minute": 0, "linger_minutes": 300},
            {"hour": 7, "minute": 0, "sync_id": 70_000},
        ],
    )
    def test_invalid_parameters_raise(self, kwargs: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            RiseAlarm(**kwargs)


class TestBuildSetClockBody:
    """Clock sync (nova_set_clock, field 21) encoding tests."""

    def test_fixed_offset_timezone(self) -> None:
        tz_minus_8 = timezone(timedelta(hours=-8))
        now = datetime(2026, 1, 15, 10, 0, 0, tzinfo=tz_minus_8)
        body = build_set_clock_body(now)

        outer = parse_protobuf_fields(body)
        assert 21 in outer
        inner_bytes = outer[21][0]
        assert isinstance(inner_bytes, bytes)
        inner = parse_protobuf_fields(inner_bytes)

        assert inner[1] == [int(now.timestamp())]
        assert decode_zigzag32(int(inner[2][0])) == -28800
        assert inner[3] == [NO_DST_TRANSITION]
        assert decode_zigzag32(int(inner[4][0])) == 0

    def test_zoneinfo_dst_spring_forward_and_fall_back(self) -> None:
        la = ZoneInfo("America/Los_Angeles")
        # Before 2026 US spring-forward (2026-03-08 02:00 PST -> 03:00 PDT = 10:00 UTC)
        winter_now = datetime(2026, 2, 15, 12, 0, 0, tzinfo=la)
        winter_body = build_set_clock_body(winter_now)
        winter_raw = parse_protobuf_fields(winter_body)[21][0]
        assert isinstance(winter_raw, bytes)
        winter_inner = parse_protobuf_fields(winter_raw)
        expected_spring_utc = int(
            datetime(2026, 3, 8, 10, 0, 0, tzinfo=UTC).timestamp()
        )
        assert decode_zigzag32(int(winter_inner[2][0])) == -28800
        assert winter_inner[3] == [expected_spring_utc]
        assert decode_zigzag32(int(winter_inner[4][0])) == -25200

        # Before 2026 US fall-back (2026-11-01 02:00 PDT -> 01:00 PST = 09:00 UTC)
        autumn_now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=la)
        autumn_body = build_set_clock_body(autumn_now)
        autumn_raw = parse_protobuf_fields(autumn_body)[21][0]
        assert isinstance(autumn_raw, bytes)
        autumn_inner = parse_protobuf_fields(autumn_raw)
        expected_fall_utc = int(datetime(2026, 11, 1, 9, 0, 0, tzinfo=UTC).timestamp())
        assert decode_zigzag32(int(autumn_inner[2][0])) == -25200
        assert autumn_inner[3] == [expected_fall_utc]
        assert decode_zigzag32(int(autumn_inner[4][0])) == -28800


class TestRiseProtocol:
    """Multi-Rise scheduling, chunking, and notification parsing tests."""

    def test_rise_flags_roundtrip(self) -> None:
        flags = encode_rise_flags(enabled=True, repeats_weekly=True, sync_id=0x1234)
        assert flags == 0x12340007
        assert decode_rise_flags(flags) == (True, True, True, 0x1234)

        disabled_once = encode_rise_flags(
            enabled=False, repeats_weekly=False, sync_id=5
        )
        assert decode_rise_flags(disabled_once) == (False, False, True, 5)

    def test_calculate_rise_time_utc_one_off_rollover(self) -> None:
        tz = timezone(timedelta(hours=-8))
        # Local time: Friday 2026-11-13 10:00 PST
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=tz)

        # Future time today (11:30, linger=15 -> +3s) stays on 2026-11-13
        t_today = calculate_rise_time_utc(11, 30, 15, now=now)
        expected_today = (
            int(datetime(2026, 11, 13, 11, 30, 0, tzinfo=UTC).timestamp()) + 3
        )
        assert t_today == expected_today

        # Past time today (07:30, linger=10 -> +2s) rolls over to tomorrow 2026-11-14
        t_tomorrow = calculate_rise_time_utc(7, 30, 10, now=now)
        expected_tomorrow = (
            int(datetime(2026, 11, 14, 7, 30, 0, tzinfo=UTC).timestamp()) + 2
        )
        assert t_tomorrow == expected_tomorrow

    def test_calculate_rise_time_utc_repeating_weekday_rollover(self) -> None:
        tz = timezone(timedelta(hours=-5))
        # Wednesday 2026-11-11 09:00 local
        now = datetime(2026, 11, 11, 9, 0, 0, tzinfo=tz)

        # Friday (same week: 2026-11-13)
        t_fri = calculate_rise_time_utc(7, 0, 5, now=now, weekday=Weekday.FRIDAY)
        assert t_fri == int(datetime(2026, 11, 13, 7, 0, 0, tzinfo=UTC).timestamp()) + 1

        # Monday (already passed this week -> next Monday 2026-11-16)
        t_mon = calculate_rise_time_utc(7, 0, 5, now=now, weekday=Weekday.MONDAY)
        assert t_mon == int(datetime(2026, 11, 16, 7, 0, 0, tzinfo=UTC).timestamp()) + 1

        # Wednesday 08:00 (same day, already passed -> next Wednesday 2026-11-18)
        t_wed = calculate_rise_time_utc(8, 0, 30, now=now, weekday=Weekday.WEDNESDAY)
        assert t_wed == int(datetime(2026, 11, 18, 8, 0, 0, tzinfo=UTC).timestamp()) + 6

    def test_empty_rise_config_clears_alarms(self) -> None:
        bodies = build_rise_config_bodies([])
        assert bodies == [bytes.fromhex("c2010408001003")]

    def test_multi_packet_chunking_and_roundtrip(self) -> None:
        now = datetime(2026, 11, 13, 10, 0, 0, tzinfo=UTC)
        alarm1 = RiseAlarm(
            hour=7,
            minute=15,
            linger_minutes=10,
            enabled=True,
            weekdays=tuple(Weekday),  # 7 slots
        )
        alarm2 = RiseAlarm(
            hour=8,
            minute=45,
            linger_minutes=30,
            enabled=False,
            weekdays=tuple(Weekday),  # 7 slots -> 14 total slots -> 2 packets (8 + 6)
        )

        bodies = build_rise_config_bodies([alarm1, alarm2], now=now)
        assert len(bodies) == 2

        # Every full BLE packet must fit comfortably inside the 161-byte MTU
        packets = [build_action_packet(42, b) for b in bodies]
        assert all(len(p) <= 161 for p in packets)

        parsed0 = parse_rise_config_notification(packets[0])
        parsed1 = parse_rise_config_notification(packets[1])
        assert parsed0 is not None
        assert parsed1 is not None

        assert parsed0.start == 0
        assert parsed0.first_packet is True
        assert parsed0.last_packet is False
        assert len(parsed0.entries) == 8

        assert parsed1.start == 8
        assert parsed1.first_packet is False
        assert parsed1.last_packet is True
        assert len(parsed1.entries) == 6

        decoded = decode_rise_alarms([*parsed0.entries, *parsed1.entries])
        assert decoded == [
            RiseAlarm(
                hour=7,
                minute=15,
                linger_minutes=10,
                enabled=True,
                weekdays=tuple(Weekday),
                sync_id=1,
            ),
            RiseAlarm(
                hour=8,
                minute=45,
                linger_minutes=30,
                enabled=False,
                weekdays=tuple(Weekday),
                sync_id=2,
            ),
        ]

    def test_exceeding_max_slots_raises(self) -> None:
        # 3 daily alarms = 21 slots > 16 limit
        alarms = [
            RiseAlarm(hour=6, minute=0, weekdays=tuple(Weekday)),
            RiseAlarm(hour=7, minute=0, weekdays=tuple(Weekday)),
            RiseAlarm(hour=8, minute=0, weekdays=tuple(Weekday)),
        ]
        with pytest.raises(ValueError, match="exceeds device maximum"):
            build_rise_config_bodies(alarms)

    def test_unsupported_ui_linger_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid linger_minutes"):
            build_rise_config_bodies([RiseAlarm(hour=7, minute=0, linger_minutes=20)])

    def test_delete_legacy_rise_body(self) -> None:
        assert build_delete_legacy_rise_body() == bytes.fromhex("a2010620ffffffff0f")

    def test_parse_rise_config_notification_non_matching(self) -> None:
        assert parse_rise_config_notification(b"\x08\x2a") is None
        assert parse_rise_config_notification(b"\x08\x2a\x22\x02\x08\x01") is None
