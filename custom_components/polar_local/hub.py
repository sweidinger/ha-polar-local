"""Local "cloud" for one Polar: answers the device on Home Assistant's MQTT broker."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components import mqtt
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import protocol as p
from .const import (
    DEFAULT_IR_TIMEOUT,
    DEFAULT_MAX_OPEN,
    DOMAIN,
    HEARTBEAT_TIMEOUT,
    SETTING_KEYS,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


class PolarHub:
    """Talks to one Polar over Home Assistant's MQTT integration."""

    def __init__(self, hass: HomeAssistant, entry_id: str, serial: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.serial = serial
        self.base = p.base_topic(serial)
        self.signal = SIGNAL_UPDATE.format(entry_id)
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{serial}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._last_heart: datetime | None = None
        self.state: dict[str, Any] = {
            "online": False, "temperature": None, "rssi": None, "plate": None,
            "lid_open": False, "step": None, "plan_id": None, "event_code": None,
            "pet_near": False, "firmware": None, "hardware": None, "mac": None,
            "last_seen": None, "zero_state": None, "ota_progress": None,
            "plans": [],
        }
        for key in SETTING_KEYS:
            self.state[key] = None
        self.prefs: dict[str, Any] = {
            "irSensorIdenTimeout": DEFAULT_IR_TIMEOUT,
            "maxOpen": DEFAULT_MAX_OPEN,
        }
        self._pending: dict[str, dict[str, Any]] = {}

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.hass.config.time_zone)

    # ------------------------------------------------------------------ setup
    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.prefs.update(stored.get("prefs", {}))
        for key, value in stored.get("last", {}).items():
            if key in self.state:
                self.state[key] = value
        self.state["irSensorIdenTimeout"] = self.prefs["irSensorIdenTimeout"]
        self._unsubs.append(await mqtt.async_subscribe(
            self.hass, f"{self.base}/+/post", self._on_message, qos=1))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._watchdog, timedelta(seconds=15)))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._save()

    async def _save(self) -> None:
        last = {k: self.state[k] for k in
                (*SETTING_KEYS, "plate", "firmware", "hardware", "mac", "plans")
                if self.state.get(k) is not None}
        await self._store.async_save({"prefs": self.prefs, "last": last})

    @callback
    def _changed(self) -> None:
        async_dispatcher_send(self.hass, self.signal)
        self.hass.async_create_task(self._save())

    # ------------------------------------------------------------ device -> HA
    async def _publish(self, kind: str, payload: dict[str, Any]) -> None:
        payload.setdefault("ts", p.now_ms())
        _LOGGER.debug("-> %s %s", kind, payload)
        await mqtt.async_publish(self.hass, f"{self.base}/{kind}/sub",
                                 json.dumps(payload), qos=0, retain=False)

    @callback
    def _on_message(self, msg: mqtt.ReceiveMessage) -> None:
        if msg.retain:
            return
        try:
            data = json.loads(msg.payload)
        except ValueError:
            _LOGGER.warning("Polar sent invalid JSON on %s", msg.topic)
            return
        if not isinstance(data, dict):
            return
        kind = msg.topic.rsplit("/", 2)[-2]
        cmd = data.get("cmd", "")
        _LOGGER.debug("<- %s %s", kind, data)
        s = self.state
        s["last_seen"] = dt_util.utcnow().isoformat()

        if kind == "heart" and cmd == "HEARTBEAT":
            self._last_heart = dt_util.utcnow()
            if data.get("temperature") is not None:
                s["temperature"] = round(float(data["temperature"]), 1)
            s["rssi"] = data.get("rssi")
            s["online"] = True
        elif kind == "ntp" and cmd == "NTP":
            self.hass.async_create_task(
                self._publish("ntp", p.ntp_reply(data.get("msgId", ""), self.tz)))
        elif kind == "event":
            self._event(cmd, data)
            echo = p.event_echo(data)
            if echo:
                self.hass.async_create_task(self._publish("event", echo))
        elif kind == "config" and cmd == "ATTR_SET_SERVICE":
            change = self._pending.pop(data.get("msgId", ""), None)
            if change and data.get("code") == 0:
                s.update(change)
            elif change:
                _LOGGER.warning("Polar rejected %s: %s", change, data)
        elif kind == "service" and cmd == "ATTR_PUSH_EVENT":
            self._attrs(data)
        elif kind == "ota" and cmd == "OTA_PROGRESS":
            s["ota_progress"] = data.get("progress")
        self._changed()

    def _attrs(self, d: dict[str, Any]) -> None:
        s = self.state
        if "platePosition" in d:
            s["plate"] = d["platePosition"]
        if "zeroState" in d:
            s["zero_state"] = d["zeroState"]
        for key in SETTING_KEYS:
            if key in d:
                s[key] = d[key]

    def _event(self, cmd: str, d: dict[str, Any]) -> None:
        s = self.state
        if cmd == "ATTR_PUSH_EVENT":
            self._attrs(d)
        elif cmd == "DEVICE_START_EVENT":
            s["firmware"] = d.get("softwareVersion")
            s["hardware"] = d.get("hardwareVersion")
            s["mac"] = d.get("mac")
            s["lid_open"] = False
            s["ota_progress"] = None
            async_call_later(self.hass, 1, self._after_start)
        elif cmd == "WET_GRAIN_OUTPUT_EVENT":
            step = d.get("execStep")
            s["step"] = step
            s["plan_id"] = d.get("planId", s["plan_id"])
            if step == "OPEN_DOOR":
                s["lid_open"] = True
            elif step in ("CLOSE_DOOR", "GRAIN_END"):
                s["lid_open"] = False
            if "plate" in d:
                s["plate"] = d["plate"]
            if step == "GRAIN_END":
                self._drop_plan(d.get("planId"))
        elif cmd == "WET_GRAIN_MULTI_EVENT":
            s["event_code"] = d.get("eventCode")
        elif cmd == "PET_DETECT_EVENT":
            s["pet_near"] = d.get("type") == "NEAR"

    def _drop_plan(self, plan_id: int | None) -> None:
        self.state["plans"] = [x for x in self.state["plans"] if x.get("planId") != plan_id]

    async def _after_start(self, _now: datetime | None = None) -> None:
        """What the Petlibro cloud does after every DEVICE_START_EVENT."""
        await self._publish("service", p.service(
            "ATTR_SET_SERVICE", irSensorIdenTimeout=self.prefs["irSensorIdenTimeout"], code=0))
        await self.async_refresh()

    @callback
    def _watchdog(self, _now: datetime) -> None:
        alive = self._last_heart is not None and \
            (dt_util.utcnow() - self._last_heart).total_seconds() < HEARTBEAT_TIMEOUT
        if alive != self.state["online"]:
            self.state["online"] = alive
            self._changed()

    # ------------------------------------------------------------ HA -> device
    async def async_refresh(self) -> None:
        await self._publish("service", p.service(
            "GET_SOME_ATTR_SERVICE", attrKeys=["platePosition"], code=0))

    async def async_set_attr(self, **fields: Any) -> None:
        """ATTR_SET_SERVICE; state is updated when the device confirms with code 0."""
        cmd = p.service("ATTR_SET_SERVICE", **fields)
        if "lightSwitch" in fields:
            cmd["lightAgingType"] = 1
        if "soundSwitch" in fields:
            cmd["soundAgingType"] = 1
        local = {k: v for k, v in fields.items() if k == "irSensorIdenTimeout"}
        if local:
            self.prefs.update(local)
            self.state.update(local)
        self._pending[cmd["msgId"]] = {k: v for k, v in fields.items()}
        await self._publish("service", cmd)
        self._changed()

    async def async_set_max_open(self, minutes: int) -> None:
        self.prefs["maxOpen"] = int(minutes)
        self._changed()

    async def async_feed_now(self, plate: int | None = None,
                             duration: int | None = None) -> None:
        plate = plate or self.state.get("plate") or 1
        duration = duration or int(self.prefs["maxOpen"])
        await self._publish("service", p.service(
            "WET_GRAIN_FEEDING_PLAN_SERVICE",
            plans=[p.feed_now_plan(plate, duration, dt_util.now())]))

    async def async_stop_feeding(self) -> None:
        await self._publish("service", p.service(
            "WET_FOOD_FEED_STOP_SERVICE",
            planId=self.state.get("plan_id") or p.MANUAL_PLAN_ID))

    async def async_set_plans(self, plans: list[dict[str, Any]]) -> None:
        """Replace all plans on the device (empty list first, like the app)."""
        link = p.new_id()
        await self._publish("service", {**p.service(
            "WET_GRAIN_FEEDING_PLAN_SERVICE", plans=[]), "linkId": link})
        if plans:
            await self._publish("service", {**p.service(
                "WET_GRAIN_FEEDING_PLAN_SERVICE", plans=plans), "linkId": link})
        self.state["plans"] = sorted(
            plans, key=lambda x: (x["executionDay"], x["executionTime"]))
        self._changed()

    async def async_set_plate(self, plate: int) -> None:
        await self._publish("service", p.service("SET_PLATE_POS_SERVICE", platePosition=plate))

    async def async_bell(self) -> None:
        await self._publish("service", p.service("DEVICE_FUNCTION_TEST_SERVICE", action="AUDIO"))

    async def async_send(self, kind: str, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload.setdefault("msgId", p.new_id())
        payload.setdefault("linkId", p.new_id())
        await self._publish(kind, payload)

    # ---------------------------------------------------------------- helpers
    def next_plan(self) -> datetime | None:
        """Start of the next stored plan (aware UTC), or None."""
        now = dt_util.utcnow()
        times = []
        for plan in self.state["plans"]:
            try:
                when = datetime.strptime(
                    f"{plan['executionDay']} {plan['executionTime']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=dt_util.UTC)
            except (KeyError, ValueError):
                continue
            if when >= now - timedelta(minutes=int(plan.get("feedingDuration", 0))):
                times.append(when)
        return min(times) if times else None
