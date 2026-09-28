# Upgrades and rebuild plans

I built this printer as a stock Voron 2.4r2 from a kit and have been slowly fixing the incorrect parts in the kit and improving performance and reliability.

I started with an Afterburner toolhead and cable chains, then moved to Stealthburner with a toolhead board and CAN bus. I later replaced Clockwork 2 with [Galileo2](https://github.com/JaredC01/Galileo2) while keeping Stealthburner.

The probe went from the original Omron inductive probe to [Unklicky](https://github.com/majarspeed/Unklicky), then Euclid, and finally the current LDC1612 eddy-current probe. There isn't a fuse on the 24 V feed to the toolhead. Failed stows and deploys with the magnetic probes got pretty spicy and dramatic.

I've done enough piecemeal upgrades. It's time to rebuild the frame and put the parts I've been collecting to use. This is the roadmap; the [hardware notes](../HARDWARE-NOTES.md) separate installed hardware, parts on hand, and the remaining selections.

## What I've already changed

| Modification | Why I changed it |
| --- | --- |
| Stealthburner with Galileo2 | I moved on from Clockwork 2, but I'm keeping the toolhead so I don't have to buy another board or fans |
| CAN-connected toolhead board | Part of moving away from the original cable-chain setup |
| High-temperature A/B steppers | Already fitted for the warmer chamber I'm working toward |
| Chamber sealing | I designed and fitted it because the basement is cold and drafty in winter |
| 70 W hotend heaters | I've been using these for a while |
| ASA-GF printed parts | Most of the remaining printed parts, including the Galileo2 parts |
| PC-CF toolhead parts | I've melted enough cooling ducts to want something that handles the heat better |
| 6 mm PC door with K3 hinges | The door uses K3 hinges; gdsolar's [K3-style Voron adaptation](https://github.com/gdsolar/Printer-Mods/tree/main/Voron/K3_Style_Door) is a reference for the hinge design, with a [6 mm panel in its parts list](https://github.com/gdsolar/Printer-Mods/blob/main/Voron/K3_Style_Door/Stuff_To_Buy.md) |
| ACM panel kit | Replaced all three stock ABS panels: rear, deck, and bottom electronics cover. The deck warped on the first bed heat-up |

## Frame and motion

The frame is badly skewed, and the Shake&Tune results aren't pretty. I'm rebuilding it square and considering pinning the corners. I like to print fast, so I want to address the mechanical problems before tuning around them.

| Part or change | Status | Notes |
| --- | --- | --- |
| CNC gantry components | Going into the rebuild | Tool-free XY tensioners, XY joints, and AB joints |
| CNC tool-free Z tensioners | Going into the rebuild | Metal tensioners with dial adjustment, separate from the Z drives |
| 400 mm MGN12H X rail | One on hand, not installed | I've had this waiting on the shelf for roughly one to two years |
| 400 mm MGN9H-1R rails | Two on hand, not installed | Bought separately from the X rail |
| Belts, pulleys, and idlers | On hand | Replacing these while the machine is apart |
| Motor shaft retainers | On hand | Going in with the motion-system work |
| G2ZXL | On hand | I want to address gantry droop. The [G2ZXL listing](https://kb-3d.com/store/ldo/1215-ldo-motors-galileo-2-z-drive-kit-g2zxl-for-v2-micron-pack-of-4-1719449861676.html) specifies 9:1 planetary reduction and increased static holding torque for larger V2 builds |
| Titanium backers | On hand | To reduce thermal bowing caused by the rails and extrusions expanding differently |

## Bed and chamber

I want a hotter, more consistent chamber for ABS and ASA, without winter drafts causing failures. I'm aiming closer to the materials' glass-transition temperatures. The operating temperature also depends on the ratings of the components and materials that remain in the chamber.

| Part or change | Status | Notes |
| --- | --- | --- |
| Blurolls three-point kinematic bed mount | Going into the rebuild | To let the bed expand without the mounts fighting it |
| [Monolith Bed Fans](https://github.com/Monolith3D/Monolith_Bed_Fans) | Reinstalling during the rebuild | This shroud uses four 5015 radial fans |
| Better chamber sealing | Improving the existing modifications | Reduce heat loss and drafts |
| Generic NTC frame thermistors | Not installed yet | I'll mount them to the Z extrusions |
| [Stealthmax V2](https://github.com/nevermore3d/Stealthmax_V2) with photocatalytic add-on | Planned | The project specifies carbon filtration, an H14 filter, a servo-controllable exhaust/recirculation vent, and an optional photocatalytic oxidation (PCO) stage |
| X/Y controller removal from the chamber | Part of this rebuild | I'll relocate it outside or remove it entirely. It isn't staying in the chamber |

The titanium backers reduce thermal bowing, the Blurolls bed mount lets the bed expand, and the frame sensors will let me track the Z-extrusion temperatures.

I'm replacing most of the printed chamber components with metal. The cooling duct, extruder parts, and Stealthburner cover will remain, along with parts needed for the cutter, bed fans, and purge system.

### Enclosure panels

The stock ABS deck panel, the chamber floor beneath the bed, warped the first time I heated the bed. I replaced all three ABS panels with the [ACM kit](https://kb-3d.com/store/frame-enclosure/546-acm-or-pc-panel-set-for-voron-v24-multiple-sizes.html): rear, deck, and bottom electronics cover. The door is PC and the side panels are acrylic.

## Hotend and toolhead

I'm replacing the original Dragon with a Dragon HF and ceramic heatbreak. It isn't installed yet. A big printer with a big nozzle needs more flow than the original hotend delivers at speed.

I'm keeping Stealthburner and Galileo2. The immediate repair is the failed FAN0 MOSFET (AO3400/A) on the FLY SB2040 Pro Max V3; I'm waiting for a replacement MOSFET.

## Filament handling

I have all the components for an enclosed [Box Turtle](https://github.com/ArmoredTurtle/BoxTurtle) with its [TurtleNeck buffer](https://github.com/ArmoredTurtle/BoxTurtle/tree/main/STLs/Base_Build/TurtleNeck).

I'm considering [FilamATrix for Galileo2](https://github.com/thunderkeys/FilamATrix/tree/main/STLs/galileo2_extruder) for the cutter, with the Dragon HF and Stealthburner.

I may use the TurtleNeck buffer for AFC's [buffer-based sensing](https://www.afcproject.dev/installation/buffer-ram-sensor.html) instead of separate toolhead filament sensors. That uses `pin_tool_start: buffer`, the TurtleNeck configuration, and a named buffer association.

For purge handling, I'm planning [Turtleblobifier](https://github.com/ImSundee/Turtleblobifier). It purges onto a tray, ejects the blob into a bucket, and brushes the nozzle.

## Lighting and controls

I'm replacing the old LED strips glued to a printed mount with [Daylight on a Stick XXL](https://github.com/VoronDesign/Voron-Hardware/blob/master/Daylight/Daylight_on_a_stick_XXL/README.md). The XXL design is intended for 350 mm printers and uses 30 white LEDs, specified at 4000 K and 90+ CRI.

I've selected a Pi TFT70 for KlipperScreen. The farther the printer gets from the computer, the more useful a touchscreen at the machine becomes. Reference: [Pi TFT70 V2.0 manual](https://raw.githubusercontent.com/bigtreetech/BIGTREETECH-TouchScreenHardware/master/BTT%20Pi%20TFT70%20V2.0%20Github/Hardware/BTT-Pi%20TFT70%20user%20manual.pdf).

## Software and testing

The rebuild needs new macros for heating, bed fans, filtration, filament changes, and purge handling.

I'll compare frame measurements, Shake&Tune results, and print results before and after the work. Wiring, sensor curves, mounting clearances, and calibration values will go into the build notes as I install the parts.

## Later ideas

I'd like to try a 48–60 V motion setup eventually, possibly as part of a larger drive-system change. That's a later spending decision, not something I'm waiting for before rebuilding. The X/Y controller leaves the chamber now either way.

I've also wanted cameras for a long time, but haven't fitted any yet.
