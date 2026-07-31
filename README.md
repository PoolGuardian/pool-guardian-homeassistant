# Pool Guardian for Home Assistant

[![Validate](https://github.com/PoolGuardian/pool-guardian-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/PoolGuardian/pool-guardian-homeassistant/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

Local, read-only Home Assistant integration for the Pool Guardian pool freeze-protection
controller. No cloud account, no MQTT broker, no credentials.

## What it does

Polls the controller over your LAN and exposes its state as Home Assistant entities:

- **Pool** — pump running, water detected at the high and low sensors, controller state,
  auto/manual mode, active alert count
- **Freeze protection** — enabled, protection active, freeze warning, pump lockout, and the
  four user-set thresholds
- **Water sensors** — per-sensor water detection, water temperature, link state and firmware
  version for both the HIGH and LOW probes
- **Pump current** — instantaneous, average, and per-run min/max
- **Last pump run** — duration, why it ended, average current, auto vs manual, and when it
  finished
- **Diagnostics** — Wi-Fi signal, uptime, IP, controller firmware, cloud link status
  (most disabled by default; enable them from the device page if you want them)

## What it deliberately does not do

**There is no way to control the pump from this integration.** No switch, no service, no
button. That is intentional, not an oversight — this controller can drain a pool, and a
read-only local API needs no credential, which is what makes setup a single step. Pump
control lives in the Pool Guardian mobile app and the authenticated local API.

If you need HA to *act* on pool state, use these entities as triggers and drive whatever
you like — just not the pump.

## Requirements

- Home Assistant 2025.2 or newer (the integration uses the current
  `helpers.service_info.zeroconf` import path rather than the deprecated one)
- A Pool Guardian controller on the same network as Home Assistant
- Controller firmware 1.0.320 or newer. **1.0.332 or newer** is recommended: it adds the
  mDNS records that make auto-discovery work regardless of device name, and the
  "last run end reason" field. Older firmware works, minus those two things.

## Installation

### HACS (recommended)

1. HACS → ⋮ → Custom repositories
2. Repository: `https://github.com/PoolGuardian/pool-guardian-homeassistant`, type **Integration**
3. Install **Pool Guardian**, then restart Home Assistant

### Manual

Copy `custom_components/pool_guardian` into your Home Assistant `config/custom_components/`
directory and restart.

## Setup

Controllers are found automatically — look for a discovered **Pool Guardian** card under
Settings → Devices & Services.

On firmware 1.0.332 and newer this works whatever the controller is called, because it
advertises a `device_type=pool_monitor` mDNS TXT record. On older firmware discovery falls
back to matching the mDNS name, so it only finds controllers still using their factory name
(`PoolGuardian-xxxxxx`).

To add one manually: **Add Integration → Pool Guardian**, then enter the controller's IP
address or `.local` hostname. The controller's own web page shows its IP, and so does the
mobile app under device settings.

> Renaming a controller after setup is always fine — the integration keys off the MAC
> address, not the name.

## Options

**Polling interval** (default 10 s, range 5–300 s). Configure → Options on the integration.

Lower is not automatically better: the controller is simultaneously running an RS232 sensor
loop, a cloud WebSocket and its own web server on a single ESP32. Pool state changes over
minutes, so 10 s loses nothing that matters.

## Notes

- Water temperature is reported as *unknown* while a sensor is offline rather than holding
  the last packet's value, which would otherwise look live forever.
- Pump current is *unknown* when the current sensor reports unhealthy. A zero would be
  indistinguishable from a real "pump drawing nothing", which is itself a fault.
- Temperatures come from the water probes' own thermistors, not the controller's air sensor.

## Relationship to the MQTT integration

The controller can also publish to an MQTT broker with Home Assistant discovery, exposing a
near-identical entity set. Use whichever suits you — MQTT if you already run a broker and
want push updates, this integration if you would rather not run one. Running both works but
gives you two copies of every entity.

## Support

Issues with **this integration** → [GitHub issues](https://github.com/PoolGuardian/pool-guardian-homeassistant/issues).

Anything about the **device, mobile app, subscription or your account** →
support@pool-guardian.net. Nobody watching this repository can help with those.

## License

MIT — see [LICENSE](LICENSE).
