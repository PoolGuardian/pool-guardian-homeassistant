# Contributing

Thanks for looking. A few things that will save you time.

## This integration is read-only, permanently

There is no switch, button or service that controls the pump, and there will
not be one. The controller can drain a pool, and the read-only local API needs
no credential — which is exactly what makes setup a single step. Control lives
in the Pool Guardian mobile app and the authenticated local API.

The same decision applies to the device's MQTT integration. PRs adding a
control path will be closed.

## Local development

Symlink (or copy) `custom_components/pool_guardian` into your Home Assistant
config directory and restart:

```bash
ln -s "$(pwd)/custom_components/pool_guardian" /path/to/ha/config/custom_components/pool_guardian
```

Turn on debug logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.pool_guardian: debug
```

## Before opening a PR

```bash
ruff check custom_components
ruff format custom_components
```

CI also runs `hassfest` and the HACS validation action. Both check things that
are easy to get wrong by hand — manifest key order, required fields, the
zeroconf matcher schema, translation completeness.

## Adding an entity

Entities are table-driven. Add one row to `SENSORS` in `sensor.py` or
`BINARY_SENSORS` in `binary_sensor.py`, and one matching entry under
`entity.sensor` / `entity.binary_sensor` in `strings.json`. Copy `strings.json`
to `translations/en.json` — they are kept identical.

The `key` and the `translation_key` must match. Extractors receive the whole
merged coordinator payload (`live`, `status`, `info`, `last_run`) and must
return `None` rather than raising when data is absent — the payload is empty on
the first refresh and while the controller reboots.

Return `None` rather than a plausible-looking zero when a reading is not
trustworthy. Pump current is suppressed when `current_sensor_ok` is false and
water temperature is suppressed while a sensor is offline, because in both
cases a zero or a stale value is indistinguishable from a real reading — and
in this product a wrong reading is worse than a missing one.

## Firmware dependencies

Some fields need a minimum controller firmware. Note it in a comment next to
the entity and make the integration degrade to unknown on older firmware
rather than erroring. Current floors:

| Feature | Minimum firmware |
| --- | --- |
| Everything baseline | 1.0.320 |
| mDNS TXT auto-discovery, `last_run_end_reason` | 1.0.332 |
| Last-run fields surviving a controller reboot | 1.0.334 |
