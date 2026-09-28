# Voron 2.4

I built this printer from a Voron 2.4r2 kit and have been correcting problems with the BOM and making improvements to the original design ever since. That includes the K3-style door, ACM panels, and the move to Stealthburner with Galileo2. This repo covers those changes, along with choices like sintered diamond nozzles and G10 flex plates, and the next round of work: G2ZXL drives, new rails, titanium backers, and a full frame rebuild.

The frame is badly skewed, and the Shake&Tune plots aren't pretty. I like to print fast, so getting the frame square comes first. I'm considering pinning the corners while it's apart.

## Where it stands

I'm running Stealthburner with a Galileo2 extruder, CAN-connected electronics, and eddy-current probing. The FAN0 MOSFET (AO3400/A) on the toolhead board failed when I removed the Stealthburner cover with the power still on (oops), so I'm waiting for a replacement MOSFET.

| Component | Current setup |
| --- | --- |
| Printer | Voron 2.4r2, 350 mm |
| Mainboard | Octopus v1.1 F446, USB-to-CAN bridge |
| X/Y controller | PITB v2, TMC5160 drivers |
| Toolhead board | FLY SB2040 Pro Max V3, TMC2240 extruder driver |
| Extruder | Galileo2 |
| Z | Four TMC2209-driven motors |
| Probe | LDC1612 eddy-current probe |
| Nozzle | 0.6 mm |

## The rebuild

I've collected new rails, G2ZXL drives, titanium backers, and replacement belts, pulleys, idlers, and shaft retainers. I'm replacing the printed gantry components with metal parts and moving to a three-point kinematic bed mount.

The printer lives in a basement that gets cold and drafty in winter. I've already designed and fitted chamber sealing; the rebuild adds better sealing and temperature sensing for the Z extrusions. The X/Y controller is leaving the chamber, whether I relocate it or remove it entirely.

I also have all the components for an enclosed Box Turtle MMU. That brings filament cutting, purge handling, and a new set of macros into the rebuild.

- [Hardware notes](HARDWARE-NOTES.md)
- [Upgrade history and rebuild plans](docs/upgrades.md)

## License

The documentation in this repository is by [BenDManning](https://github.com/BenDManning) and licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
