# Voron 2.4

I built this printer from a Voron 2.4r2 kit and have been correcting problems with the BOM and making improvements to the original design ever since. That includes the K3-style door, ACM panels, and the move to Stealthburner with Galileo2. This repo covers those changes, along with choices like sintered diamond nozzles and G10 flex plates, and the next round of work: G2ZXL drives, new rails, titanium backers, and a full frame rebuild.

The frame is badly skewed, and the Shake&Tune plots aren't pretty. I like to print fast, so getting the frame square comes first. I'm considering pinning the corners while it's apart.

## Repository status

This is an ongoing build and rebuild log. It includes [configuration snapshots](config/), hardware notes, upgrade plans, and a [photo log of the wiring progression and repairs](docs/build-history.md).

## Where it stands

I'm running Stealthburner with a Galileo2 extruder, CAN-connected electronics, and eddy-current probing. I damaged the FAN0 MOSFET (AO3400/A) during an attempted board swap with power still connected (oops). Replacement components are ordered; the repair is pending.

![Current Stealthburner toolhead inside the printer](docs/images/current-stealthburner-toolhead.jpg)

*Current toolhead ahead of the rebuild.*

![Current electronics bay with sleeved harnesses and DIN-rail terminal blocks](docs/images/electronics-03-current.jpg)

*Current electronics bay, September 2026. The [photo log](docs/build-history.md) shows the earlier wiring and repair history.*

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
- [Build photos, wiring progression, and repairs](docs/build-history.md)

## Configuration snapshots

I used to back up the printer configuration to a private GitHub repo with an `autocommit.sh` script. That repo is now public and archived as [Voron2.4r2.old](https://github.com/BenDManning/Voron2.4r2.old). It records an earlier version of the printer, not the setup I'm running today.

I use that approach again with a public copy for sharing and a separate private recovery repo for settings that shouldn't be published. The old script is the starting point for the idea; the replacement keeps Git operations away from the live configuration and checks the public copy before uploading it.

The [snapshot scripts](backup/) run on the printer after config edits settle. [Configuration snapshots and recovery](docs/backups.md) explains how they work and how I recover an earlier version.

## License

The documentation in this repository is by [BenDManning](https://github.com/BenDManning) and licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The vendor copy of `config/mainsail.cfg` comes from [mainsail-config](https://github.com/mainsail-crew/mainsail-config) and retains its [GPL-3.0 license](licenses/mainsail-config-GPL-3.0.txt).
