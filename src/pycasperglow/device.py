"""Async BLE client for Casper Glow lights."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    HANDSHAKE_TIMEOUT,
    READ_CHAR_UUID,
    RECONNECT_PACKET,
    WRITE_CHAR_UUID,
)
from .exceptions import CommandError, HandshakeTimeoutError
from .protocol import (
    build_action_packet,
    extract_token_from_notify,
    payload_contains_ready_marker,
)

_LOGGER = logging.getLogger(__name__)


class CasperGlow:
    """Async client for a Casper Glow light."""

    def __init__(
        self,
        ble_device: BLEDevice,
        client: BleakClient | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._external_client = client

    @property
    def name(self) -> str | None:
        """Return the device name."""
        return self._ble_device.name

    @property
    def address(self) -> str:
        """Return the device address."""
        return self._ble_device.address

    async def turn_on(self) -> None:
        """Turn the light on."""
        from .const import ACTION_BODY_ON

        await self._execute_command(ACTION_BODY_ON)

    async def turn_off(self) -> None:
        """Turn the light off."""
        from .const import ACTION_BODY_OFF

        await self._execute_command(ACTION_BODY_OFF)

    async def _execute_command(self, action_body: bytes) -> None:
        """Connect, handshake, send command, disconnect."""
        ready_event = asyncio.Event()
        token: int | None = None

        def _on_notify(_sender: Any, data: bytearray) -> None:
            nonlocal token
            _LOGGER.debug("Notification: %s", data.hex())
            if payload_contains_ready_marker(bytes(data)):
                extracted = extract_token_from_notify(bytes(data))
                if extracted is not None:
                    token = extracted
                    ready_event.set()

        client = self._external_client or await establish_connection(
            BleakClient, self._ble_device, self._ble_device.address
        )
        try:
            if not client.is_connected:
                await client.connect()

            await client.start_notify(READ_CHAR_UUID, _on_notify)
            await client.write_gatt_char(WRITE_CHAR_UUID, RECONNECT_PACKET)

            try:
                await asyncio.wait_for(ready_event.wait(), HANDSHAKE_TIMEOUT)
            except TimeoutError as err:
                raise HandshakeTimeoutError(
                    f"Device did not become ready within {HANDSHAKE_TIMEOUT}s"
                ) from err

            if token is None:
                raise CommandError("Ready marker seen but no token extracted")

            packet = build_action_packet(token, action_body)
            await client.write_gatt_char(WRITE_CHAR_UUID, packet)
            _LOGGER.debug("Sent action packet: %s", packet.hex())
        finally:
            if self._external_client is None:
                await client.disconnect()
