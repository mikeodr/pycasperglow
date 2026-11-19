"""Async BLE client for Casper Glow lights."""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    MAX_CONNECT_ATTEMPTS,
    establish_connection,
)

from .const import (
    HANDSHAKE_TIMEOUT,
    QUERY_STATE_BODY,
    READ_CHAR_UUID,
    RECONNECT_PACKET,
    STATE_RESPONSE_TIMEOUT,
    WRITE_CHAR_UUID,
)
from .exceptions import CommandError, ConnectionError, HandshakeTimeoutError
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
    dimming_time_remaining_ms: int | None = None  # remaining time in milliseconds
    configured_dimming_time_minutes: int | None = (
        None  # set by set_brightness_and_dimming_time()
    )
    is_paused: bool | None = None
    is_charging: bool | None = None
    raw_state: bytes | None = None

    @property
    def dimming_time_minutes(self) -> int | None:
        """Return remaining dimming time in minutes, derived from milliseconds."""
        if self.dimming_time_remaining_ms is None:
            return None
        return self.dimming_time_remaining_ms // 60_000


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
        * sub-field 5: always 0 in all real-device captures — not the charging indicator
        * sub-field 7: nested message whose inner field 1 is a charging indicator
            (0 = not charging, 3 = charging observed); inner field 2 is a discrete
            battery level enum (3=25%, 4=50%, 5=75%, 6=100%).
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
            self._state.dimming_time_remaining_ms = sf2[0]

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
            self._state.dimming_time_remaining_ms = 0

        # Sub-field 4: paused indicator (0 = not paused, 1 = paused)
        sf4 = state_fields.get(4)
        if sf4 is not None and isinstance(sf4[0], int):
            self._state.is_paused = sf4[0] != 0

        # Sub-field 7: nested message.
        #   Inner field 1: charging indicator (0 = not charging, ≥1 = charging;
        #     3 observed in practice).
        #   Inner field 2: battery level enum (3=25%, 4=50%, 5=75%, 6=100%).
        # Sub-field 8 is always 100 and is NOT the battery level.
        sf7 = state_fields.get(7)
        if sf7 is not None and isinstance(sf7[0], bytes):
            inner = parse_protobuf_fields(sf7[0])
            inner1 = inner.get(1)
            if inner1 is not None and isinstance(inner1[0], int):
                self._state.is_charging = inner1[0] != 0
            inner2 = inner.get(2)
            if inner2 is not None and isinstance(inner2[0], int):
                self._state.battery_level = BatteryLevel.from_raw(inner2[0])

        _LOGGER.debug("Parsed state from notification: %s", self._state)
        return True

    @asynccontextmanager
    async def _connect(
        self,
        on_notify: Callable[[Any, bytearray], None],
        ready_event: asyncio.Event,
        *,
        max_attempts: int = MAX_CONNECT_ATTEMPTS,
    ) -> AsyncIterator[BleakClient]:
        """Connect, subscribe, send the reconnect packet and wait for ready.

        Holds ``_ble_lock`` for the whole session.  Uses the external client
        when one was supplied (never disconnecting it, but unsubscribing from
        notifications on exit); otherwise opens a fresh connection and always
        disconnects it on exit.  BLE failures during setup are raised as
        ``ConnectionError``; a missing ready marker as
        ``HandshakeTimeoutError``.  *on_notify* must set *ready_event*.
        """
        address = self._ble_device.address
        async with self._ble_lock:
            client = self._external_client
            subscribed = False
            try:
                try:
                    if client is None:
                        client = await establish_connection(
                            BleakClient,
                            self._ble_device,
                            address,
                            max_attempts=max_attempts,
                        )
                    if not client.is_connected:
                        await client.connect()
                    await client.start_notify(READ_CHAR_UUID, on_notify)
                    subscribed = True
                    await client.write_gatt_char(WRITE_CHAR_UUID, RECONNECT_PACKET)
                except BLEAK_RETRY_EXCEPTIONS as err:
                    raise ConnectionError(
                        f"Failed to connect to {address}: {err}"
                    ) from err

                try:
                    await asyncio.wait_for(ready_event.wait(), HANDSHAKE_TIMEOUT)
                except TimeoutError as err:
                    raise HandshakeTimeoutError(
                        f"Device did not become ready within {HANDSHAKE_TIMEOUT}s"
                    ) from err

                yield client
            finally:
                # Never let a failed cleanup mask the real error.
                if client is not None and self._external_client is None:
                    try:
                        await client.disconnect()
                    except Exception:
                        _LOGGER.debug(
                            "Error disconnecting from %s", address, exc_info=True
                        )
                elif client is not None and subscribed:
                    # The external client outlives this session; drop our
                    # handler so the next session can subscribe again.
                    try:
                        await client.stop_notify(READ_CHAR_UUID)
                    except Exception:
                        _LOGGER.debug(
                            "Error unsubscribing from %s", address, exc_info=True
                        )

    async def _send_action(
        self, client: BleakClient, token: int | None, action_body: bytes
    ) -> None:
        """Build and write an action packet; raise CommandError on failure."""
        if token is None:
            raise CommandError("Ready marker seen but no token extracted")
        packet = build_action_packet(token, action_body)
        try:
            await client.write_gatt_char(WRITE_CHAR_UUID, packet)
        except BLEAK_RETRY_EXCEPTIONS as err:
            raise CommandError(
                f"Failed to send command to {self._ble_device.address}: {err}"
            ) from err
        _LOGGER.debug("Sent action packet: %s", packet.hex())

    async def handshake(self, *, max_attempts: int = MAX_CONNECT_ATTEMPTS) -> None:
        """Test connectivity by performing the handshake without sending a command.

        *max_attempts* is passed to ``establish_connection``.  Callers probing a
        device that may not be a Casper Glow (e.g. during discovery) should use
        ``max_attempts=1`` to avoid holding connection slots on repeated retries.

        Raises HandshakeTimeoutError or ConnectionError on failure.
        """
        ready_event = asyncio.Event()

        def _on_notify(_sender: Any, data: bytearray) -> None:
            if payload_contains_ready_marker(bytes(data)):
                ready_event.set()

        async with self._connect(_on_notify, ready_event, max_attempts=max_attempts):
            pass

    async def turn_on(self) -> None:
        """Turn the light on."""
        from .const import ACTION_BODY_ON

        await self._execute_command(ACTION_BODY_ON)
        self._state.is_on = True
        self._fire_callbacks()

    async def turn_off(self) -> None:
        """Turn the light off."""
        from .const import ACTION_BODY_OFF

        await self._execute_command(ACTION_BODY_OFF)
        self._state.is_on = False
        self._state.dimming_time_remaining_ms = 0
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

    async def set_brightness_and_dimming_time(
        self, level: int, dimming_time_minutes: int
    ) -> None:
        """Set brightness percentage and dimming time together.

        Both values are required and transmitted in a single BLE command
        (the device protocol encodes them together in a field-18 protobuf
        message).

        Valid brightness values: 60, 70, 80, 90, 100 (iOS app levels 1–5).
        Valid dimming time values: 15, 30, 45, 60, 90 (minutes).
        """
        from .const import BRIGHTNESS_LEVELS, DIMMING_TIME_MINUTES

        if level not in BRIGHTNESS_LEVELS:
            raise ValueError(
                f"Invalid brightness {level}; must be one of {BRIGHTNESS_LEVELS}"
            )
        if dimming_time_minutes not in DIMMING_TIME_MINUTES:
            raise ValueError(
                f"Invalid dimming time {dimming_time_minutes};"
                f" must be one of {DIMMING_TIME_MINUTES}"
            )
        body = build_brightness_body(level, dimming_time_minutes * 60_000)
        await self._execute_command(body)
        self._state.brightness_level = level
        self._state.configured_dimming_time_minutes = dimming_time_minutes
        self._fire_callbacks()

    def _make_notify_handler(
        self, ready_event: asyncio.Event, state_event: asyncio.Event | None = None
    ) -> tuple[Callable[[Any, bytearray], None], Callable[[], int | None]]:
        """Return a notification handler and a getter for the extracted token.

        The handler parses state notifications (setting *state_event* when one
        is parsed) and sets *ready_event* once a session token is extracted.
        """
        token: int | None = None

        def _on_notify(_sender: Any, data: bytearray) -> None:
            nonlocal token
            payload = bytes(data)
            _LOGGER.debug("Notification: %s", payload.hex())
            if self._parse_state_notification(payload) and state_event is not None:
                state_event.set()
            if payload_contains_ready_marker(payload):
                extracted = extract_token_from_notify(payload)
                if extracted is not None:
                    token = extracted
                    ready_event.set()

        return _on_notify, lambda: token

    async def _execute_command(self, action_body: bytes) -> None:
        """Connect, handshake, send command, disconnect."""
        ready_event = asyncio.Event()
        on_notify, get_token = self._make_notify_handler(ready_event)
        async with self._connect(on_notify, ready_event) as client:
            await self._send_action(client, get_token(), action_body)

    async def query_state(self) -> GlowState:
        """Query the device for its current state.

        Connects, performs the handshake, sends a state query command,
        waits for the state response notification, and returns the
        updated GlowState.
        """
        ready_event = asyncio.Event()
        state_event = asyncio.Event()
        on_notify, get_token = self._make_notify_handler(ready_event, state_event)
        async with self._connect(on_notify, ready_event) as client:
            await self._send_action(client, get_token(), QUERY_STATE_BODY)
            try:
                await asyncio.wait_for(state_event.wait(), STATE_RESPONSE_TIMEOUT)
            except TimeoutError:
                _LOGGER.warning("State response timeout — returning cached state")
            self._fire_callbacks()

        return self._state
