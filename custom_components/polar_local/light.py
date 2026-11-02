"""Indicator LED."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PolarDeviceEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([IndicatorLight(entry.runtime_data, "indicator", entry.title)])


class IndicatorLight(PolarDeviceEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        value = self.s.get("lightSwitch")
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_set_attr(lightSwitch=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set_attr(lightSwitch=False)
