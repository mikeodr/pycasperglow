"""Exception hierarchy for pycasperglow."""


class CasperGlowError(Exception):
    """Base exception for pycasperglow."""


class ConnectionError(CasperGlowError):
    """Connection or handshake failure."""


class CommandError(CasperGlowError):
    """Failed to send a command to the device."""


class HandshakeTimeoutError(ConnectionError):
    """Ready marker not received within the timeout period."""
