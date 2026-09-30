#!/usr/bin/env python3
"""Restore printer configuration from a chosen private GitHub snapshot.

  restore_snapshot.py restore --config SETTINGS --commit FULL_COMMIT_HASH

Fetches outside live config, previews filenames, asks for confirmation, saves the
current config, then restores approved files. The same command handles existing
and newly created config directories. Uses settings.source as the destination.
Stop Klipper and Moonraker before applying. Backups stay paused afterward.
Use --repo LOCAL_REPOSITORY for offline recovery. No software installation or
hardware operations are performed. Legacy export-only CLI remains supported.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import hashlib
import json
import stat
import tempfile

from printer_snapshot import BackupError, safe_relative


def git(repo, *args, check=True, raw=False):
    """Isolate Git overrides; never expose remote URLs or stderr."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    result = subprocess.run(['git', '-C', str(repo), '-c', 'core.hooksPath=/dev/null', *args],
                            capture_output=True, timeout=90, env=env)
    if check and result.returncode:
        raise BackupError('Git read/fetch failed; verify reviewed commit and configured branch')
    return result.stdout if raw else result.stdout.decode('utf-8', errors='strict').strip()



def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def encode(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode()


def private_mkdir(path):
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise BackupError('private directory path is unsafe')
        return
    private_mkdir(path.parent)
    path.mkdir(mode=0o700)


def private_write(path, content):
    private_mkdir(path.parent)
    with path.open('xb') as handle:
        os.chmod(path, 0o600)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def inventory(root):
    """lstat inventory, including unrelated files; never follow symlinks."""
    result = {}
    def walk(path, name):
        info = path.lstat()
        record = {'mode': stat.S_IMODE(info.st_mode), 'mtime': info.st_mtime_ns,
                  'uid': info.st_uid, 'gid': info.st_gid}
        if stat.S_ISLNK(info.st_mode):
            record.update(kind='link', link=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            record['kind'] = 'dir'
        elif stat.S_ISREG(info.st_mode):
            record.update(kind='file', sha256=digest_bytes(path.read_bytes()))
        else:
            raise BackupError('target contains unsupported special files')
        result[name] = record
        if record['kind'] == 'dir':
            for child in sorted(path.iterdir()):
                walk(child, (name + '/' if name else '') + child.name)
    if root.exists() or root.is_symlink():
        walk(root, '')
    return result


def validate_snapshot(files, config, root):
    from printer_snapshot import validate_includes
    if not files.get('printer.cfg', b'').strip():
        raise BackupError('snapshot requires nonempty printer.cfg')
    if not set(config['roots']).issubset(files):
        raise BackupError('snapshot is missing required roots')
    for name, content in files.items():
        safe_relative(name)
        if name == '_recovery/dependencies.json':
            try:
                metadata = json.loads(content)
            except ValueError:
                raise BackupError('invalid dependency metadata') from None
            if not isinstance(metadata, dict):
                raise BackupError('invalid dependency metadata')
        elif not managed(name, config):
            raise BackupError('snapshot contains files outside approved scope')
    validate_includes({n: c for n, c in files.items() if managed(n, config)}, root)


def matching_vendor_link(name, target, config, files):
    path = target / name
    mapped = config.get('vendor_map', {}).get(name)
    return bool(mapped and name in config['roots'] and name in files
                and path.is_symlink() and path.resolve(strict=True) == Path(mapped).absolute()
                and path.read_bytes() == files[name])


def validate_target(target, baseline, config, files):
    import fnmatch
    preserved = {n for n, r in baseline.items() if r['kind'] != 'dir' and not managed(n, config)}
    for name, content in files.items():
        if not managed(name, config):
            continue
        for match in re.finditer(r'^\s*\[include\s+([^\]]+)\]', content.decode('utf-8'), re.M | re.I):
            pattern = (Path(name).parent / match.group(1).strip()).parts
            for extra in preserved:
                parts = Path(extra).parts
                if len(parts) == len(pattern) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pattern)):
                    raise BackupError('preserved unrelated file would expand snapshot include; reconcile manually')
    for name in set(files) | {n for n in baseline if managed(n, config)} | set(config['directories']):
        path = target / safe_relative(name)
        for component in [path, *path.parents]:
            if component.is_symlink():
                if component == path and matching_vendor_link(name, target, config, files):
                    continue
                raise BackupError('managed destination symlink differs or is unapproved; no vendor files changed')
        if path.exists() and name in files and not path.is_file():
            raise BackupError('managed file destination is not a regular file')
    for name, record in baseline.items():
        if record['kind'] == 'link' and any(name == d or name.startswith(d + '/') for d in config['directories']):
            raise BackupError('managed directory contains symlink; reconcile vendor links manually')


def validate_layout(config, bundle, target, mode):
    from printer_snapshot import excluded
    if mode not in {'rollback', 'rebuild'}:
        raise BackupError('choose rollback or rebuild mode')
    for key in ('roots', 'directories'):
        if not isinstance(config.get(key), list):
            raise BackupError('explicit managed roots and directories required')
        for name in config[key]:
            if safe_relative(name).as_posix() != name or any(p.startswith('.') for p in Path(name).parts):
                raise BackupError('unsafe managed scope')
    if 'printer.cfg' not in config['roots'] or any(excluded(n, config) for n in config['roots']):
        raise BackupError('required root scope invalid')
    if mode == 'rollback' and (target != Path(config['source']).absolute() or not target.is_dir()):
        raise BackupError('rollback requires existing configured source; use rebuild for explicit remapping')
    for path in (target, bundle, Path(config['state']).absolute()):
        if '..' in path.parts:
            raise BackupError('parent traversal in directory mapping refused')
        for component in (path, *path.parents):
            if component.is_symlink():
                raise BackupError('symlink directory paths are not supported')
    state = Path(config['state']).absolute()
    for left, right in ((target, bundle), (target, state), (bundle, state)):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise BackupError('target, bundle and watcher state must be separate')
    if target.exists() and not target.is_dir():
        raise BackupError('target must be a directory')


def prepare(config, commit, bundle, target, mode, repo=None):
    """Prepare an isolated local review; returned digest is apply confirmation."""
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise BackupError('use a full reviewed commit ID')
    bundle, target = Path(bundle).absolute(), Path(target).absolute()
    validate_layout(config, bundle, target, mode)
    if bundle.exists() or bundle.is_symlink():
        raise BackupError('review bundle must not exist')
    settings = config['repositories']['private']
    branch = settings['branch']
    options = ['-c', 'core.hooksPath=/dev/null', '-c', 'fetch.fsckObjects=true']
    if repo is not None:
        source = str(Path(repo).resolve(strict=True))
    else:
        from printer_snapshot import ssh_command
        source = settings['url']
        if not re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source):
            raise BackupError('private recovery requires scoped SSH remote')
        if not settings.get('ssh_key') or not settings.get('known_hosts'):
            raise BackupError('private recovery requires scoped key and pinned host keys')
        key = Path(settings['ssh_key']).resolve(strict=True)
        if key.stat().st_mode & 0o077 or not key.is_file():
            raise BackupError('SSH identity must be a private file')
        if not Path(settings['known_hosts']).is_file():
            raise BackupError('pinned host keys file missing')
        options += ['-c', 'core.sshCommand=' + ssh_command(settings)]
    with tempfile.TemporaryDirectory() as temporary:
        bare = Path(temporary) / 'source.git'
        git(Path(temporary), 'init', '--bare', '--template=', str(bare))
        git(bare, 'check-ref-format', 'refs/heads/' + branch)
        git(bare, *options, 'fetch', '--no-tags', '--no-recurse-submodules', source,
            '+refs/heads/' + branch + ':refs/heads/review')
        if git(bare, 'merge-base', commit, 'refs/heads/review') != commit:
            raise BackupError('commit is not reachable from configured branch')
        files = Path(temporary) / 'files'
        restore(bare, commit, files)
        baseline = inventory(target)
        contents = {p.relative_to(files).as_posix(): p.read_bytes()
                    for p in files.rglob('*') if p.is_file()}
        validate_snapshot(contents, config, files)
        validate_target(target, baseline, config, contents)
        bundle.mkdir(mode=0o700)
        payload = {}
        for path in sorted(files.rglob('*')):
            if path.is_file():
                name = path.relative_to(files).as_posix()
                content = path.read_bytes()
                payload[name] = digest_bytes(content)
                private_write(bundle / 'files' / name, content)
        manifest = {'version': 1, 'commit': commit, 'target': str(target), 'mode': mode,
                    'state': str(Path(config['state']).absolute()),
                    'baseline': baseline, 'files': payload,
                    'preserved_links': [n for n in contents if matching_vendor_link(n, target, config, contents)],
                    'scope': {
                        key: config.get(key, []) for key in ('roots', 'directories', 'private_exclusions')}}
        data = encode(manifest)
        private_write(bundle / 'manifest.json', data)
        return digest_bytes(data)


def managed(name, scope):
    from printer_snapshot import excluded
    return (not excluded(name, scope) and (name in scope['roots'] or any(
        name.startswith(directory + '/') for directory in scope['directories'])))


def services_stopped():
    """No network probe: both installed services must be explicitly stopped."""
    for service in ('klipper.service', 'moonraker.service'):
        result = subprocess.run(['systemctl', 'show', service, '--no-pager',
                                 '--property=LoadState,ActiveState,SubState'],
                                capture_output=True, text=True, timeout=15)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode or values != {'LoadState': 'loaded', 'ActiveState': 'inactive', 'SubState': 'dead'}:
            raise BackupError('klipper and moonraker must both be stopped; unknown state refused')


def load_bundle(bundle, confirmation=None):
    bundle = Path(bundle).absolute()
    entries = inventory(bundle)
    if not entries or any(r['kind'] == 'link' or r['mode'] & 0o077 for r in entries.values()):
        raise BackupError('bundle must contain private regular files and directories, no symlinks')
    raw = (bundle / 'manifest.json').read_bytes()
    digest = digest_bytes(raw)
    if confirmation is not None and digest != confirmation:
        raise BackupError('confirmation does not match review manifest')
    manifest = json.loads(raw)
    if manifest.get('version') != 1:
        raise BackupError('unsupported review manifest')
    contents = {}
    for name, expected in manifest['files'].items():
        contents[name] = (bundle / 'files' / safe_relative(name)).read_bytes()
        if digest_bytes(contents[name]) != expected:
            raise BackupError('review payload changed; prepare again')
    actual = {n[6:] for n, r in entries.items() if n.startswith('files/') and r['kind'] == 'file'}
    if actual != set(contents):
        raise BackupError('unexpected review payload files')
    validate_snapshot(contents, manifest['scope'], bundle / 'files')
    return manifest, contents, digest


def atomic_write(path, content):
    private_mkdir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.restore-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_transition(before, after, changed):
    """Only changed path and its ancestor directory mtimes may differ."""
    ancestors = {p.as_posix() if p.as_posix() != '.' else '' for p in Path(changed).parents}
    for name in set(before) | set(after):
        if name == changed:
            continue
        old, new = before.get(name), after.get(name)
        if name in ancestors:
            if new is None or new['kind'] != 'dir':
                raise BackupError('concurrent directory change detected')
            if old is None:
                continue
            old = {k: v for k, v in old.items() if k != 'mtime'}
            new = {k: v for k, v in new.items() if k != 'mtime'}
        if old != new:
            raise BackupError('concurrent target modification detected')


def apply(config, bundle, confirmation, guard=None):
    """Apply a reviewed bundle. guard is a test seam, never a CLI option."""
    import fcntl
    import tarfile
    from printer_snapshot import read_status, write_status
    bundle = Path(bundle).absolute()
    manifest, contents, _ = load_bundle(bundle, confirmation)
    target = Path(manifest['target'])
    validate_layout(config, bundle, target, manifest['mode'])
    if manifest['scope'] != {key: config.get(key, []) for key in ('roots', 'directories', 'private_exclusions')}:
        raise BackupError('managed scope changed; prepare again')
    validate_target(target, manifest['baseline'], config, contents)
    if inventory(target) != manifest['baseline']:
        raise BackupError('target changed since preparation; prepare again')
    state = Path(config['state']).absolute()
    if str(state) != manifest['state']:
        raise BackupError('watcher state mapping changed; prepare again')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    with (state / 'cycle.lock').open('a') as lock:
        os.chmod(state / 'cycle.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = read_status(state)
        status['paused'] = True
        write_status(state, status)
        archive = bundle / 'before.tar'
        with archive.open('xb') as handle:
            os.chmod(archive, 0o600)
            with tarfile.open(fileobj=handle, mode='w', dereference=False) as saved:
                if target.exists():
                    saved.add(target, arcname='target', recursive=True)
            handle.flush()
            os.fsync(handle.fileno())
        (guard or services_stopped)()
        if inventory(target) != manifest['baseline']:
            raise BackupError('target changed before write; prepare again')
        validate_target(target, manifest['baseline'], config, contents)
        private_write(bundle / 'apply-started.json', encode({'manifest': confirmation}))
        try:
            expected = manifest['baseline']
            deletions = [n for n, r in expected.items() if r['kind'] == 'file'
                         and managed(n, manifest['scope']) and n not in contents]
            writes = sorted((n for n in contents if managed(n, manifest['scope'])
                             and not matching_vendor_link(n, target, config, contents)),
                            key=lambda n: (n == 'printer.cfg', n))
            for name in deletions + writes:
                if inventory(target) != expected:
                    raise BackupError('concurrent modification before write')
                if name in deletions:
                    (target / name).unlink()
                else:
                    atomic_write(target / name, contents[name])
                after = inventory(target)
                verify_transition(expected, after, name)
                if name in deletions:
                    if name in after:
                        raise BackupError('deletion verification failed')
                elif after.get(name, {}).get('sha256') != digest_bytes(contents[name]):
                    raise BackupError('write verification failed')
                expected = after
            after = inventory(target)
            if after != expected:
                raise BackupError('post-write target drift')
            validate_target(target, after, config, contents)
            for name, content in contents.items():
                if matching_vendor_link(name, target, config, contents):
                    continue
                if managed(name, manifest['scope']) and after.get(name, {}).get('sha256') != digest_bytes(content):
                    raise BackupError('post-write verification failed')
            for name, record in manifest['baseline'].items():
                if record['kind'] != 'dir' and not managed(name, manifest['scope']) and after.get(name) != record:
                    raise BackupError('unrelated state changed during apply')
            private_write(bundle / 'applied.json', encode({'manifest': confirmation, 'after': after}))
        except (OSError, BackupError):
            raise BackupError('apply incomplete; protected before.tar and manifest.json in bundle support manual recovery; keep services stopped and backup paused') from None
        return archive


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


def preview(bundle):
    manifest, contents, digest = load_bundle(bundle)
    rows = []
    for name in sorted(set(contents) | set(manifest['baseline'])):
        if name in contents and not managed(name, manifest['scope']):
            status = 'metadata-only'
        elif managed(name, manifest['scope']):
            before = manifest['baseline'].get(name, {})
            if name not in contents:
                if before.get('kind') != 'file':
                    continue
                status = 'delete'
            else:
                status = ('unchanged-link' if name in manifest.get('preserved_links', [])
                          else 'unchanged' if before.get('sha256') == manifest['files'][name]
                          else 'replace' if before else 'add')
        else:
            continue
        rows.append({'path': name, 'status': status})
    return {'mode': manifest['mode'], 'target': manifest['target'], 'commit': manifest['commit'],
            'confirmation': digest, 'paths': rows,
            'warning': 'Review private bundle files securely. No content diffs printed. Services and backup remain stopped/paused after apply.'}


def main():
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='offline export only; no apply safety guarantees')
    export.add_argument('--repo', required=True)
    export.add_argument('--commit', required=True)
    export.add_argument('--destination', required=True)
    restore_parser = commands.add_parser('restore', help='preview and confirm a configuration restore')
    restore_parser.add_argument('--config', required=True)
    restore_parser.add_argument('--repo', help='local repository for offline recovery')
    restore_parser.add_argument('--commit', required=True, help='full chosen snapshot commit hash')
    argv = sys.argv[1:]
    if argv and argv[0] == '--repo':
        argv = ['export', *argv]  # Original export CLI remains supported.
    args = parser.parse_args(argv)
    try:
        if args.command == 'export':
            count = restore(args.repo, args.commit, args.destination)
            print('Exported %d configuration files for manual review; nothing deployed.' % count)
        else:
            import uuid
            config = json.loads(Path(args.config).read_text())
            target = Path(config['source']).absolute()
            bundle = Path(config['state']).absolute().parent / ('config-restore-' + uuid.uuid4().hex)
            private_mkdir(bundle.parent)
            digest = prepare(config, args.commit, bundle, target,
                             'rollback' if target.exists() else 'rebuild', args.repo)
            print('Snapshot:', args.commit)
            print('Config directory:', target)
            print('Review and backup directory:', bundle)
            for row in preview(bundle)['paths']:
                if row['status'] != 'metadata-only':
                    print(row['status'] + ': ' + json.dumps(row['path']))
            try:
                confirmed = input('Restore these configuration files? Type yes to continue: ').strip().lower() == 'yes'
            except (EOFError, KeyboardInterrupt):
                confirmed = False
            if not confirmed:
                print('Cancelled. Configuration unchanged.')
                return 0
            archive = apply(config, bundle, digest)
            print('Configuration restored. Previous config copy:', archive)
            print('Backups remain paused. Check the files, restart services, then resume backups when ready.')
        return 0
    except BackupError as error:
        print('Recovery refused: ' + str(error))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Recovery failed; details suppressed. Keep services stopped and backup paused. If apply began, retain bundle/before.tar and manifest.json for manual recovery; do not trust partial output.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
