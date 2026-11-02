# Is the cooling controllable? — static analysis of firmware 3.0.18

**Question:** The firmware accepts `coolSwitch` (and `coolAgingType`, `coolStartTimeUtc`,
`coolEndTimeUtc`, `coolTimes`) in `ATTR_SET_SERVICE`, but sending `coolSwitch:false` had no
measurable effect on the real device (compartment temperature flat at ~13 °C for 45–90 min,
plate rotation continued). This note explains why, from the firmware itself.

**Method:** The OTA image `PLAF109_OTA_030018.bin` is an unencrypted ESP-IDF app for the
ESP32-C3 (RISC-V). Segments were disassembled with Capstone (RV32-IMC) and pointer loads
(`lui`/`auipc` + `addi`/load/store) were resolved to recover which code references which
string and RAM address. Addresses below are from this image and are informational.

## What the cooling controller actually checks

The decision to run the Peltier is made by a controller in the `0x42015xxx–0x42017xxx`
region. Its start routine (`start_cooling`, prologue at `0x42016af2`) does, in order:

1. **Battery check** — if running on battery it logs *"Battery power, not start cooling"* and
   returns without enabling (string `0x3c1243b4`, logged at `0x42016b5a`).
2. **State check** — global cooling state at `0x3fc9a7d8` (`2` = cooling active); if already
   active it does nothing.
3. Otherwise it sets the state and starts the Peltier, logging *"Cooling start event"*
   (`0x420101fa`).

The periodic controller (around `0x42016dee`) additionally:

- stops cooling on battery (*"Battery power detected, stopping cooling"*, `0x42016e7a`), and
- gates **starting** on a one-byte **cooling-enable flag** at `0x3fc9a810`
  (`cool_info` struct base `0x3fc9a800`, offset `0x10`), read at `0x42016e00`, `0x42017120`,
  `0x4201717c`.

## Who writes the enable flag

The flag at `0x3fc9a810` is written at exactly four sites, **all inside the cooling module**:

| site | write | meaning |
|---|---|---|
| `0x42015820` | `sb a5,0x10(..)` | set from the thaw/period logic |
| `0x420159b8` | `sw zero,0x10(..)` | zeroed in a struct reset |
| `0x42015c9e` | `sb zero,0x10(..)` | cleared (disable) |
| `0x42015d5c` | `sb 1,0x10(..)` | set to 1 by the 24-hour "cooling-abnormal" state machine |

None of these are in the settings path.

## Where `coolSwitch` goes instead

`coolSwitch` is parsed in the `ATTR_SET_SERVICE` handler (`0x4201a730`, key string
`0x3c12513c`): the boolean is read and stored into the settings struct (`sb a0,0x1fc(sp)` at
`0x4201a744`), then the struct is handed to the settings/NVS apply function. That value is
persisted, but **no read of it occurs anywhere in the cooling controller** — the enable flag
it would need to touch has only the four internal writers above.

## Conclusion

On both 3.0.14 and 3.0.18 the cooling is autonomous: **always on while bound and on mains
power**, pausing only per-plate during the 30-minute thaw before a feeding. `coolSwitch` and
the `cool*` time-window fields are parsed and stored but not wired to the controller, so they
cannot turn cooling off or schedule it over MQTT. They are most likely reserved for a feature
PETLIBRO has not enabled. If a later firmware wires them up, re-running the test
(`send_command` with `{"cmd":"ATTR_SET_SERVICE","coolSwitch":false,"coolAgingType":1}` and
watching the temperature) will show it, and the switch can be added back to the integration.
