"""Async BLE client for Casper Glow lights."""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    HANDSHAKE_TIMEOUT,
    QUERY_STATE_BODY,
    READ_CHAR_UUID,
    RECONNECT_PACKET,
    STATE_RESPONSE_TIMEOUT,
    WRITE_CHAR_UUID,
)
from .exceptions import CommandError, HandshakeTimeoutError
from .protocol import (
    build_action_packet,
    build_brightness_body,
    extract_token_from_notify,
    parse_protobuf_fields,
    parse_state_response,
    payload_contains_ready_marker,
)

_LOGGER = logging.getLogger(__name__)


_BATTERY_PERCENTAGE: dict[int, int] = {3: 25, 4: 50, 5: 75, 6: 100}


class BatteryLevel(enum.IntEnum):
    """Discrete battery level reported by the device.

    The Casper Glow encodes battery state as a 4-step enum in field 7 of
    the state response (a nested protobuf sub-message; inner field 2).
    The raw values map to approximate percentages:

      PCT_25  (3) — ~25 % — low; device should be charged.
      PCT_50  (4) — ~50 %.
      PCT_75  (5) — ~75 %.
      PCT_100 (6) — ~100 % — fully charged.

    Values not listed here are mapped to ``None`` by :meth:`from_raw`.
    """

    PCT_25 = 3
    PCT_50 = 4
    PCT_75 = 5
    PCT_100 = 6

    @property
    def percentage(self) -> int:
        """Return the approximate battery percentage as an integer."""
        return _BATTERY_PERCENTAGE[self.value]

    def __str__(self) -> str:
        return f"{self.percentage}%"

    @classmethod
    def from_raw(cls, value: int) -> BatteryLevel | None:
        """Return the matching member, or None if the value is unrecognised."""
        try:
            return cls(value)
        except ValueError:
            _LOGGER.debug("Unrecognised battery level raw value: %d", value)
            return None


@dataclass
class GlowState:
    """Represents the current state of a Casper Glow light."""

    is_on: bool | None = None
    brightness_level: int | None = None
    battery_level: BatteryLevel | None = None
    dimming_time_minutes: int | None = None  # remaining time from device
    configured_dimming_time_minutes: int | None = None  # set only by set_dimming_time()
    is_paused: bool | None = None
    raw_state: bytes | None = None


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
        self._ble_lock = asyncio.Lock()

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

        The device reports state in protobuf field 19 (nested inside
        field 4 of the notification).  The field-19 inner sub-fields:

        * sub-field 1: power/mode indicator (1 = on, 3 = off)
        * sub-field 2: remaining dimming time in milliseconds
            (counts down to 0 when off)
        * sub-field 3: configured total dimming duration in milliseconds
            (0 when off)
        * sub-field 4: paused indicator (0 = not paused, 1 = paused)
        * sub-field 7: nested message whose inner field 2 is a discrete
            battery level enum (3 = 25 %, 4 = 50 %, 5 = 75 %, 6 = 100 %).
        * sub-field 8: always 100 in all captures — NOT the battery level.
        """
        state_fields = parse_state_response(data)
        if state_fields is None:
            return False

        self._state.raw_state = data

        # Sub-field 1: power/mode indicator (1 = on, 3 = off)
        sf1 = state_fields.get(1)
        if sf1 is not None and isinstance(sf1[0], int):
            self._state.is_on = sf1[0] == 1
            if not self._state.is_on:
                self._state.is_paused = False

        # Sub-field 2: remaining dimming time in milliseconds (counts down to 0)
        sf2 = state_fields.get(2)
        if sf2 is not None and isinstance(sf2[0], int):
            self._state.dimming_time_minutes = sf2[0] // 60_000

        # Sub-field 3: configured total duration in milliseconds.
        # Only update when non-zero — device reports 0 when off.
        sf3 = state_fields.get(3)
        if sf3 is not None and isinstance(sf3[0], int):
            total_ms = sf3[0]
            if total_ms > 0:
                self._state.configured_dimming_time_minutes = total_ms // 60_000

        # Force remaining time to 0 when device is off regardless of what the
        # device reported in sub-field 3.
        if self._state.is_on is False:
            self._state.dimming_time_minutes = 0

        # Sub-field 4: paused indicator (0 = not paused, 1 = paused)
        sf4 = state_fields.get(4)
        if sf4 is not None and isinstance(sf4[0], int):
            self._state.is_paused = sf4[0] != 0

        # Sub-field 7: battery level (nested message, inner field 2).
        # Discrete enum — observed values: 6 = full, 3 = low.
        # Sub-field 8 is always 100 in all captures and is NOT the battery.
        # Brightness is not reported in the state query response.
        sf7 = state_fields.get(7)
        if sf7 is not None and isinstance(sf7[0], bytes):
            inner = parse_protobuf_fields(sf7[0])
            inner2 = inner.get(2)
            if inner2 is not None and isinstance(inner2[0], int):
                self._state.battery_level = BatteryLevel.from_raw(inner2[0])

        _LOGGER.debug("Parsed state from notification: %s", self._state)
        return True

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
        self._state.dimming_time_minutes = 0
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

        Valid values: 15, 30, 45, 60, 90.  The dimming time is sent
        alongside the current brightness level.  Brightness must have
        been set via ``set_brightness()`` before calling this method;
        raises ``ValueError`` if brightness is not yet known.
        """
        from .const import DIMMING_TIME_MINUTES

        if minutes not in DIMMING_TIME_MINUTES:
            raise ValueError(
                f"Invalid dimming time {minutes}; must be one of {DIMMING_TIME_MINUTES}"
            )
        if self._state.brightness_level is None:
            raise ValueError("Brightness level is unknown; call set_brightness() first")
        body = build_brightness_body(self._state.brightness_level, minutes * 60_000)
        await self._execute_command(body)
        self._state.configured_dimming_time_minutes = minutes
        self._fire_callbacks()

    async def set_brightness(self, level: int) -> None:
        """Set brightness percentage.

        Valid values: 60, 70, 80, 90, 100 (matching iOS app levels 1-5).
        The brightness command also includes the current dimming time.
        If the dimming time is unknown, 15 minutes is used as the default.
        """
        from .const import BRIGHTNESS_LEVELS, DIMMING_TIME_MINUTES

        if level not in BRIGHTNESS_LEVELS:
            raise ValueError(
                f"Invalid brightness {level}; must be one of {BRIGHTNESS_LEVELS}"
            )
        dim_min = self._state.configured_dimming_time_minutes or DIMMING_TIME_MINUTES[0]
        body = build_brightness_body(level, dim_min * 60_000)
        await self._execute_command(body)
        self._state.brightness_level = level
        self._fire_callbacks()

    async def _execute_command(self, action_body: bytes) -> None:
        """Connect, handshake, send command, disconnect."""
        async with self._ble_lock:
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

    async def query_state(self) -> GlowState:
        """Query the device for its current state.

        Connects, performs the handshake, sends a state query command,
        waits for the state response notification, and returns the
        updated GlowState.
        """
        async with self._ble_lock:
            ready_event = asyncio.Event()
            state_event = asyncio.Event()
            token: int | None = None

            def _on_notify(_sender: Any, data: bytearray) -> None:
                nonlocal token
                _LOGGER.debug("Notification: %s", data.hex())
                if self._parse_state_notification(bytes(data)):
                    state_event.set()
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

                packet = build_action_packet(token, QUERY_STATE_BODY)
                await client.write_gatt_char(WRITE_CHAR_UUID, packet)
                _LOGGER.debug("Sent state query: %s", packet.hex())

                try:
                    await asyncio.wait_for(state_event.wait(), STATE_RESPONSE_TIMEOUT)
                except TimeoutError:
                    _LOGGER.warning("State response timeout — returning cached state")

                self._fire_callbacks()
            finally:
                if self._external_client is None:
                    await client.disconnect()

            return self._state
