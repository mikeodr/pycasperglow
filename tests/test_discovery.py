"""Tests for Casper Glow discovery."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pycasperglow.const import MANUFACTURER_ID
from pycasperglow.discovery import is_casper_glow

GLOW_MANUFACTURER_DATA = {MANUFACTURER_ID: b"\x00"}


def _make_device(name: str | None = None) -> Any:
    device = MagicMock()
    device.name = name
    return device


def _make_adv(
    local_name: str | None = None,
    manufacturer_data: dict[int, bytes] | None = None,
) -> Any:
    adv = MagicMock()
    adv.local_name = local_name
    adv.manufacturer_data = manufacturer_data or {}
    return adv


class TestIsCasperGlow:
    """is_casper_glow detection tests."""

    @pytest.mark.parametrize(
        ("device_name", "local_name"),
        [
            (None, "JarGlow123"),
            ("Jar", None),
            ("Jar_0", "Jar_0"),
        ],
        ids=["local_name", "device_name", "both_names"],
    )
    def test_matches(
        self,
        device_name: str | None,
        local_name: str | None,
    ) -> None:
        device = _make_device(name=device_name)
        adv = _make_adv(local_name=local_name, manufacturer_data=GLOW_MANUFACTURER_DATA)
        assert is_casper_glow(device, adv)

    @pytest.mark.parametrize(
        ("device_name", "local_name"),
        [
            ("SomeOtherDevice", "SomeOtherDevice"),
            (None, None),
            ("Ja", "Ja"),
        ],
        ids=["different_device", "none_names", "partial_prefix"],
    )
    def test_no_match(
        self,
        device_name: str | None,
        local_name: str | None,
    ) -> None:
        device = _make_device(name=device_name)
        adv = _make_adv(local_name=local_name, manufacturer_data=GLOW_MANUFACTURER_DATA)
        assert not is_casper_glow(device, adv)

    @pytest.mark.parametrize(
        "manufacturer_data",
        [{}, {0x004C: b"\x00"}],
        ids=["no_manufacturer_data", "other_manufacturer"],
    )
    def test_name_without_manufacturer_id_no_match(
        self, manufacturer_data: dict[int, bytes]
    ) -> None:
        device = _make_device(name="Jar")
        adv = _make_adv(local_name="Jar", manufacturer_data=manufacturer_data)
        assert not is_casper_glow(device, adv)
