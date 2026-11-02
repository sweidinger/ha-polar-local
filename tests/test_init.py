"""Integration tests with a mocked MQTT broker."""
import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.polar_local.const import CONF_SERIAL, DOMAIN

SN = "AF05TEST0000000Q"
BASE = f"dl/PLAF109/{SN}/device"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def _setup(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_SERIAL: SN}, unique_id=SN, title="Polar")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sent(mqtt_mock, kind):
    return [json.loads(c.args[1]) for c in mqtt_mock.async_publish.call_args_list
            if c.args[0] == f"{BASE}/{kind}/sub"]


def _eid(hass, platform, key):
    from homeassistant.helpers import entity_registry as er
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SN}_{key}")


async def test_heartbeat_ntp_echo_and_entities(hass, mqtt_mock):
    await hass.config.async_update(time_zone="Europe/Berlin")
    await _setup(hass, mqtt_mock)

    async_fire_mqtt_message(hass, f"{BASE}/ntp/post", json.dumps({"cmd": "NTP", "msgId": "n1", "ts": 0}))
    async_fire_mqtt_message(hass, f"{BASE}/heart/post", json.dumps(
        {"cmd": "HEARTBEAT", "rssi": -50, "temperature": 12.34, "count": 1}))
    async_fire_mqtt_message(hass, f"{BASE}/event/post", json.dumps(
        {"cmd": "ATTR_PUSH_EVENT", "msgId": "a1", "volume": 49, "closeDoorTime": 30,
         "lightSwitch": False, "soundSwitch": True, "platePosition": 2}))
    async_fire_mqtt_message(hass, f"{BASE}/event/post", json.dumps(
        {"cmd": "PET_DETECT_EVENT", "msgId": "p1", "type": "NEAR"}))
    await hass.async_block_till_done()

    ntp = _sent(mqtt_mock, "ntp")
    assert ntp and ntp[0]["msgId"] == "n1" and ntp[0]["timezoneOffsetSeconds"] in (3600, 7200)
    echoes = _sent(mqtt_mock, "event")
    assert [e["msgId"] for e in echoes] == ["a1"]  # PET_DETECT is not echoed

    assert hass.states.get(_eid(hass, "sensor", "temperature")).state == "12.3"
    assert hass.states.get(_eid(hass, "binary_sensor", "online")).state == "on"
    assert hass.states.get(_eid(hass, "binary_sensor", "pet_near")).state == "on"
    assert hass.states.get(_eid(hass, "select", "plate")).state == "plate_2"
    assert hass.states.get(_eid(hass, "number", "volume")).state == "49"
    assert hass.states.get(_eid(hass, "light", "indicator")).state == "off"


async def test_feeding_events_and_commands(hass, mqtt_mock):
    await _setup(hass, mqtt_mock)
    async_fire_mqtt_message(hass, f"{BASE}/heart/post", json.dumps({"cmd": "HEARTBEAT", "temperature": 12}))
    async_fire_mqtt_message(hass, f"{BASE}/event/post", json.dumps(
        {"cmd": "WET_GRAIN_OUTPUT_EVENT", "planId": 5, "plate": 1, "execStep": "OPEN_DOOR"}))
    await hass.async_block_till_done()
    lid = _eid(hass, "binary_sensor", "lid_open")
    assert hass.states.get(lid).state == "on"
    echo = _sent(mqtt_mock, "event")[-1]
    assert echo["execStep"] == "OPEN_DOOR" and "msgId" not in echo

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call("switch", "turn_off",
                                   {"entity_id": _eid(hass, "switch", "lid")}, blocking=True)
    stop = _sent(mqtt_mock, "service")[-1]
    assert stop["cmd"] == "WET_FOOD_FEED_STOP_SERVICE" and stop["planId"] == 5

    await hass.services.async_call("number", "set_value",
                                   {"entity_id": _eid(hass, "number", "volume"), "value": 60}, blocking=True)
    cmd = _sent(mqtt_mock, "service")[-1]
    assert cmd["cmd"] == "ATTR_SET_SERVICE" and cmd["volume"] == 60
    async_fire_mqtt_message(hass, f"{BASE}/config/post", json.dumps(
        {"cmd": "ATTR_SET_SERVICE", "msgId": cmd["msgId"], "code": 0}))
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, "number", "volume")).state == "60"

    await hass.services.async_call("button", "press",
                                   {"entity_id": _eid(hass, "button", "bell")}, blocking=True)
    assert _sent(mqtt_mock, "service")[-1]["action"] == "AUDIO"


async def test_set_plans_service(hass, mqtt_mock):
    await hass.config.async_update(time_zone="Europe/Berlin")
    await _setup(hass, mqtt_mock)
    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(DOMAIN, "set_plans", {"plans": [
        {"plate": 3, "time": "19:00", "date": "2030-01-15", "duration": 30},
        {"plate": 1, "time": "07:00", "date": "2030-01-16"},
    ]}, blocking=True)
    sent = _sent(mqtt_mock, "service")
    assert sent[0]["plans"] == []
    plans = sent[1]["plans"]
    assert plans[0]["executionTime"] == "18:00" and plans[0]["executionDay"] == "2030-01-15"
    assert plans[1]["executionTime"] == "06:00" and plans[1]["feedingDuration"] == 5
    assert sent[0]["linkId"] == sent[1]["linkId"]
    state = hass.states.get(_eid(hass, "sensor", "next_plan"))
    assert state.state.startswith("2030-01-15T18:00")
    assert len(state.attributes["plans"]) == 2

    async_fire_mqtt_message(hass, f"{BASE}/event/post", json.dumps(
        {"cmd": "WET_GRAIN_OUTPUT_EVENT", "planId": plans[0]["planId"], "execStep": "GRAIN_END", "finished": True}))
    await hass.async_block_till_done()
    assert len(hass.states.get(_eid(hass, "sensor", "next_plan")).attributes["plans"]) == 1


async def test_device_start_sends_cloud_followups(hass, mqtt_mock, freezer):
    from datetime import timedelta
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util
    await _setup(hass, mqtt_mock)
    async_fire_mqtt_message(hass, f"{BASE}/event/post", json.dumps(
        {"cmd": "DEVICE_START_EVENT", "msgId": "s1", "softwareVersion": "3.0.18",
         "hardwareVersion": "5.2.0", "mac": "B0:81:84:00:00:00"}))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    cmds = [c["cmd"] for c in _sent(mqtt_mock, "service")]
    assert cmds[:2] == ["ATTR_SET_SERVICE", "GET_SOME_ATTR_SERVICE"]
    assert hass.states.get(_eid(hass, "sensor", "firmware")).state == "3.0.18"


async def test_config_flow(hass, mqtt_mock):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"serial": "bad!", "name": "x"})
    assert result["errors"] == {"serial": "invalid_serial"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"serial": SN.lower(), "name": "Polar"})
    assert result["type"] == "create_entry" and result["data"] == {"serial": SN}
