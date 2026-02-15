"""pycasperglow - Async Python library for Casper Glow lights."""

from .const import DEVICE_NAME_PREFIX, SERVICE_UUID
from .device import CasperGlow
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
    "HandshakeTimeoutError",
    "SERVICE_UUID",
    "discover_glows",
    "is_casper_glow",
]
