"""PETLIBRO Polar wet food feeder, fully local via Home Assistant's MQTT broker."""
from __future__ import annotations

from datetime import datetime, timedelta

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from . import protocol as p
from .const import (
    CONF_SERIAL,
    DOMAIN,
    SERVICE_CLEAR_PLANS,
    SERVICE_FEED_NOW,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_PLANS,
    SERVICE_STOP,
)
from .hub import PolarHub

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type PolarConfigEntry = ConfigEntry[PolarHub]

PLAN_SCHEMA = vol.Schema({
    vol.Required("plate"): vol.All(vol.Coerce(int), vol.In(p.PLATES)),
    vol.Required("time"): cv.time,
    vol.Optional("date"): cv.date,
    vol.Optional("duration", default=5): vol.All(vol.Coerce(int), vol.Range(1, 240)),
    vol.Optional("need_thaw"): cv.boolean,
})

SET_PLANS_SCHEMA = vol.Schema({
    vol.Optional("device_id"): cv.string,
    vol.Required("plans"): vol.All(cv.ensure_list, [PLAN_SCHEMA]),
})
DEVICE_ONLY_SCHEMA = vol.Schema({vol.Optional("device_id"): cv.string})
FEED_NOW_SCHEMA = vol.Schema({
    vol.Optional("device_id"): cv.string,
    vol.Optional("plate"): vol.All(vol.Coerce(int), vol.In(p.PLATES)),
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(1, 240)),
})
SEND_SCHEMA = vol.Schema({
    vol.Optional("device_id"): cv.string,
    vol.Optional("topic", default="service"): vol.In(["service", "config", "ota", "event", "ntp"]),
    vol.Required("payload"): dict,
})


async def async_setup_entry(hass: HomeAssistant, entry: PolarConfigEntry) -> bool:
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT integration is not available")
    hub = PolarHub(hass, entry.entry_id, entry.data[CONF_SERIAL])
    await hub.async_start()
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PolarConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok


def _hub_for(hass: HomeAssistant, call: ServiceCall) -> PolarHub:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN)
               if getattr(e, "runtime_data", None) is not None]
    device_id = call.data.get("device_id")
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        if device:
            for entry in entries:
                if entry.entry_id in device.config_entries:
                    return entry.runtime_data
        raise ServiceValidationError(f"No Polar found for device {device_id}")
    if len(entries) != 1:
        raise ServiceValidationError("Several Polars configured, please pass device_id")
    return entries[0].runtime_data


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_PLANS):
        return

    async def set_plans(call: ServiceCall) -> None:
        hub = _hub_for(hass, call)
        now = dt_util.now()
        plans = []
        for item in call.data["plans"]:
            day = item.get("date")
            when = datetime.combine(day or now.date(), item["time"], tzinfo=now.tzinfo)
            if day is None and when <= now:
                when += timedelta(days=1)
            plans.append(p.plan_entry(item["plate"], when, item["duration"],
                                      need_thaw=item.get("need_thaw")))
        await hub.async_set_plans(plans)

    async def clear_plans(call: ServiceCall) -> None:
        await _hub_for(hass, call).async_set_plans([])

    async def feed_now(call: ServiceCall) -> None:
        await _hub_for(hass, call).async_feed_now(call.data.get("plate"), call.data.get("duration"))

    async def stop(call: ServiceCall) -> None:
        await _hub_for(hass, call).async_stop_feeding()

    async def send(call: ServiceCall) -> None:
        payload = call.data["payload"]
        if not isinstance(payload.get("cmd"), str):
            raise ServiceValidationError("payload needs a 'cmd'")
        await _hub_for(hass, call).async_send(call.data["topic"], payload)

    hass.services.async_register(DOMAIN, SERVICE_SET_PLANS, set_plans, schema=SET_PLANS_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_PLANS, clear_plans, schema=DEVICE_ONLY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_FEED_NOW, feed_now, schema=FEED_NOW_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP, stop, schema=DEVICE_ONLY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_COMMAND, send, schema=SEND_SCHEMA)
