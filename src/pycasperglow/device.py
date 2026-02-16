"""Async BLE client for Casper Glow lights."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass
class GlowState:
    """Represents the current state of a Casper Glow light."""

    is_on: bool | None = None
    brightness_level: int | None = None
    dimming_time_minutes: int | None = None
    is_paused: bool | None = None


class CasperGlow:
    """Async client for a Casper Glow light."""

    def __init__(
        self,
        ble_device: BLEDevice,
        client: BleakClient | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._external_client = client
        self._state = GlowState()
        self._callbacks: list[Callable[[GlowState], None]] = []

    @property
    def name(self) -> str | None:
        """Return the device name."""
        return self._ble_device.name

    @property
    def address(self) -> str:
        """Return the device address."""
        return self._ble_device.address

    @property
    def state(self) -> GlowState:
        """Return the current device state."""
        return self._state

    @property
    def is_on(self) -> bool | None:
        """Return whether the light is on, or None if unknown."""
        return self._state.is_on

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the BLE device reference."""
        self._ble_device = ble_device

    def register_callback(
        self, callback: Callable[[GlowState], None]
    ) -> Callable[[], None]:
        """Register a callback for state updates. Returns an unregister function."""
        self._callbacks.append(callback)

        def _unregister() -> None:
            self._callbacks.remove(callback)

        return _unregister

    def _fire_callbacks(self) -> None:
        """Notify all registered callbacks of a state change."""
        for callback in self._callbacks:
            callback(self._state)

    def _parse_state_notification(self, data: bytes) -> bool:
        """Parse a BLE notification for state information.

        Returns True if the notification contained state data and the
        state was updated, False otherwise.

        TODO: Decode the actual BLE notification format once the protocol
        for state reporting is captured. The Glow device is known to
        report state via BLE notifications, but the payload format has
        not yet been reverse-engineered.
        """
        _ = data
        return False

    async def handshake(self) -> None:
        """Test connectivity by performing the handshake without sending a command.

        Raises HandshakeTimeoutError or ConnectionError on failure.
        """
        ready_event = asyncio.Event()

        def _on_notify(_sender: Any, data: bytearray) -> None:
            if payload_contains_ready_marker(bytes(data)):
                ready_event.set()

        client = await establish_connection(
            BleakClient, self._ble_device, self._ble_device.address
        )
        try:
            await client.start_notify(READ_CHAR_UUID, _on_notify)
            await client.write_gatt_char(WRITE_CHAR_UUID, RECONNECT_PACKET)

            try:
                await asyncio.wait_for(ready_event.wait(), HANDSHAKE_TIMEOUT)
            except TimeoutError as err:
                raise HandshakeTimeoutError(
                    f"Device did not become ready within {HANDSHAKE_TIMEOUT}s"
                ) from err
        finally:
            await client.disconnect()

    async def turn_on(self, brightness_level: int | None = None) -> None:
        """Turn the light on, optionally setting brightness."""
        from .const import ACTION_BODY_ON

        await self._execute_command(ACTION_BODY_ON)
        self._state.is_on = True
        if brightness_level is not None:
            await self.set_brightness(brightness_level)
        self._fire_callbacks()

    async def turn_off(self) -> None:
        """Turn the light off."""
        from .const import ACTION_BODY_OFF

        await self._execute_command(ACTION_BODY_OFF)
        self._state.is_on = False
        self._fire_callbacks()

    async def pause(self) -> None:
        """Pause an active dimming sequence."""
        from .const import ACTION_BODY_PAUSE

        await self._execute_command(ACTION_BODY_PAUSE)
        self._state.is_paused = True
        self._fire_callbacks()

    async def resume(self) -> None:
        """Resume a paused dimming sequence."""
        from .const import ACTION_BODY_RESUME

        await self._execute_command(ACTION_BODY_RESUME)
        self._state.is_paused = False
        self._fire_callbacks()

    async def set_dimming_time(self, minutes: int) -> None:
        """Set the dimming time in minutes.

        Not yet implemented — action bytes have not been validated
        against real device captures.
        """
        raise NotImplementedError(
            "set_dimming_time is not yet validated against device captures"
        )

    async def set_brightness(self, level: int) -> None:
        """Set brightness level (1-5).

        Not yet implemented — action bytes have not been validated
        against real device captures.
        """
        raise NotImplementedError(
            "set_brightness is not yet validated against device captures"
        )

    async def _execute_command(self, action_body: bytes) -> None:
        """Connect, handshake, send command, disconnect."""
        ready_event = asyncio.Event()
        token: int | None = None

        def _on_notify(_sender: Any, data: bytearray) -> None:
            nonlocal token
            _LOGGER.debug("Notification: %s", data.hex())
            self._parse_state_notification(bytes(data))
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
