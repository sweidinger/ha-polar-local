# PETLIBRO Polar (local) for Home Assistant

Run the **PETLIBRO Polar wet food feeder (PLAF109)** completely without the Petlibro cloud.
The Polar connects to Home Assistant's own MQTT broker, and this integration plays the
part of the cloud: it answers time requests, confirms events, writes feeding plans and
exposes everything as Home Assistant entities.

* No cloud account needed after setup, no polling, instant updates (local push)
* Feeding plans written from Home Assistant – the Polar still does its own thaw rotation
* Lid, plate, bell, LED, volume, sound, close delay, ringer, IR timing
* Pet detection at the bowl (IR sensor), temperature, Wi-Fi signal, feeding steps, event codes
* Firmware updates can be triggered locally (see [docs/API.md](docs/API.md#firmware-update))

Tested with firmware **3.0.14** and **3.0.18** (hardware 5.2.0). The full protocol is
documented in **[docs/API.md](docs/API.md)**.

> ⚠️ Unofficial. Not affiliated with PETLIBRO. You redirect a device that feeds an animal –
> test everything while you are at home and keep the bowl empty during experiments.

## How it works

```
Polar ──MQTT 1883──► Mosquitto (Home Assistant app) ◄── this integration
          (DNS: mqtt.us.petlibro.com → Home Assistant)
```

The Polar talks plain, unencrypted MQTT on port 1883 to `mqtt.us.petlibro.com`. A local DNS
record makes that name point to your Home Assistant host. The Polar logs in with its own
per-device username/password, so the broker needs a login for exactly these credentials.

## Requirements

* Home Assistant with the **MQTT integration** and the **Mosquitto broker** app
  (any broker on port 1883 works)
* A router/DNS server where you can add a host record (UniFi, Pi-hole, AdGuard, OpenWrt, …)
* The Polar's serial number and MQTT credentials – captured once, see step 1
* The Polar must have been set up **once with the Petlibro app**: Wi-Fi, broker address and
  the per-device MQTT login are provisioned via Bluetooth during pairing. Afterwards the
  cloud is no longer needed – the configuration survives reboots and firmware updates
  (only a factory reset or a Wi-Fi change needs the app again).

## Setup

### 1. Capture the Polar's MQTT credentials (one time)

The credentials are only visible when the Polar connects. Use the small relay in
[`tools/mqtt_relay.py`](tools/mqtt_relay.py): it listens on 1883, forwards everything to the
real Petlibro broker and writes the login to `credentials.json`.

```bash
# on any Linux host/NAS in your LAN (Docker example)
docker run -d --name petlibro-relay -p 1883:1883 \
  -e UPSTREAM_HOST=<IP of mqtt.us.petlibro.com> \
  -v $PWD/tools/mqtt_relay.py:/relay.py:ro -v $PWD/data:/data \
  python:3-slim python -u /relay.py
```

* Resolve `mqtt.us.petlibro.com` **before** you add the DNS record and put the IP into
  `UPSTREAM_HOST` – otherwise the relay would connect to itself.
* Add a DNS host record `mqtt.us.petlibro.com → <relay host>` that applies to the Polar,
  then power-cycle the Polar. After a few seconds `data/credentials.json` contains
  `client_id` (= serial number), `username` and `password`. The app keeps working meanwhile.
* The relay drops firmware-update and plan commands from the cloud by default
  (`DROP_WORDS`), so nothing changes on the device while you capture. Set `DROP_WORDS=` to
  forward everything.
* Stop the relay afterwards. Keep `credentials.json` private.
* These are **device** credentials, not your Petlibro account. They are not available from
  the Petlibro web API (none of its known endpoints returns them), so capturing the
  connection is the only practical way today.

### 2. Add the Polar to Mosquitto

In the Mosquitto broker app → *Configuration* → *Logins* add the captured username and password:

```yaml
logins:
  - username: <username from credentials.json>
    password: <password from credentials.json>
```

Recommended: restrict the Polar to its own topics with an ACL. Enable
`customize: {active: true, folder: mosquitto}` in the app and create
`/share/mosquitto/acl.conf` with `acl_file /share/mosquitto/accesscontrollist` and
`/share/mosquitto/accesscontrollist`:

```
# every existing user needs its rules once an ACL is active!
user homeassistant
topic readwrite #

user <polar username>
topic readwrite dl/PLAF109/<SERIAL>/#
topic read dl/PLAF109/device/broadcast/#
```

Restart the Mosquitto app and check that your other MQTT devices still connect.

### 3. Install the integration

HACS → *Integrations* → ⋮ → *Custom repositories* → `https://github.com/sweidinger/ha-polar-local`
(category *Integration*) → install **PETLIBRO Polar (local)** → restart Home Assistant.

*Settings → Devices & services → Add integration → PETLIBRO Polar (local)* and enter the
serial number.

### 4. Point the Polar to Home Assistant

Change the DNS record to `mqtt.us.petlibro.com → <Home Assistant IP>` and power-cycle the
Polar (or wait – it reconnects on its own). Within a minute the device in Home Assistant is
*Connected*, shows the temperature and the firmware version.

Optional, once everything works:

* Block internet access for the Polar in your firewall. It falls back to public DNS servers
  (8.8.4.4) when your DNS server does not answer, and would then reach the cloud again.
  Allow it temporarily for firmware updates.
* Remove the Polar from the Petlibro app / disable the cloud integration.

Going back to the cloud: delete the DNS record and power-cycle the Polar.

## Entities

| Entity | Type | Notes |
|---|---|---|
| Lid | switch | on = open now for *Max. open duration* minutes, off = close |
| Lid open | binary sensor (door) | from the device's feeding steps |
| Pet at bowl | binary sensor (occupancy) | IR sensor, `NEAR`/`LEAVE` |
| Plate position | select | rotates the plate (refused while a pet is detected) |
| Bell | button | plays the meal sound |
| Indicator LED | light | |
| Next feeding | sensor (timestamp) | next plan written by this integration, all plans as attributes |
| Temperature | sensor | compartment temperature |
| Volume, Close delay, Ringer interval/duration, IR detection time | number (config) | written to the device |
| Max. open duration | number (config) | used by the Lid switch, stored in Home Assistant |
| Sound | switch (config) | |
| Wi-Fi signal, Firmware, Last step, Last event code, Ringer mode, anti-pinch currents, door check times, Update progress, Last seen, Connected, Temperature check | diagnostic | |

## Actions

| Action | What it does |
|---|---|
| `polar_local.set_plans` | Replaces all plans on the Polar. `plans`: list of `{plate, time, date?, duration?, need_thaw?}`; local time; without `date` the next occurrence is used |
| `polar_local.clear_plans` | Removes all plans |
| `polar_local.feed_now` | Opens now (`plate`, `duration` optional) |
| `polar_local.stop_feeding` | Closes the lid |
| `polar_local.send_command` | Raw JSON command for experiments (`topic`: service/config/ota/…) |

Example – plan the next three meals after refilling (one plate per meal, each plate
served once, so food never stays longer than 24 h):

```yaml
action: polar_local.set_plans
data:
  plans:
    - {plate: 1, time: "07:00", duration: 30}
    - {plate: 2, time: "12:30", duration: 30}
    - {plate: 3, time: "18:00", duration: 30}
```

The Polar rotates the plate to the front 30 minutes before each meal (cooling pause /
thaw), opens at the given time and keeps the lid open while the pet eats.

## Troubleshooting

* **Not connected:** check that `mqtt.us.petlibro.com` resolves to Home Assistant *for the
  Polar* and that the Mosquitto log shows `New client connected ... as <SERIAL>`.
  A `not authorised` means the login/ACL is wrong.
* **Plans run at the wrong time:** the time zone comes from Home Assistant's configuration;
  the device gets it on every reconnect.
* Enable debug logging:
  ```yaml
  logger:
    logs:
      custom_components.polar_local: debug
  ```

## Roadmap

* **Bluetooth provisioning from Home Assistant** – set up a new or reset Polar directly from
  the config flow (via a local Bluetooth adapter or ESPHome Bluetooth proxies): send Wi-Fi and
  a broker login generated by Home Assistant, pointing straight at Home Assistant. No Petlibro
  account, no credential capture, no DNS override. Firmware 3.0.18 contains a NimBLE GATT
  provisioning service (`seq`/`type` framed messages with `wifiSsid`, password, MQTT config and
  `user_id`, no app-level encryption found) plus AP-mode and SmartConfig fallbacks; the
  message format still has to be decoded.
* Cooling control: `coolSwitch` is accepted by 3.0.14 and 3.0.18 but has no effect (tested). Cooling always runs.

## Credits

Protocol work based on captures of a real device. Ideas from
[rgnv/haos-petlibro-local](https://github.com/rgnv/haos-petlibro-local) (MIT).
