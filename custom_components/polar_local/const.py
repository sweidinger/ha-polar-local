"""Constants for PETLIBRO Polar (local)."""
from __future__ import annotations

DOMAIN = "polar_local"
MANUFACTURER = "PETLIBRO"
MODEL_NAME = "Polar Wet Food Feeder"

CONF_SERIAL = "serial"

SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"

DEFAULT_MAX_OPEN = 45          # minutes the "lid" switch keeps the lid open
DEFAULT_IR_TIMEOUT = 2         # the cloud sends irSensorIdenTimeout=2 after every start
HEARTBEAT_TIMEOUT = 150        # seconds without heartbeat -> offline (device sends every 60 s)

PLATE_OPTIONS = ["plate_1", "plate_2", "plate_3"]

# Settings written with ATTR_SET_SERVICE and reported in the start ATTR_PUSH_EVENT.
SETTING_KEYS = {
    "volume", "soundSwitch", "closeDoorTime", "ringerInterval", "ringerDuration",
    "ringerMode", "doorStuckCurrent", "plateStuckCurrent", "doorCheckSignalTime",
    "doorNotcheckSignalTime", "temperatureCheckSwitch", "lightSwitch",
    "enableLight", "enableSound", "powerType", "powerMode",
}

SERVICE_SET_PLANS = "set_plans"
SERVICE_CLEAR_PLANS = "clear_plans"
SERVICE_FEED_NOW = "feed_now"
SERVICE_STOP = "stop_feeding"
SERVICE_SEND_COMMAND = "send_command"
