"""pycasperglow - Async Python library for Casper Glow lights."""

from .const import DEVICE_NAME_PREFIX, DIMMING_TIME_MINUTES, SERVICE_UUID
from .device import CasperGlow, GlowState
from .discovery import discover_glows, is_casper_glow
from .exceptions import (
    CasperGlowError,
    CommandError,
    ConnectionError,
    HandshakeTimeoutError,
)

__all__ = [
    "CasperGlow",
    "CasperGlowError",
    "CommandError",
    "ConnectionError",
    "DEVICE_NAME_PREFIX",
    "DIMMING_TIME_MINUTES",
    "GlowState",
    "HandshakeTimeoutError",
    "SERVICE_UUID",
    "discover_glows",
    "is_casper_glow",
]
