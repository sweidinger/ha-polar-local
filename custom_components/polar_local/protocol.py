"""Petlibro Polar (PLAF109) MQTT protocol helpers.

Pure functions without Home Assistant dependencies, so they can be unit tested.
Protocol reverse engineered from captures of the Petlibro cloud talking to
firmware 3.0.14 and from strings in firmware 3.0.18 (see docs/API.md).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

MODEL = "PLAF109"
MANUAL_PLAN_ID = 666666666

# Events the cloud confirms on event/sub (everything else only gets a PUBACK).
EVENT_ECHO = {
    "DEVICE_START_EVENT",
    "ATTR_PUSH_EVENT",
    "GET_FEEDING_PLAN_EVENT",
    "WET_GRAIN_OUTPUT_EVENT",
}

PLATES = (1, 2, 3)


def base_topic(serial: str) -> str:
    """Return the topic root of one device."""
    return f"dl/{MODEL}/{serial}/device"


def now_ms() -> int:
    """Current time in milliseconds."""
    return int(time.time() * 1000)


def new_id() -> str:
    """Random message/link id like the cloud uses."""
    return uuid.uuid4().hex


def _offset(dt: datetime, tz: tzinfo) -> int:
    return int(dt.astimezone(tz).utcoffset().total_seconds())


def dst_transitions(tz: tzinfo, start: datetime | None = None,
                    count: int = 2) -> list[tuple[int, int]]:
    """Return the next ``count`` UTC-offset changes as (epoch ms, new offset s)."""
    now = start or datetime.now(timezone.utc)
    cur = prev = _offset(now, tz)
    result: list[tuple[int, int]] = []
    t = now
    for _ in range(400 * 24):
        t = t + timedelta(hours=1)
        off = _offset(t, tz)
        if off != prev:
            lo = t - timedelta(hours=1)
            while (t - lo) > timedelta(minutes=1):
                mid = lo + (t - lo) / 2
                if _offset(mid, tz) == prev:
                    lo = mid
                else:
                    t = mid
            edge = t.replace(second=0, microsecond=0)
            result.append((int(edge.timestamp() * 1000), off))
            prev = off
            if len(result) == count:
                break
    while len(result) < count:
        result.append((0, cur))
    return result


def ntp_reply(msg_id: str, tz: tzinfo, now: datetime | None = None) -> dict[str, Any]:
    """Answer to the device's NTP request (topic ntp/sub).

    ``code`` must not be 2030: firmware 3.0.18 unbinds itself on that code.
    """
    now = now or datetime.now(timezone.utc)
    cur = _offset(now, tz)
    trans = dst_transitions(tz, now)
    return {
        "cmd": "NTP",
        "ts": int(now.timestamp() * 1000),
        "msgId": msg_id,
        "code": 0,
        "calibrationTag": True,
        "timezoneOffsetSeconds": cur,
        "nextDSTOffsetSeconds": trans[0][1],
        "nextDSTTransitionTs": trans[0][0],
        "secondNextDSTOffsetSeconds": trans[1][1],
        "secondNextDSTTransitionTs": trans[1][0],
        "timezone": int(cur / 3600) if cur % 3600 == 0 else cur / 3600,
        "linkId": new_id(),
    }


def event_echo(data: dict[str, Any]) -> dict[str, Any] | None:
    """Confirmation the cloud sends for an event/post, or None."""
    cmd = data.get("cmd")
    if cmd not in EVENT_ECHO or "linkId" in data:
        return None
    echo = {"cmd": cmd, "ts": now_ms(), "msgId": data.get("msgId", ""),
            "code": 0, "linkId": new_id()}
    if cmd == "WET_GRAIN_OUTPUT_EVENT":
        echo.pop("msgId")
        echo["execStep"] = data.get("execStep", "")
    return echo


def service(cmd: str, **fields: Any) -> dict[str, Any]:
    """Build a service/sub command."""
    return {"cmd": cmd, "msgId": new_id(), "linkId": new_id(), "ts": now_ms(), **fields}


def plan_entry(plate: int, when: datetime, duration: int,
               plan_id: int | None = None, need_thaw: bool | None = None) -> dict[str, Any]:
    """One feeding plan. ``when`` is aware; the device expects UTC HH:MM."""
    if plate not in PLATES:
        raise ValueError(f"plate must be 1..3, got {plate}")
    if not 1 <= duration <= 240:
        raise ValueError(f"duration must be 1..240 minutes, got {duration}")
    utc = when.astimezone(timezone.utc)
    entry: dict[str, Any] = {
        "planId": plan_id if plan_id is not None
        else 70000000 + int(when.timestamp()) % 10000000 + plate,
        "executionTime": utc.strftime("%H:%M"),
        "executionDay": utc.strftime("%Y-%m-%d"),
        "plate": plate,
        "feedingDuration": duration,
    }
    if need_thaw is not None:
        entry["needThaw"] = need_thaw
    return entry


def feed_now_plan(plate: int, duration: int, local_now: datetime) -> dict[str, Any]:
    """Plan that opens immediately (how the Petlibro app opens the lid)."""
    return {
        "planId": MANUAL_PLAN_ID,
        "executionTime": local_now.strftime("%H:%M"),
        "executionDay": local_now.strftime("%Y-%m-%d"),
        "plate": plate,
        "feedingDuration": duration,
        "feedNowState": True,
    }
