"""Plate position."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PLATE_OPTIONS
from .entity import PolarDeviceEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([PlateSelect(entry.runtime_data, "plate", entry.title)])


class PlateSelect(PolarDeviceEntity, SelectEntity):
    _attr_options = PLATE_OPTIONS

    @property
    def current_option(self) -> str | None:
        plate = self.s.get("plate")
        return PLATE_OPTIONS[plate - 1] if plate in (1, 2, 3) else None

    async def async_select_option(self, option: str) -> None:
        await self.hub.async_set_plate(PLATE_OPTIONS.index(option) + 1)
