"""pycasperglow - Async Python library for Casper Glow lights."""

from .const import (
    BRIGHTNESS_LEVELS,
    DEVICE_NAME_PREFIX,
    DIMMING_TIME_MINUTES,
    GATT_SERVICE_UUID,
    MANUFACTURER_ID,
)
from .device import BatteryLevel, CasperGlow, GlowState
from .discovery import discover_glows, is_casper_glow
from .exceptions import (
    CasperGlowError,
    CommandError,
    ConnectionError,
    HandshakeTimeoutError,
)

__all__ = [
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
    "discover_glows",
    "is_casper_glow",
]
