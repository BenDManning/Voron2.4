# Hardware notes

I started with a stock 350 mm Voron 2.4r2 kit. These notes cover the installed hardware and planned changes. I haven't added the configuration files to this repo yet.

## Installed hardware

| Component | Setup |
| --- | --- |
| Printer | Voron 2.4r2, 350 mm, CoreXY |
| Mainboard | Octopus v1.1 F446, USB-to-CAN bridge |
| X/Y controller | PITB v2 |
| X/Y drivers | TMC5160 |
| A/B motors | High-temperature steppers |
| Toolhead | Stealthburner |
| Toolhead board | FLY SB2040 Pro Max V3 |
| Extruder | Galileo2, with a TMC2240 driver |
| Z drive | Four motors with TMC2209 drivers |
| Hotend | Original Dragon with bimetal heatbreak |
| Hotend heater | 70 W |
| Nozzle and filament | 0.6 mm nozzle, 1.75 mm filament |
| Probe | LDC1612 eddy-current probe |
| Door | 6 mm PC with K3 hinges |
| Rear, deck (chamber floor), and bottom (electronics cover) panels | ACM replacement kit; all three installed |
| Side panels | Acrylic |

## Changes I've already made

The original probe was an Omron inductive probe. I replaced it with Unklicky, then Euclid, and finally the current LDC1612 eddy-current probe.

I also moved from cable chains to a CAN-connected toolhead board. On the extrusion side, I moved to Stealthburner with Clockwork 2 and later replaced CW2 with Galileo2. I'm keeping Stealthburner because I don't want to buy another board or set of fans right now.

The stock ABS deck panel, the chamber floor beneath the bed, warped the first time I heated the bed. I replaced all three ABS panels with the ACM kit: rear, deck, and bottom electronics cover.

I designed and fitted chamber seals to deal with the cold, drafty basement. Most of the remaining printed parts are ASA-GF. I use PC-CF for the toolhead parts, including the cooling duct, because I've melted too many ducts. The ASA-GF Galileo2 parts have held up at an 80 °C chamber temperature.

## Parts on hand

- One Honeybadger 400 mm MGN12H X rail and two Berserker 400 mm MGN9H-1R rails, still uninstalled.
- G2ZXL, titanium backers, new belts, pulleys, idlers, and motor shaft retainers.
- All components for an enclosed Box Turtle with its [TurtleNeck buffer](https://github.com/ArmoredTurtle/BoxTurtle/tree/main/STLs/Base_Build/TurtleNeck), not yet installed.

## Other rebuild work and selected parts

- CNC tool-free Z tensioners, tool-free XY tensioners, XY joints, and AB joints.
- Blurolls three-point kinematic bed mount.
- Dragon HF with a ceramic heatbreak, not installed yet.
- Generic NTC thermistors to mount to the Z extrusions, not installed yet.
- Reinstall Monolith Bed Fans and improve the chamber sealing.
- Stealthmax V2 with the photocatalytic add-on.
- [FilamATrix for Galileo2](https://github.com/thunderkeys/FilamATrix/tree/main/STLs/galileo2_extruder) as the cutter option I'm considering, plus [Turtleblobifier](https://github.com/ImSundee/Turtleblobifier) for purge handling.
- Daylight on a Stick XXL and a Pi TFT70 for KlipperScreen.

The X/Y controller is leaving the chamber during this rebuild. I'll either relocate it outside or remove it entirely.

The [upgrade roadmap](docs/upgrades.md) has the project links and reasons for the changes.

## Toolhead board repair

I damaged the FAN0 MOSFET, AO3400/A, on the toolhead fan board during an attempted board swap with power still connected. Replacement components are ordered; the repair is pending. Lesson learned: fully disconnect power before swapping boards.

The [repair photo and build history](docs/build-history.md#toolhead-fan0-mosfet) document the damage, along with earlier failures and the electronics-bay wiring progression.
