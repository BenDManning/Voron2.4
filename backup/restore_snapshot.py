#!/usr/bin/env python3
"""Export config/ from a local recovery checkout into a NEW review directory.

This never writes to a running printer configuration or restarts any service.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess

from printer_snapshot import BackupError, git, safe_relative


def restore(repo, commit, destination):
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise BackupError('use a full reviewed commit ID')
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise BackupError('destination must not exist')
    files = {}
    for entry in git(repo, 'ls-tree', '-r', '-z', commit, '--', 'config/').split('\0'):
        if not entry:
            continue
        metadata, name = entry.split('\t', 1)
        mode, kind, oid = metadata.split()
        if mode not in {'100644', '100755'} or kind != 'blob':
            raise BackupError('recovery tree contains unsupported links or objects')
        relative = safe_relative(name).relative_to('config')
        files[relative] = git(repo, 'cat-file', 'blob', oid, raw=True)
    if not files:
        raise BackupError('commit contains no config files')
    os.umask(0o077)
    destination.mkdir(mode=0o700)
    for relative, content in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open('xb') as handle:
            handle.write(content)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, help='local Git checkout or bare repository')
    parser.add_argument('--commit', required=True, help='full reviewed commit object ID')
    parser.add_argument('--destination', required=True, help='new, nonexisting review directory')
    args = parser.parse_args()
    try:
        count = restore(args.repo, args.commit, args.destination)
        print('Exported %d configuration files for manual review; nothing deployed.' % count)
        return 0
    except (BackupError, OSError, ValueError, subprocess.SubprocessError):
        print('Recovery export failed; details suppressed. Do not use a partial export.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
