"""Buttons: bell, refresh."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PolarDeviceEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    async_add_entities([BellButton(hub, "bell", entry.title),
                        RefreshButton(hub, "refresh", entry.title)])


class BellButton(PolarDeviceEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self.hub.async_bell()


class RefreshButton(PolarDeviceEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self.hub.async_refresh()
