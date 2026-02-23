"""Tests for the CasperGlow async client."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycasperglow.const import (
    ACTION_BODY_OFF,
    ACTION_BODY_ON,
    ACTION_BODY_PAUSE,
    ACTION_BODY_RESUME,
    DIMMING_TIME_MINUTES,
    QUERY_STATE_BODY,
    READ_CHAR_UUID,
    RECONNECT_PACKET,
    WRITE_CHAR_UUID,
)
from pycasperglow.device import BatteryLevel, CasperGlow
from pycasperglow.exceptions import HandshakeTimeoutError
from pycasperglow.protocol import (
    build_action_packet,
    build_brightness_body,
    encode_varint,
)


def _make_ble_device(name: str = "JarGlow", address: str = "AA:BB:CC:DD:EE:FF") -> Any:
    device = MagicMock()
    device.name = name
    device.address = address
    return device


def _make_ready_notification(token: int = 42) -> bytearray:
    """Build a notification payload with field 1 = token and embedded ready marker."""
    from pycasperglow.protocol import encode_varint

    # field 1 varint (token), then ready marker bytes
    return bytearray(b"\x08" + encode_varint(token) + bytes.fromhex("72020800"))


def _make_mock_client(ready_token: int = 42) -> AsyncMock:
    """Create a mock BleakClient that simulates the handshake."""
    client = AsyncMock()
    client.is_connected = True

    async def _start_notify(char_uuid: str, callback: Any) -> None:
        # Store callback so write_gatt_char can trigger it
        client._notify_callback = callback

    async def _write_gatt_char(char_uuid: str, data: bytes) -> None:
        if data == RECONNECT_PACKET:
            # Simulate device sending ready notification
            notification = _make_ready_notification(ready_token)
            client._notify_callback(None, notification)

    client.start_notify = AsyncMock(side_effect=_start_notify)
    client.write_gatt_char = AsyncMock(side_effect=_write_gatt_char)
    return client


def _make_state_notification(
    *,
    is_on: bool = False,
    is_paused: bool = False,
    token: int = 42,
    dimming_ms: int = 0,
    remaining_ms: int = 0,
    battery: int = 6,
) -> bytes:
    """Build a notification with field 1 (token) and field 4 containing field 19.

    The field 19 body mirrors the real device structure:
    * sub-field 1: power/mode indicator (1 = on, 3 = off)
    * sub-field 2: remaining dimming time in milliseconds (counts down to 0 when off)
    * sub-field 3: configured total dimming duration in milliseconds
    * sub-field 4: paused indicator (0 = not paused, 1 = paused)
    * sub-field 7: nested message with inner field 2 = battery level enum
        (6 = full, 3 = low; others unknown)
    """
    from pycasperglow.protocol import STATE_RESPONSE_FIELD

    power_indicator = 1 if is_on else 3
    paused_indicator = 1 if is_paused else 0
    # Sub-field 7: nested message with inner field 2 = battery enum
    battery_inner = b"\x10" + encode_varint(battery)
    battery_sf7 = b"\x3a" + encode_varint(len(battery_inner)) + battery_inner
    state_inner = (
        b"\x08"
        + encode_varint(power_indicator)  # sub-field 1
        + b"\x10"
        + encode_varint(remaining_ms)  # sub-field 2: remaining
        + b"\x18"
        + encode_varint(dimming_ms)  # sub-field 3: configured total
        + b"\x20"
        + encode_varint(paused_indicator)  # sub-field 4
        + battery_sf7  # sub-field 7
    )
    # field 19, wire type 2
    tag_19 = (STATE_RESPONSE_FIELD << 3) | 2
    field4_body = encode_varint(tag_19) + encode_varint(len(state_inner)) + state_inner
    # Wrap in top-level notification: field 1 (token), field 4 (body)
    return (
        b"\x08"
        + encode_varint(token)
        + b"\x22"
        + encode_varint(len(field4_body))
        + field4_body
    )


def _make_mock_client_with_state(
    ready_token: int = 42,
    *,
    is_on: bool = True,
    is_paused: bool = False,
    dimming_ms: int = 900_000,
    battery: int = 6,
) -> AsyncMock:
    """Create a mock BleakClient that simulates handshake + state response."""
    client = AsyncMock()
    client.is_connected = True

    async def _start_notify(char_uuid: str, callback: Any) -> None:
        client._notify_callback = callback

    async def _write_gatt_char(char_uuid: str, data: bytes) -> None:
        if data == RECONNECT_PACKET:
            notification = _make_ready_notification(ready_token)
            client._notify_callback(None, notification)
        else:
            # For any other write (e.g. state query), send a state notification
            state_notif = bytearray(
                _make_state_notification(
                    is_on=is_on,
                    is_paused=is_paused,
                    token=ready_token,
                    dimming_ms=dimming_ms,
                    remaining_ms=dimming_ms,
                    battery=battery,
                )
            )
            client._notify_callback(None, state_notif)

    client.start_notify = AsyncMock(side_effect=_start_notify)
    client.write_gatt_char = AsyncMock(side_effect=_write_gatt_char)
    return client


@pytest.fixture
def device() -> Any:
    return _make_ble_device()


@pytest.fixture
def mock_client() -> AsyncMock:
    return _make_mock_client()


@pytest.fixture
def glow(device: Any, mock_client: AsyncMock) -> CasperGlow:
    return CasperGlow(device, client=mock_client)


class TestCasperGlow:
    """CasperGlow client tests."""

    @pytest.mark.parametrize(
        ("method_name", "action_body", "state_attr", "state_val"),
        [
            ("turn_on", ACTION_BODY_ON, None, None),
            ("turn_off", ACTION_BODY_OFF, None, None),
            ("pause", ACTION_BODY_PAUSE, "is_paused", True),
            ("resume", ACTION_BODY_RESUME, "is_paused", False),
        ],
        ids=["turn_on", "turn_off", "pause", "resume"],
    )
    async def test_command_writes_correct_packet(
        self,
        method_name: str,
        action_body: bytes,
        state_attr: str | None,
        state_val: bool | None,
    ) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)

        await getattr(glow, method_name)()

        calls = client.write_gatt_char.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (WRITE_CHAR_UUID, RECONNECT_PACKET)
        assert calls[1].args == (WRITE_CHAR_UUID, build_action_packet(42, action_body))
        if state_attr is not None:
            assert getattr(glow.state, state_attr) is state_val

    async def test_subscribes_to_notifications(
        self, glow: CasperGlow, mock_client: AsyncMock
    ) -> None:
        await glow.turn_on()

        mock_client.start_notify.assert_called_once()
        assert mock_client.start_notify.call_args.args[0] == READ_CHAR_UUID

    async def test_handshake_timeout(self) -> None:
        device = _make_ble_device()
        client = AsyncMock()
        client.is_connected = True
        client.start_notify = AsyncMock()
        client.write_gatt_char = AsyncMock()  # Never triggers ready

        glow = CasperGlow(device, client=client)

        with (
            patch("pycasperglow.device.HANDSHAKE_TIMEOUT", 0.1),
            pytest.raises(HandshakeTimeoutError),
        ):
            await glow.turn_on()

    async def test_disconnect_on_success(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client()
        glow = CasperGlow(device)

        with patch("pycasperglow.device.establish_connection", return_value=client):
            await glow.turn_on()

        client.disconnect.assert_called_once()

    async def test_disconnect_on_error(self) -> None:
        device = _make_ble_device()
        client = AsyncMock()
        client.is_connected = True
        client.start_notify = AsyncMock()
        client.write_gatt_char = AsyncMock()

        glow = CasperGlow(device)

        with (
            patch("pycasperglow.device.establish_connection", return_value=client),
            patch("pycasperglow.device.HANDSHAKE_TIMEOUT", 0.1),
            pytest.raises(HandshakeTimeoutError),
        ):
            await glow.turn_on()

        client.disconnect.assert_called_once()

    async def test_external_client_not_disconnected(
        self, glow: CasperGlow, mock_client: AsyncMock
    ) -> None:
        await glow.turn_on()

        mock_client.disconnect.assert_not_called()

    async def test_properties(self) -> None:
        device = _make_ble_device(name="JarTest", address="11:22:33:44:55:66")
        glow = CasperGlow(device)
        assert glow.name == "JarTest"
        assert glow.address == "11:22:33:44:55:66"

    @pytest.mark.parametrize(
        ("method_name", "state_attr", "state_val"),
        [
            ("pause", "is_paused", True),
            ("resume", "is_paused", False),
        ],
    )
    async def test_pause_resume_fires_callback(
        self,
        glow: CasperGlow,
        method_name: str,
        state_attr: str,
        state_val: bool,
    ) -> None:
        states: list[Any] = []
        glow.register_callback(lambda s: states.append(s))

        await getattr(glow, method_name)()

        assert len(states) == 1
        assert getattr(states[0], state_attr) is state_val

    async def test_set_dimming_time_sends_correct_packet(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)
        glow._state.brightness_level = 80  # brightness must be known

        await glow.set_dimming_time(30)

        calls = client.write_gatt_char.call_args_list
        assert len(calls) == 2
        # Should send brightness body with the known brightness (80) and 30 min
        expected_body = build_brightness_body(80, 30 * 60_000)
        expected_packet = build_action_packet(42, expected_body)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_packet)
        assert glow.state.configured_dimming_time_minutes == 30

    @pytest.mark.parametrize(
        ("method_name", "arg", "match"),
        [
            ("set_dimming_time", 20, "Invalid dimming time"),
            ("set_brightness", 50, "Invalid brightness"),
        ],
    )
    async def test_invalid_arg_raises(
        self,
        glow: CasperGlow,
        method_name: str,
        arg: int,
        match: str,
    ) -> None:
        with pytest.raises(ValueError, match=match):
            await getattr(glow, method_name)(arg)

    async def test_set_dimming_time_fires_callback(self, glow: CasperGlow) -> None:
        glow._state.brightness_level = 70  # brightness must be known
        states: list[Any] = []
        glow.register_callback(lambda s: states.append(s))

        await glow.set_dimming_time(45)

        assert len(states) == 1
        assert states[0].configured_dimming_time_minutes == 45

    async def test_set_dimming_time_unknown_brightness_raises(
        self, glow: CasperGlow
    ) -> None:
        # brightness_level is None by default — no set_brightness() call yet
        with pytest.raises(ValueError, match="Brightness level is unknown"):
            await glow.set_dimming_time(30)

    async def test_set_dimming_time_uses_known_brightness(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)
        glow._state.brightness_level = 80  # previously known

        await glow.set_dimming_time(15)

        calls = client.write_gatt_char.call_args_list
        expected_body = build_brightness_body(80, 15 * 60_000)
        expected_packet = build_action_packet(42, expected_body)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_packet)

    async def test_set_brightness_sends_correct_packet(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)

        await glow.set_brightness(80)

        calls = client.write_gatt_char.call_args_list
        assert len(calls) == 2
        # Should send brightness body with 80% and default dimming time (15 min)
        expected_body = build_brightness_body(80, 15 * 60_000)
        expected_packet = build_action_packet(42, expected_body)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_packet)
        assert glow.state.brightness_level == 80

    async def test_set_brightness_fires_callback(self, glow: CasperGlow) -> None:
        states: list[Any] = []
        glow.register_callback(lambda s: states.append(s))

        await glow.set_brightness(70)

        assert len(states) == 1
        assert states[0].brightness_level == 70

    async def test_set_brightness_ignores_remaining_dimming_time(self) -> None:
        # dimming_time_minutes is a countdown from the device and not a valid
        # configured value; set_brightness() must not use it as a fallback.
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)
        glow._state.dimming_time_minutes = 60  # remaining time — must be ignored

        await glow.set_brightness(90)

        calls = client.write_gatt_char.call_args_list
        expected_body = build_brightness_body(90, DIMMING_TIME_MINUTES[0] * 60_000)
        expected_packet = build_action_packet(42, expected_body)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_packet)

    async def test_query_state_sends_query_packet(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=True)
        glow = CasperGlow(device, client=client)

        state = await glow.query_state()

        calls = client.write_gatt_char.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (WRITE_CHAR_UUID, RECONNECT_PACKET)
        expected_query = build_action_packet(42, QUERY_STATE_BODY)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_query)
        assert state.is_on is True

    async def test_query_state_off(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=False)
        glow = CasperGlow(device, client=client)

        state = await glow.query_state()
        assert state.is_on is False

    async def test_query_state_battery_level(self) -> None:
        """battery_level is BatteryLevel.PCT_25 when the device reports raw value 3."""
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=False, battery=3)
        glow = CasperGlow(device, client=client)

        state = await glow.query_state()
        assert state.battery_level is BatteryLevel.PCT_25
        assert state.battery_level.percentage == 25  # type: ignore[union-attr]

    async def test_query_state_battery_level_full(self) -> None:
        """battery_level is BatteryLevel.PCT_100 when the device reports raw value 6."""
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=True, battery=6)
        glow = CasperGlow(device, client=client)

        state = await glow.query_state()
        assert state.battery_level is BatteryLevel.PCT_100
        assert state.battery_level.percentage == 100  # type: ignore[union-attr]

    async def test_query_state_brightness(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=True)
        glow = CasperGlow(device, client=client)

        state = await glow.query_state()
        assert state.configured_dimming_time_minutes == 15
        assert state.dimming_time_minutes == 15

    async def test_query_state_fires_callback(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=True)
        glow = CasperGlow(device, client=client)
        states: list[Any] = []
        glow.register_callback(lambda s: states.append(s))

        await glow.query_state()

        assert len(states) == 1
        assert states[0].is_on is True

    async def test_query_state_external_client_not_disconnected(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=True)
        glow = CasperGlow(device, client=client)

        await glow.query_state()
        client.disconnect.assert_not_called()

    async def test_query_state_disconnect_on_success(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client_with_state(ready_token=42, is_on=True)
        glow = CasperGlow(device)

        with patch("pycasperglow.device.establish_connection", return_value=client):
            await glow.query_state()

        client.disconnect.assert_called_once()

    async def test_parse_state_on(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)

        notification = _make_state_notification(
            is_on=True,
            dimming_ms=900_000,
            remaining_ms=900_000,
        )
        result = glow._parse_state_notification(notification)

        assert result is True
        assert glow.state.is_on is True
        assert glow.state.is_paused is False
        assert glow.state.configured_dimming_time_minutes == 15
        assert glow.state.dimming_time_minutes == 15
        assert glow.state.raw_state is not None

    async def test_parse_state_off(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)

        notification = _make_state_notification(is_on=False)
        result = glow._parse_state_notification(notification)

        assert result is True
        assert glow.state.is_on is False
        assert glow.state.is_paused is False
        assert glow.state.dimming_time_minutes == 0

    async def test_parse_state_paused(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)

        notification = _make_state_notification(
            is_on=True,
            is_paused=True,
            dimming_ms=900_000,
            remaining_ms=900_000,
        )
        result = glow._parse_state_notification(notification)

        assert result is True
        assert glow.state.is_on is True
        assert glow.state.is_paused is True
        assert glow.state.dimming_time_minutes == 15

    async def test_parse_state_no_field_19(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)

        # Just a ready marker notification — no field 19
        notification = _make_ready_notification(token=42)
        result = glow._parse_state_notification(bytes(notification))

        assert result is False
        assert glow.state.raw_state is None

    async def test_set_brightness_uses_configured_time(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)
        glow._state.configured_dimming_time_minutes = 60
        glow._state.dimming_time_minutes = 44  # stale remaining — must not be used

        await glow.set_brightness(90)

        calls = client.write_gatt_char.call_args_list
        expected_body = build_brightness_body(90, 60 * 60_000)
        expected_packet = build_action_packet(42, expected_body)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_packet)

    async def test_turn_off_zeros_dimming_time(self, glow: CasperGlow) -> None:
        glow._state.dimming_time_minutes = 30

        await glow.turn_off()

        assert glow.state.dimming_time_minutes == 0

    async def test_parse_state_notification_off_zeros_dimming_time(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)
        # Device is off but reports a non-zero remaining time — must be zeroed.
        notification = _make_state_notification(is_on=False, dimming_ms=900_000)
        glow._parse_state_notification(notification)

        assert glow.state.dimming_time_minutes == 0

    async def test_parse_state_reports_remaining_not_total(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)
        # 10 min remaining in a 15-min sequence
        notification = _make_state_notification(
            is_on=True,
            dimming_ms=900_000,
            remaining_ms=600_000,
        )
        glow._parse_state_notification(notification)

        assert glow.state.configured_dimming_time_minutes == 15
        assert glow.state.dimming_time_minutes == 10  # 600_000 ms // 60_000

    async def test_parse_state_configured_set_from_ble(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)
        notification = _make_state_notification(is_on=True, dimming_ms=1_800_000)
        glow._parse_state_notification(notification)

        assert glow.state.configured_dimming_time_minutes == 30

    async def test_parse_state_off_does_not_corrupt_configured_time(self) -> None:
        device = _make_ble_device()
        glow = CasperGlow(device)
        # Establish a known configured time from a previous on-state poll.
        glow._parse_state_notification(
            _make_state_notification(is_on=True, dimming_ms=900_000)
        )
        assert glow.state.configured_dimming_time_minutes == 15

        # Device turns off: sf3 = 0 — configured setting must not be overwritten.
        glow._parse_state_notification(_make_state_notification(is_on=False))
        assert glow.state.configured_dimming_time_minutes == 15
        assert glow.state.dimming_time_minutes == 0
