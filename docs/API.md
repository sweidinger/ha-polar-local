# PETLIBRO Polar (PLAF109) – MQTT protocol

Reverse engineered from

* **3.0.14** – full captures of the Petlibro cloud talking to a real device (hardware 5.2.0), and
* **3.0.18** – the same captures after the update, plus the strings in the OTA image
  (`PLAF109_OTA_030018.bin`, ESP-IDF v4.4.6, ESP32-C3, built 21 Sep 2026, not encrypted).

Column **3.0.14 / 3.0.18** in the tables:
✅ seen on the wire / tested, 🔎 only present in the firmware image (untested),
❌ accepted but without effect, – not present.
Firmware 3.0.14 was never available as a file, so “🔎 only in 3.0.18” means *not observed
with 3.0.14* – it may or may not exist there.

## Transport

| | |
|---|---|
| Broker | `mqtt.us.petlibro.com:1883`, **plain MQTT 3.1.1, no TLS** (EU accounts may use another host) |
| Client id | serial number (e.g. `AF05XXXXXXXXXXXXQ`) |
| Login | per-device username + password (sent in clear text in CONNECT) |
| Keep-alive | 60 s |
| Subscriptions | `dl/PLAF109/<SN>/device/+/sub`, `dl/PLAF109/device/broadcast/sub` |

The broker address is stored in the device (NVS, list with backup addresses, scheme `mqtt://`
or `mqtts://`). There is no hard-coded Petlibro host in 3.0.18, so a DNS override for
`mqtt.us.petlibro.com` is enough to move the device to another broker.
`DEVICE_CONFIG_SYNC` (below) rewrites the stored address.

### Topics

`dl/PLAF109/<SN>/device/<kind>/post` = device → cloud, `.../<kind>/sub` = cloud → device.

| kind | used for |
|---|---|
| `heart` | `HEARTBEAT` every 60 s |
| `ntp` | time request / answer |
| `event` | events (feeding steps, pet detection, attribute pushes, start) |
| `service` | commands and their replies |
| `config` | replies to `ATTR_SET_SERVICE` / `DEVICE_CONFIG_SYNC` |
| `ota` | firmware update command, progress, result |
| `system`, `broadcast` | present in 3.0.18, not observed |

### Rules a local “cloud” must follow

1. **NTP:** answer every `ntp/post` (see below). Without it the device has no time and plans
   do not run. **Never** send `code: 2030` – 3.0.18 unbinds itself on that code
   (and stops cooling, see [Binding](#binding)).
2. **Event echo:** confirm `DEVICE_START_EVENT`, `ATTR_PUSH_EVENT`, `GET_FEEDING_PLAN_EVENT`
   and `WET_GRAIN_OUTPUT_EVENT` on `event/sub` with
   `{"cmd": <same>, "ts", "msgId": <same>, "code": 0, "linkId": <new>}`.
   For `WET_GRAIN_OUTPUT_EVENT` drop `msgId` and add `execStep`.
3. **Never answer** `service/post`, `config/post`, `heart/post` – the device would execute
   the echo again.
4. After `DEVICE_START_EVENT` the cloud sends `ATTR_SET_SERVICE {"irSensorIdenTimeout": 2}`
   and `GET_SOME_ATTR_SERVICE`.

Every command carries `cmd`, `ts` (epoch ms), `msgId` and `linkId` (random 32-hex strings).
The device replies on `service/post` (or `config/post`) with the same `msgId` and `code: 0`.

## Device → cloud

| cmd | topic | content | 3.0.14 | 3.0.18 |
|---|---|---|---|---|
| `HEARTBEAT` | heart | `rssi`, `wifiType`, `count`, `temperature` (°C, compartment NTC) | ✅ | ✅ |
| `NTP` | ntp | `ts` (device clock), `msgId` | ✅ | ✅ |
| `DEVICE_START_EVENT` | event | `pid`, `mac`, `hardwareVersion`, `softwareVersion` | ✅ | ✅ |
| `ATTR_PUSH_EVENT` | event | full settings after start (see [Settings](#settings)); later only changed keys, e.g. `platePosition` + `foodGratingSwitch`, `lightSwitch` + `lightAgingType`, or empty `{}` as receipt of an `ATTR_SET_SERVICE` | ✅ | ✅ |
| `ATTR_PUSH_EVENT` | service | reply to `GET_SOME_ATTR_SERVICE`: `zeroState` (`PROCESSING` → `SUCCESS` = plate homing done) | ✅ | ✅ |
| `WET_GRAIN_OUTPUT_EVENT` | event | `planId`, `plate`, `execStep`, `finished`, `execTime` | ✅ | ✅ |
| `WET_GRAIN_MULTI_EVENT` | event | `eventCode` (+ `planId`, `plate`), see [Event codes](#event-codes) | ✅ | ✅ |
| `PET_DETECT_EVENT` | event | `type`: `NEAR` / `LEAVE` (IR sensor at the bowl, ~5 s resolution) | ✅ | ✅ |
| `DIAG_LOG_REPORT_EVENT` | event | Wi-Fi/MQTT diagnostics (`TYPE`, `STG`, `ERR`, …) | ✅ | ✅ |
| `OTA_UPGRADE` | ota | receipt `code: 0` | – | ✅ |
| `OTA_PROGRESS` | ota | `progress` 0–100 (about 2.5 min for 1.5 MB) | ✅* | ✅ |
| `OTA_INFORM` | ota | `state: 1` = image written, rebooting | ✅* | ✅ |
| `DEVICE_CANNOT_ROTATE_EVENT` | event | plate blocked | – | 🔎 |
| `DEVICE_RESUME_EVENT`, `SNOWFLAKE_ERROR_EVENT`, `WIFI_MESH_EVENT` | event | – | – | 🔎 |

\* sent by 3.0.14 while it installed 3.0.18.

### Feeding steps (`execStep`)

| step | meaning |
|---|---|
| `GRAIN_THAW` | 30 min before a plan: cooling pauses for the plate, the plate is rotated to the front |
| `GRAIN_START` | plan time reached |
| `OPEN_DOOR` | lid open (≈ 4 s after `GRAIN_START`) |
| `CLOSE_DOOR` | lid closed |
| `GRAIN_END` | plan finished (`finished: true`) |

### Event codes

| code | meaning (observed) |
|---|---|
| 1008 | plan ended but a pet is at the bowl – closing postponed |
| 1009 | postponed plan finished after the pet left |
| 1011 | lid closed (“door close clear”, always together with 1022) |
| 1022 | feeding cycle cleared |
| 1027 | `DOOR_STUCK_CLOSE_DOOR_WITH_PLAN_FEED` (3.0.18 strings) |

## Cloud → device

| cmd | topic | fields | 3.0.14 | 3.0.18 |
|---|---|---|---|---|
| `NTP` | ntp | `code: 0`, `calibrationTag: true`, `timezoneOffsetSeconds`, `nextDSTOffsetSeconds`, `nextDSTTransitionTs`, `secondNextDSTOffsetSeconds`, `secondNextDSTTransitionTs`, `timezone` (hours) | ✅ | ✅ |
| `WET_GRAIN_FEEDING_PLAN_SERVICE` | service | `plans: [...]`, see [Plans](#plans). The app first sends `plans: []` (clears everything), then the full list | ✅ | ✅ |
| `WET_FOOD_FEED_STOP_SERVICE` | service | `planId` of the running plan – closes the lid | ✅ | ✅ |
| `WET_FOOD_FEED_NOW_SERVICE` | service | immediate feed (`planId`, `feedingDuration`, `needThaw`) | – | 🔎 |
| `SET_PLATE_POS_SERVICE` | service | `platePosition` 1–3 (refused while a pet is detected) | ✅ | ✅ |
| `DEVICE_FUNCTION_TEST_SERVICE` | service | `action: "AUDIO"` – plays the bell (only `AUDIO` supported) | ✅ | ✅ |
| `ATTR_SET_SERVICE` | service | any of the [settings](#settings) | ✅ | ✅ |
| `GET_SOME_ATTR_SERVICE` | service | `attrKeys` – in practice only answers `zeroState` | ✅ | ✅ |
| `DEVICE_CONFIG_SYNC` | service | `mqttAddr: [{host, port}]`, `httpsAddr` – rewrites the stored broker list | ✅ | ✅ |
| `OTA_UPGRADE` | **ota** | `url` (https), `upgradeType: 1`, `targetSoftwareVersion`, `md5`, `sha256` (base64), `signatureType: 1` | ✅ | ✅ |
| `DEVICE_RESUME_SERVICE` | service | clears an error state (anti-pinch, door/plate motor stuck, cooling abnormal, power off > 8 h) | – | 🔎 |
| `WIFI_CHANGE_SERVICE`, `WIFI_RECONNECT_SERVICE` | service | – | – | 🔎 |

### Plans

```json
{"planId": 70123456, "executionTime": "06:00", "executionDay": "2026-10-31",
 "plate": 1, "feedingDuration": 30}
```

* `executionTime` / `executionDay`: **UTC**. A plan runs once.
* `feedingDuration`: minutes the lid stays open. If a pet is at the bowl at the end, the lid
  stays open until it leaves (event 1008) and closes `closeDoorTime` seconds later.
* `feedNowState: true` (with `planId` 666666666 in the app) opens immediately.
* Optional in 3.0.18 🔎: `needThaw` (bool, rotate/thaw 30 min before), `enableAudio`,
  `audioTimes`, `optCode` (`PLATE_POSTPONE` keeps the plate state).
* The device answers with `plans: [{"planId", "syncTime": 0}]`.

### Settings

Reported in the `ATTR_PUSH_EVENT` after start, written with `ATTR_SET_SERVICE`.
Toggles with a time window (`*AgingType`, `*StartTimeUtc`, `*EndTimeUtc`, `*Times`) use
`AgingType: 1` = always.

| key | values / unit | 3.0.14 | 3.0.18 | note |
|---|---|---|---|---|
| `lightSwitch` (+`lightAgingType`) | bool | ✅ | ✅ | indicator LED |
| `soundSwitch` (+`soundAgingType`) | bool | ✅ | ✅ | |
| `volume` | 0–100 | ✅ | ✅ | |
| `closeDoorTime` | s | ✅ | ✅ | lid closes this long after the pet left (verified: 30 → 32 s) |
| `irSensorIdenTimeout` | s | ✅ | ✅ | sent by the cloud after every start (2) |
| `ringerMode` | `SMART` | ✅ | ✅ | smart ringer stops when a pet is detected |
| `ringerInterval`, `ringerDuration` | min | ✅ | ✅ | |
| `temperatureCheckSwitch` | bool | ✅ | ✅ | |
| `doorCheckSignalTime`, `doorNotcheckSignalTime` | s | ✅ | ✅ | |
| `doorStuckCurrent`, `plateStuckCurrent` | mA (400) | ✅ | ✅ | **anti-pinch thresholds – do not change** |
| `coolSwitch` (+`coolAgingType`, `coolStartTimeUtc`, `coolEndTimeUtc`, `coolTimes`) | bool | ❌ | ❌ | accepted (`code: 0`) but without effect on both versions (temperature and cooling rotation unchanged for 45–90 min); not reported back |
| `enableLight`, `enableSound`, `powerType`, `powerMode`, `electricQuantity`, `wifiSsid` | read-only | ✅ | ✅ | `electricQuantity` = AA battery level (meaningless without batteries) |

## Behaviour worth knowing

* **Cooling runs permanently** (Peltier, ~7–8 K below room temperature, verified overnight
  without plans). It pauses only for the plate being thawed.
* **Rotation while cooling:** the plates are rotated one position about every 30 min
  (“cooling timeout rotation”), paused during thaw/feeding and while plans are pending.
  3.0.18 fixes an occasional *continuous* rotation.
* **Binding:** the device stores whether it is bound to an account. Unbound (reset key long
  press, `UNBIND`, or NTP reply `code: 2030`) → it stops cooling and blinks white.
  It also stops cooling on battery power.
* **Plans live on the device** (NVS) and run without any broker connection.

## Firmware update

The cloud sends `OTA_UPGRADE` on `.../device/ota/sub`. The device downloads the image itself
(needs internet), reports `OTA_PROGRESS`, `OTA_INFORM {"state": 1}`, reboots and reconnects
with the new `softwareVersion`. Only the ESP image header/hash is validated
(no signature check found in 3.0.18; secure boot via eFuse not verified).

Known images:

| version | url | md5 |
|---|---|---|
| 3.0.18 | `https://oss.us.petlibro.com/dlcloud/platform/device_package/PLAF109/030018.bin/2026-09-24/03:01:07/PLAF109_OTA_030018.bin` | `e99a8419a94ddb510ff316ec3de3f1b2` |
