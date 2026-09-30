# Installing and using the snapshot scripts

The watcher is installed on the printer. Public and private uploads have been
read back from GitHub, and a private recovery export has been checked byte for byte.
The printer is authoritative. These scripts never pull into its configuration,
restart firmware, or restore over an existing directory.

## Prerequisites and setup

- Linux, Python 3.9+ standard library, Git 2.28+, OpenSSH client.
- Run as the printer configuration owner, not root.
- Two independent repositories and repository-scoped write deploy keys. Verify
  private visibility externally before using the private recovery destination.
- Pin the SSH host key in a reviewed known_hosts file. The script uses
  `StrictHostKeyChecking=yes`, `IdentitiesOnly=yes`, and disables SSH config files.
- Put deploy keys, known_hosts and settings outside source and state directories.
  Keys must not be group/world accessible. Protect settings with mode 600.
- Copy `printer_snapshot.py`, `restore_snapshot.py` and `snapshot_metrics.py` to
  `~/.local/lib/printer-git-backup/`. Install the executable `printer-backup`
  launcher in `~/.local/bin/`. Copy `config.example.json` to
  `~/.config/printer-git-backup/settings.json`, mode 600, and review every field.
  Example destinations are placeholders; keep actual private details unpublished.
- `roots` is an explicit list of required reviewed root cfg/conf files. Missing
  roots fail closed. `directories` recursively selects new cfg/conf files.
  Both public and private destinations manage **only `config/`**.
- `vendor_map` maps a source-relative file to its exact final resolved absolute
  target. Vendor symlink chains are materialized as independent regular files.
  Directory symlinks and other external file symlinks are refused.
- `private_exclusions` applies to both copies. Required includes cannot bypass it.
  Built-in exclusions reject dot paths, logs/backups directories, non-cfg/conf
  files, dated filenames, and common SSH authentication filenames.
- `replacements` affects public copies only, matching exact path/section/key.
  Section and key matches are case-insensitive. Use `REDACTED` for secrets.
  The replacement examples are illustrative, not a review of a live printer.
- Optional `dependency_manifest`: an absolute path to reviewed, UTF-8 JSON.
  It is scanned, included at private `config/_recovery/dependencies.json`, and
  omitted publicly. It is not collected automatically from the host.

```sh
~/.local/bin/printer-backup now
~/.local/bin/printer-backup pause
~/.local/bin/printer-backup status
~/.local/bin/printer-backup resume
```

`now` bypasses debounce but **refuses publication while paused**. `resume` clears
persistent pause and immediately reconciles. `pause` and `status` exit zero if
successful; failed delivery or a paused `now` exits nonzero. A busy whole-cycle
lock exits nonzero: retry the operator command after the current cycle finishes.
`status` prints JSON; it does not refresh remote-success timestamps.

Install `printer-git-backup.service` as a **user service**, after paths/settings
are reviewed. Run `systemctl --user daemon-reload` and
`systemctl --user enable --now printer-git-backup.service`. An administrator
can enable boot/logout persistence with `loginctl enable-linger USER`.
Lingering is enabled on this printer; no reboot was performed as a test.

The service runs `watch`, an ordinary **polling/content watcher**, not inotify.
Defaults: poll every 5 seconds, require 60 seconds of quiet after changes, and
reconcile/retry every 300 seconds even if source bytes are unchanged. There is
no timer, cron job, AI dependency, or hosted workflow.

## Status and safety boundaries

State/checkouts live below the configured mode-700 state root. `status.json` is
atomically replaced with mode 600. `public` and `private` each expose `error`,
`last_success`, and `remote_head` after successful remote verification. Failures
retain the previous success timestamp and record `last_attempt`/`failure_since`.
`watcher_alive_at`, `paused_seen_at`, and `last_reconcile` are **not** evidence of
successful remote delivery. The existing monitoring system checks the last
successful backup and watcher heartbeat, then sends failures and recoveries
through ntfy. The backup scripts themselves do not hold ntfy credentials.

An optional `metrics` setting starts a read-only listener in the watcher process:

```json
"metrics": {
  "bind": ["127.0.0.1", 9178],
  "allowed_clients": ["127.0.0.1"]
}
```

For a separate monitoring host, use the printer's LAN bind address and allow only
the monitor's actual source IP. Do not expose it to the internet. Only
`GET /metrics` is served; other clients receive 403. The output contains fixed
public/private success timestamps, failure flags, pause state and liveness,
not configuration, repository addresses, commit IDs or error details. A deliberate
pause suppresses stale-backup alerts without changing success timestamps.
Stopped services and stalled watcher heartbeats remain independently detectable.

The process compares two content snapshots before delivery. This detects ordinary
concurrent edits, but is not an atomic filesystem snapshot or proof that saved
configuration was loaded successfully. The source and private state are trusted
local filesystems: this is not a security boundary against a hostile local user
racing filesystem operations or modifying checkout Git configuration/hooks.

Remote documentation-only fast-forwards are accepted; changed remote config or
true divergence stops delivery. Pending local commits are retained, never reset
or force-pushed. Failed pushes are retried without requiring a new source edit.
Every push, including an ambiguous failure response, is checked against remote
HEAD. Unrelated staged/working edits stop publication. A fresh private repository
can be empty. Existing destination checkouts are not automatically migrated when
settings change: stop the service and review them manually.

The built-in scanner checks newly publishable staged blobs and pending public
commit history, including now-deleted content. It rejects recognized
sensitive fields, selected token formats, credential URLs, PEM private keys,
multiline sensitive continuations, quoted JSON sensitive fields and suspicious
high-entropy tokens. This is **heuristic**, not perfect secret detection. It can
miss low-entropy secrets with unrecognized names, encodings and novel formats;
it can flag harmless content. Newly published blobs must be UTF-8; already-public
blobs, including photos, are preserved without decoding them as configuration.
No external gitleaks integration is included.
There is no automatic history rewrite or bypass for flagged pending history.
Review exact public output and all pending commits before initial deployment.

Include validation handles `[include path-or-glob]` sections in selected files.
It rejects absolute paths, `..`, missing matches and any wildcard match omitted
from the snapshot. It does not implement arbitrary runtime/Jinja include logic.
Excluded required files need a reviewed configuration change before backup can
succeed; there is no recovery-exception bypass. Only saved cfg/conf files and an
optional dependency manifest are covered—not firmware, databases, packages,
credentials outside reviewed config, or a full OS image.

## Manual recovery export (tested with disposable bare repositories)

Clone the separate private recovery repository using your unpublished settings.
Review its commit history and choose a **full commit object ID**, then run:

```sh
python3 backup/restore_snapshot.py --repo /path/to/local/recovery-checkout \
  --commit FULL_REVIEWED_COMMIT_ID --destination /path/to/NEW-review-directory
```

The destination must not exist. The command exports the chosen `config/` tree as
regular owner-readable files, rejects Git symlinks/submodules, and leaves live
printer files untouched. Inspect and compare the export before any separately
planned manual restoration. A failed export may leave a partial review directory;
do not use it as a complete recovery. Public exports contain placeholders and
are not equivalent to the private originals.

## Tests

```sh
cd backup
python3 -B -m unittest -v test_snapshot test_metrics
```

Tests create and remove disposable local bare Git remotes beneath `backup/`.
No printer, GitHub repository or real authentication material is used. Tests run
real Git commits/pushes **only in those disposable repositories**. Filesystem
race and ambiguous-acknowledgement tests inject deterministic timing failures
around real filesystem/Git operations. Run as a non-root user for permission tests.
Live checks also covered real uploads, remote read-back, recovery export,
pause/resume, independent detection of a stopped watcher, and authenticated
ntfy firing/recovery receipts. The printer firmware was not restarted.
