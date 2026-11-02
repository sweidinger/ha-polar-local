"""Switches: lid, sound."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PolarDeviceEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    async_add_entities([
        LidSwitch(hub, "lid", entry.title),
        SoundSwitch(hub, "sound", entry.title),
    ])


class LidSwitch(PolarDeviceEntity, SwitchEntity):
    """Open: feed-now plan for 'max open duration' minutes. Off: stop."""

    @property
    def is_on(self) -> bool:
        return bool(self.s.get("lid_open"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_feed_now()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_stop_feeding()


class SoundSwitch(PolarDeviceEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        value = self.s.get("soundSwitch")
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_set_attr(soundSwitch=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set_attr(soundSwitch=False)

