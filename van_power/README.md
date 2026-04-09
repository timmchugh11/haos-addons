# Van Power

Standalone HACS-compatible Home Assistant custom card that renders the 3D van power model directly in Lovelace.

This project is extracted from the `van_model` add-on card implementation, but it does not depend on the add-on UI or ingress. The card reads Home Assistant entity states directly from Lovelace and renders the 3D scene entirely inside the custom card.

## Features

- Standalone `custom:van-power-card` Lovelace card
- 3D van model rendered directly in the card
- Reads Home Assistant sensor state from the current Lovelace session
- No add-on ingress dependency

## Installation

### HACS

1. Add this repository as a custom HACS repository of type `Dashboard`.
2. Install `Van Power`.
3. Add the Lovelace resource:

```yaml
url: /hacsfiles/van_power/van-power-card.js
type: module
```

### Manual

Copy the contents of this folder into your Home Assistant `www` directory, then add:

```yaml
url: /local/van_power/van-power-card.js
type: module
```

## Example Card

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

## Default Entities

If a field is omitted, the card falls back to these defaults:

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
