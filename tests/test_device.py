"""Tests for the CasperGlow async client."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycasperglow.const import (
    ACTION_BODY_OFF,
    ACTION_BODY_ON,
    READ_CHAR_UUID,
    RECONNECT_PACKET,
    WRITE_CHAR_UUID,
)
from pycasperglow.device import CasperGlow
from pycasperglow.exceptions import HandshakeTimeoutError
from pycasperglow.protocol import build_action_packet


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


class TestCasperGlow:
    """CasperGlow client tests."""

    async def test_turn_on_writes_correct_packets(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)

        await glow.turn_on()

        calls = client.write_gatt_char.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (WRITE_CHAR_UUID, RECONNECT_PACKET)
        expected_on = build_action_packet(42, ACTION_BODY_ON)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_on)

    async def test_turn_off_writes_correct_packets(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client(ready_token=42)
        glow = CasperGlow(device, client=client)

        await glow.turn_off()

        calls = client.write_gatt_char.call_args_list
        assert len(calls) == 2
        expected_off = build_action_packet(42, ACTION_BODY_OFF)
        assert calls[1].args == (WRITE_CHAR_UUID, expected_off)

    async def test_subscribes_to_notifications(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client()
        glow = CasperGlow(device, client=client)

        await glow.turn_on()

        client.start_notify.assert_called_once()
        assert client.start_notify.call_args.args[0] == READ_CHAR_UUID

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

    async def test_external_client_not_disconnected(self) -> None:
        device = _make_ble_device()
        client = _make_mock_client()
        glow = CasperGlow(device, client=client)

        await glow.turn_on()

        client.disconnect.assert_not_called()

    async def test_properties(self) -> None:
        device = _make_ble_device(name="JarTest", address="11:22:33:44:55:66")
        glow = CasperGlow(device)
        assert glow.name == "JarTest"
        assert glow.address == "11:22:33:44:55:66"
