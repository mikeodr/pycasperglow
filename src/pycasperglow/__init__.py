"""pycasperglow - Async Python library for Casper Glow lights."""

from .const import (
    BRIGHTNESS_LEVELS,
    DEVICE_NAME_PREFIX,
    DIMMING_TIME_MINUTES,
    GATT_SERVICE_UUID,
    MANUFACTURER_ID,
    RISE_LINGER_MINUTES,
)
from .device import AnimationType, BatteryLevel, CasperGlow, GlowState
from .discovery import discover_glows, is_casper_glow
from .exceptions import (
    CasperGlowError,
    CommandError,
    ConnectionError,
    HandshakeTimeoutError,
)
from .protocol import RiseAlarm, Weekday

__all__ = [
    "AnimationType",
    "BRIGHTNESS_LEVELS",
    "BatteryLevel",
    "CasperGlow",
    "CasperGlowError",
    "CommandError",
    "ConnectionError",
    "DEVICE_NAME_PREFIX",
    "DIMMING_TIME_MINUTES",
    "GATT_SERVICE_UUID",
    "GlowState",
    "HandshakeTimeoutError",
    "MANUFACTURER_ID",
    "RISE_LINGER_MINUTES",
    "RiseAlarm",
    "Weekday",
    "discover_glows",
    "is_casper_glow",
]
