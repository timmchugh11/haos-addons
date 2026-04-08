# Van Power 3D

3D Home Assistant add-on and Lovelace card for displaying van power flows around a rotating van model.

This is a personal project and is experimental.

## Features

- 3D van scene served by the add-on on port `3050`
- Home Assistant sensor polling through the add-on API
- Lovelace custom card module: `custom:van-power-card`
- Same app-shell style as the existing `starlink_gui` project

## Default entities

The add-on ships with these defaults:

- `sensor.epever_pv_voltage`
- `sensor.epever_pv_current`
- `sensor.epever_pv_power`
- `sensor.epever_battery_voltage`
- `sensor.battery_current`
- `sensor.battery_wattage`
- `sensor.charger_hookup_voltage`
- `sensor.charger_hookup_current`
- `sensor.charger_hookup_power`
- `sensor.charger_alternator_voltage`
- `sensor.charger_alternator_current`
- `sensor.charger_alternator_power`
- `sensor.battery_percentage`

## Lovelace resource

Add the card module as a Lovelace resource, for example:

`http://HOME_ASSISTANT_HOST:3050/van-power-card.js`

Then use:

```yaml
type: custom:van-power-card
solar_voltage: sensor.epever_pv_voltage
solar_amp: sensor.epever_pv_current
solar_watt: sensor.epever_pv_power
battery_voltage: sensor.epever_battery_voltage
battery_amp: sensor.battery_current
battery_watt: sensor.battery_wattage
grid_voltage: sensor.charger_hookup_voltage
grid_amp: sensor.charger_hookup_current
grid_watt: sensor.charger_hookup_power
alternator_voltage: sensor.charger_alternator_voltage
alternator_amp: sensor.charger_alternator_current
alternator_watt: sensor.charger_alternator_power
battery_percent: sensor.battery_percentage
```
