# Configuration snapshots and recovery

Years ago I used `autocommit.sh` to back up the printer configuration to a private GitHub repo. I stopped using it, and later made that old repo public as an archive. I'm using the same basic idea again: edit the configuration on the printer and keep a Git history I can recover from.

## The repositories

- [Voron2.4](https://github.com/BenDManning/Voron2.4) is the current public project: hardware notes, rebuild plans, and the home for the snapshot scripts and sanitized configuration.
- A separate private repository holds recovery files and settings that aren't published here. It has its own Git history.
- [Voron2.4r2.old](https://github.com/BenDManning/Voron2.4r2.old) is the archived earlier setup and the inspiration for this replacement. I leave it unchanged. Its configuration and old credentials are not current examples to reuse.

## Setup status

The watcher is installed on the printer. The first public and private snapshots have been read back from GitHub and compared with the source files. A private snapshot has also been exported into a separate directory and checked byte for byte. Existing monitoring checks the watcher and both backup timestamps, with failure and recovery notifications through ntfy.

## How it works

The printer stays the source of the configuration. I edit through Mainsail, Fluidd or SSH. GitHub does not deploy changes back to it.

The watcher polls file contents every five seconds and groups changes after a 60-second quiet period, including ordinary editor saves and calibration written by `SAVE_CONFIG`. Directory rules cover files under `hardware/`, `macros/`, `addons/` and other approved paths, rather than requiring a new entry for every macro. Required includes must be accounted for; a missing or excluded dependency blocks the snapshot.

Each snapshot gets separate private and public copies outside the live configuration directory. The private copy keeps the approved printer recovery material. The public copy goes under `config/` in this repo after private files are excluded, known sensitive settings are scrubbed, and the result is checked for secrets. `.gitignore` helps exclude files, but cannot remove a password inside an otherwise publishable config. Unrecognized suspicious content blocks the public upload.

The scripts leave the hardware notes and other documentation alone. They do not pull into the live configuration, restart firmware, or run printer commands. No GitHub Actions, AI services or cron jobs are involved. A systemd user service keeps the watcher running, with lingering enabled so it does not depend on an SSH session staying open.

The script has `pause`, `resume`, `now` and `status` commands. `now` refuses to publish while paused; `resume` immediately reconciles changes. It retries every five minutes even if no further files change. A successful check with nothing new to upload updates status without adding an empty commit. Public and private delivery have separate success timestamps.

See [installation and commands](../backup/INSTALL.md) for settings, service setup and recovery instructions. The built-in secret scanner is a useful check, not a guarantee that an arbitrary file is safe to publish. Known sensitive settings need explicit replacement rules; new integrations need review.

## What recovery needs

A configuration snapshot is not an image of the printer's operating system. Recovery also needs the right Kalico version, plugin and vendor-file dependencies, and compatible MCU firmware. The public copy deliberately omits private settings, so it cannot replace the private recovery copy.

The private dependency manifest records software Git revisions and vendor symlink targets. The snapshot stores the Mainsail vendor config as a regular file, so the recovery export does not depend on a working symlink. The original vendor license is preserved in this repository.

Restoring into a separate directory comes first; replacing live configuration or restarting the printer is a deliberate manual step. A snapshot records saved files, not a promise that every experiment in it has been tested on the hardware. The recovery check does not test MCU flashing or a full operating-system rebuild.
