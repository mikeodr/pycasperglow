"""Tests for Casper Glow discovery."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pycasperglow.const import SERVICE_UUID
from pycasperglow.discovery import is_casper_glow


def _make_device(name: str | None = None) -> Any:
    device = MagicMock()
    device.name = name
    return device


def _make_adv(
    local_name: str | None = None,
    service_uuids: list[str] | None = None,
) -> Any:
    adv = MagicMock()
    adv.local_name = local_name
    adv.service_uuids = service_uuids or []
    return adv


class TestIsCasperGlow:
    """is_casper_glow detection tests."""

    def test_match_by_service_uuid(self) -> None:
        device = _make_device()
        adv = _make_adv(service_uuids=[SERVICE_UUID])
        assert is_casper_glow(device, adv)

    def test_match_by_service_uuid_case_insensitive(self) -> None:
        device = _make_device()
        adv = _make_adv(service_uuids=[SERVICE_UUID.upper()])
        assert is_casper_glow(device, adv)

    def test_match_by_local_name(self) -> None:
        device = _make_device()
        adv = _make_adv(local_name="JarGlow123")
        assert is_casper_glow(device, adv)

    def test_match_by_device_name(self) -> None:
        device = _make_device(name="Jar")
        adv = _make_adv()
        assert is_casper_glow(device, adv)

    def test_no_match(self) -> None:
        device = _make_device(name="SomeOtherDevice")
        adv = _make_adv(local_name="SomeOtherDevice")
        assert not is_casper_glow(device, adv)

    def test_no_match_none_names(self) -> None:
        device = _make_device(name=None)
        adv = _make_adv(local_name=None)
        assert not is_casper_glow(device, adv)

    def test_no_match_partial_prefix(self) -> None:
        device = _make_device(name="Ja")
        adv = _make_adv(local_name="Ja")
        assert not is_casper_glow(device, adv)
