"""Numbers: device settings (ATTR_SET_SERVICE) and the local max open duration."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PolarDeviceEntity, PolarEntity

# key: (attribute, min, max, unit)
SETTINGS = {
    "volume": ("volume", 0, 100, None),
    "close_delay": ("closeDoorTime", 5, 300, UnitOfTime.SECONDS),
    "ringer_interval": ("ringerInterval", 1, 60, UnitOfTime.MINUTES),
    "ringer_duration": ("ringerDuration", 1, 60, UnitOfTime.MINUTES),
    "ir_timeout": ("irSensorIdenTimeout", 1, 30, None),
}


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    entities: list = [SettingNumber(hub, key, entry.title, *cfg) for key, cfg in SETTINGS.items()]
    entities.append(MaxOpenNumber(hub, "max_open", entry.title))
    async_add_entities(entities)


class SettingNumber(PolarDeviceEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, hub, key, title, attr, lo, hi, unit) -> None:
        super().__init__(hub, key, title)
        self._attr = attr
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        return self.s.get(self._attr)

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.async_set_attr(**{self._attr: int(value)})


class MaxOpenNumber(PolarEntity, NumberEntity):
    """How long the lid switch opens the lid (stored in HA, not on the device)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    @property
    def native_value(self) -> float:
        return self.hub.prefs["maxOpen"]

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.async_set_max_open(int(value))
