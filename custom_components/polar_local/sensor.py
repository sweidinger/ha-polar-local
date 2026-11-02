"""Sensors."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .entity import PolarDeviceEntity, PolarEntity

DIAG = EntityCategory.DIAGNOSTIC

# key: (state field, device class, state class, unit, category, device-entity?)
SIMPLE = {
    "temperature": ("temperature", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
                    UnitOfTemperature.CELSIUS, None, True),
    "rssi": ("rssi", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT,
             SIGNAL_STRENGTH_DECIBELS_MILLIWATT, DIAG, True),
    "last_step": ("step", None, None, None, DIAG, False),
    "event_code": ("event_code", None, None, None, DIAG, False),
    "firmware": ("firmware", None, None, None, DIAG, False),
    "ringer_mode": ("ringerMode", None, None, None, DIAG, False),
    "door_stuck_current": ("doorStuckCurrent", SensorDeviceClass.CURRENT, None,
                           UnitOfElectricCurrent.MILLIAMPERE, DIAG, False),
    "plate_stuck_current": ("plateStuckCurrent", SensorDeviceClass.CURRENT, None,
                            UnitOfElectricCurrent.MILLIAMPERE, DIAG, False),
    "door_check_time": ("doorCheckSignalTime", None, None, None, DIAG, False),
    "door_nocheck_time": ("doorNotcheckSignalTime", None, None, None, DIAG, False),
    "ota_progress": ("ota_progress", None, None, "%", DIAG, False),
}


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    t = entry.title
    entities: list = []
    for key, (field, dc, sc, unit, cat, dev) in SIMPLE.items():
        cls = DeviceSimpleSensor if dev else SimpleSensor
        entities.append(cls(hub, key, t, field, dc, sc, unit, cat))
    entities += [LastSeen(hub, "last_seen", t), NextPlan(hub, "next_plan", t)]
    async_add_entities(entities)


class SimpleSensor(PolarEntity, SensorEntity):
    def __init__(self, hub, key, title, field, dc, sc, unit, cat) -> None:
        super().__init__(hub, key, title)
        self._field = field
        self._attr_device_class = dc
        self._attr_state_class = sc
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = cat

    @property
    def native_value(self) -> Any:
        return self.s.get(self._field)


class DeviceSimpleSensor(PolarDeviceEntity, SimpleSensor):
    pass


class LastSeen(PolarEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = DIAG

    @property
    def native_value(self) -> datetime | None:
        value = self.s.get("last_seen")
        return dt_util.parse_datetime(value) if value else None


class NextPlan(PolarEntity, SensorEntity):
    """Next feeding plan written by this integration (start time)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.hub.next_plan()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        out = []
        for plan in self.s.get("plans", []):
            try:
                when = datetime.strptime(f"{plan['executionDay']} {plan['executionTime']}",
                                         "%Y-%m-%d %H:%M").replace(tzinfo=dt_util.UTC)
            except (KeyError, ValueError):
                continue
            out.append({"start": dt_util.as_local(when).isoformat(), "plate": plan.get("plate"),
                        "duration": plan.get("feedingDuration"), "plan_id": plan.get("planId")})
        return {"plans": out}
