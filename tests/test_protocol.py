"""Tests for the pure protocol helpers."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.polar_local import protocol as p

BERLIN = ZoneInfo("Europe/Berlin")


def test_ntp_reply_matches_cloud_capture():
    # cloud answer captured on 2026-10-29 (CET, next switch 2027-03-28)
    now = datetime(2026, 10, 29, 13, 0, tzinfo=timezone.utc)
    r = p.ntp_reply("abc", BERLIN, now)
    assert r["code"] == 0 and r["msgId"] == "abc" and r["calibrationTag"] is True
    assert r["timezoneOffsetSeconds"] == 3600 and r["timezone"] == 1
    assert r["nextDSTOffsetSeconds"] == 7200
    assert r["nextDSTTransitionTs"] == 1806195600000
    assert r["secondNextDSTOffsetSeconds"] == 3600
    assert r["secondNextDSTTransitionTs"] == 1824944400000


def test_event_echo_rules():
    assert p.event_echo({"cmd": "HEARTBEAT"}) is None
    assert p.event_echo({"cmd": "ATTR_PUSH_EVENT", "linkId": "x"}) is None
    e = p.event_echo({"cmd": "DEVICE_START_EVENT", "msgId": "m1"})
    assert e["msgId"] == "m1" and e["code"] == 0
    w = p.event_echo({"cmd": "WET_GRAIN_OUTPUT_EVENT", "msgId": "m2", "execStep": "OPEN_DOOR"})
    assert "msgId" not in w and w["execStep"] == "OPEN_DOOR"


def test_plan_entry_is_utc():
    when = datetime(2026, 10, 30, 19, 0, tzinfo=BERLIN)
    e = p.plan_entry(3, when, 30)
    assert e["executionTime"] == "18:00" and e["executionDay"] == "2026-10-30"
    assert e["plate"] == 3 and e["feedingDuration"] == 30 and "needThaw" not in e
    assert p.plan_entry(1, when, 5, need_thaw=False)["needThaw"] is False


def test_plan_entry_validates():
    when = datetime(2026, 10, 30, 19, 0, tzinfo=BERLIN)
    with pytest.raises(ValueError):
        p.plan_entry(4, when, 5)
    with pytest.raises(ValueError):
        p.plan_entry(1, when, 0)
