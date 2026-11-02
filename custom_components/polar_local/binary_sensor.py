"""Binary sensors: lid open, pet at bowl, connected, temperature check."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PolarDeviceEntity, PolarEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    t = entry.title
    async_add_entities([
        StateBinary(hub, "lid_open", t, "lid_open", BinarySensorDeviceClass.DOOR),
        StateBinary(hub, "pet_near", t, "pet_near", BinarySensorDeviceClass.OCCUPANCY),
        StateBinary(hub, "temperature_check", t, "temperatureCheckSwitch", None,
                    EntityCategory.DIAGNOSTIC),
        Connected(hub, "online", t),
    ])


class StateBinary(PolarDeviceEntity, BinarySensorEntity):
    def __init__(self, hub, key, title, field, device_class, category=None) -> None:
        super().__init__(hub, key, title)
        self._field = field
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool | None:
        value = self.s.get(self._field)
        return None if value is None else bool(value)


class Connected(PolarEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return bool(self.s.get("online"))
