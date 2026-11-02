"""Base entity for PETLIBRO Polar (local)."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL_NAME
from .hub import PolarHub


class PolarEntity(Entity):
    """Entity that refreshes when the hub signals new data."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: PolarHub, key: str, title: str) -> None:
        self.hub = hub
        self._attr_unique_id = f"{hub.serial}_{key}"
        self._attr_translation_key = key
        mac = hub.state.get("mac")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.serial)},
            connections={(CONNECTION_NETWORK_MAC, mac.lower())} if mac else set(),
            name=title,
            manufacturer=MANUFACTURER,
            model=MODEL_NAME,
            model_id="PLAF109",
            serial_number=hub.serial,
            sw_version=hub.state.get("firmware"),
            hw_version=hub.state.get("hardware"),
        )

    @property
    def s(self) -> dict:
        return self.hub.state

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, self.hub.signal, self.async_write_ha_state))


class PolarDeviceEntity(PolarEntity):
    """Entity that is unavailable while the device is offline."""

    @property
    def available(self) -> bool:
        return bool(self.s.get("online"))
