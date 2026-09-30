#!/usr/bin/env python3
"""One-way printer configuration snapshots. Python >= 3.9, Git, Linux."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


class BackupError(Exception):
    pass


def git(repo, *args, check=True, raw=False):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                            timeout=90, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if check and result.returncode:
        raise BackupError('git operation failed: ' + args[0])
    return result.stdout if raw else result.stdout.decode('utf-8', errors='replace').strip()


def excluded(name, config):
    import fnmatch
    import re
    path = Path(name)
    return (any(p.startswith('.') or p in {'logs', 'backups', '__pycache__'} for p in path.parts)
            or path.name.startswith(('id_', 'authorized_keys', 'known_hosts'))
            or path.suffix.lower() not in {'.cfg', '.conf'}
            or bool(re.search(r'(?:19|20)\d{2}[-_]?\d{2}[-_]?\d{2}', path.name))
            or any(fnmatch.fnmatchcase(name, pattern) for pattern in config.get('private_exclusions', [])))


def snapshot(config):
    first = collect(config)
    if first != collect(config):
        raise BackupError('source changed while copying; retry required')
    return first


def collect(config):
    source = Path(config['source']).resolve(strict=True)
    files = {}

    def read(name):
        relative = safe_relative(name)
        if excluded(name, config):
            raise BackupError('required root is excluded')
        path = source / relative
        resolved = path.resolve(strict=True)
        mapped = config.get('vendor_map', {}).get(name)
        if mapped and resolved != Path(mapped).absolute():
            raise BackupError('vendor mapping target changed')
        if not resolved.is_relative_to(source) and not mapped:
            raise BackupError('external symlink not approved')
        return path.read_bytes()

    def walk_error(error):
        raise BackupError('approved directory cannot be read')

    for name in config['roots']:
        files[name] = read(name)
    for name in config['directories']:
        directory = source / safe_relative(name)
        if directory.is_symlink():
            raise BackupError('directory symlinks not supported')
        if not directory.exists():
            continue
        for base, directories, names in os.walk(directory, followlinks=False, onerror=walk_error):
            for child in directories:
                if (Path(base) / child).is_symlink():
                    raise BackupError('directory symlinks not supported')
            directories[:] = [child for child in directories if not child.startswith('.') and child not in {'logs', 'backups', '__pycache__'}]
            for child in names:
                relative = (Path(base) / child).relative_to(source).as_posix()
                if not excluded(relative, config):
                    files[relative] = read(relative)
    validate_includes(files, source)
    if config.get('dependency_manifest'):
        data = Path(config['dependency_manifest']).read_bytes()
        json.loads(data)
        scan_content(data)
        files['_recovery/dependencies.json'] = data
    return files


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in name:
        raise BackupError('unsafe relative path')
    return path


def validate_includes(files, source):
    import glob
    import re
    for name, content in files.items():
        text = content.decode('utf-8')
        for match in re.finditer(r'^\s*\[include\s+([^\]]+)\]', text, re.M | re.I):
            include = match.group(1).strip()
            safe_relative(include)
            pattern = (Path(name).parent / include).as_posix()
            matches = [Path(p).relative_to(source).as_posix() for p in glob.glob(str(source / pattern))]
            if not matches or any(candidate not in files for candidate in matches):
                raise BackupError('required include missing or outside approved scope')


def sanitize(config, files):
    import re
    output = {}
    for name, content in files.items():
        if name == '_recovery/dependencies.json':
            continue
        section = ''
        lines = []
        dropping_continuation = False
        for line in content.decode('utf-8').splitlines(keepends=True):
            heading = re.match(r'^\s*\[([^\]]+)\]', line)
            if heading:
                section = heading.group(1).strip().lower()
                dropping_continuation = False
            field = re.match(r'^([A-Za-z_][\w.-]*)\s*([=:])\s*(.*)', line)
            if dropping_continuation and line[:1].isspace() and not heading:
                continue
            if field:
                dropping_continuation = False
                for rule in config.get('replacements', []):
                    if (rule['path'] == name and rule['section'].lower() == section
                            and rule['key'].lower() == field.group(1).lower()):
                        value = rule.get('value', 'REDACTED')
                        if '\n' in value or '\r' in value:
                            raise BackupError('replacement must be one line')
                        line = field.group(1) + field.group(2) + ' ' + value + '\n'
                        dropping_continuation = True
                        break
            lines.append(line)
        output[name] = ''.join(lines).encode('utf-8')
    return output


def scan_content(content):
    """Conservative heuristic gate, NOT proof of absence of all secrets."""
    import re
    text = content.decode('utf-8')
    sensitive = re.compile(r'(password|passwd|secret|token|api[_-]?key|access[_-]?key|credential|private[_-]?key)', re.I)
    section = ''
    protected = False
    for line in text.splitlines():
        if protected and line[:1].isspace() and line.strip() and not line.lstrip().startswith(('#', ';')):
            raise BackupError('public secret gate rejected continuation')
        heading = re.match(r'^\s*\[([^\]]+)\]', line)
        if heading:
            section = heading.group(1).lower()
            protected = False
        field = re.match(r'^\s*[#;]?\s*([\w.-]+)\s*[=:]\s*(.*)', line)
        if field:
            key, value = field.groups()
            field_protected = sensitive.search(key) or (key.lower() in {'url', 'body', 'user', 'username'} and section.startswith(('notifier', 'secrets')))
            if field_protected and value.strip() not in {'', 'REDACTED'}:
                raise BackupError('public secret gate rejected content')
            protected = field_protected or (protected and line.lstrip().startswith(('#', ';')))
    for key, value in re.findall(r'"([\w.-]+)"\s*:\s*"([^"]+)"', text):
        if sensitive.search(key) and value != 'REDACTED':
            raise BackupError('public secret gate rejected quoted field')
    import math
    from collections import Counter
    for token in re.findall(r'[A-Za-z0-9+/=_-]{32,}', text):
        entropy = -sum((count / len(token)) * math.log2(count / len(token)) for count in Counter(token).values())
        if entropy > 4.5 and any(c.isdigit() for c in token) and any(c.isupper() for c in token) and any(c.islower() for c in token):
            raise BackupError('public secret gate rejected high-entropy token')
    patterns = [r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
                r'(?i)\b(?:https?|ftp)://[^\s/@]+:[^\s/@]+@',
                r'(?i)\bBearer\s+[A-Za-z0-9_.+/=-]{8,}',
                r'\b(?:gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{15,}',
                r'\bAKIA[A-Z0-9]{16}\b', r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+']
    if any(re.search(pattern, text) for pattern in patterns):
        raise BackupError('public secret gate rejected content')


def publication_gate(repo, remote):
    # Existing public blobs (including photos) are not newly disclosed by us.
    published = set()
    if remote:
        for entry in git(repo, 'ls-tree', '-r', '-z', remote).split('\0'):
            if entry:
                published.add(entry.split('\t', 1)[0].split()[2])
    objects = set()
    for entry in git(repo, 'ls-files', '--stage', '-z').split('\0'):
        if entry:
            objects.add(entry.split('\t', 1)[0].split()[1])
    head = git(repo, 'rev-parse', '--verify', 'HEAD', check=False)
    commits = git(repo, 'rev-list', 'HEAD', *(['--not', remote] if remote else [])).splitlines() if head else []
    for commit in commits:
        for entry in git(repo, 'ls-tree', '-r', '-z', commit).split('\0'):
            if entry:
                mode, kind, oid = entry.split('\t', 1)[0].split()
                if kind != 'blob':
                    raise BackupError('unsupported public Git object')
                objects.add(oid)
    for oid in objects - published:
        scan_content(git(repo, 'cat-file', 'blob', oid, raw=True))


def verify_index(repo, files):
    staged = {}
    for entry in git(repo, 'ls-files', '--stage', '-z', '--', 'config/').split('\0'):
        if entry:
            metadata, path = entry.split('\t', 1)
            mode, oid, stage = metadata.split()
            if mode != '100644' or stage != '0':
                raise BackupError('unsupported staged configuration object')
            staged[path[len('config/'):]] = git(repo, 'cat-file', 'blob', oid, raw=True)
    if staged != files:
        raise BackupError('staged configuration differs from snapshot; check ignore rules or filters')


def ssh_command(settings):
    import shlex
    if not settings.get('ssh_key'):
        return None
    return ('ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes '
            '-o StrictHostKeyChecking=yes -o ConnectTimeout=15 -i ' + shlex.quote(settings['ssh_key'])
            + ' -o UserKnownHostsFile=' + shlex.quote(settings['known_hosts']))


def deliver(config, name, files):
    if name == 'public':
        for content in files.values():
            scan_content(content)
    settings = config['repositories'][name]
    repo = Path(config['state']) / name
    ssh = ssh_command(settings)
    options = ['-c', 'core.sshCommand=' + ssh] if ssh else []
    advertised = git(repo.parent, *options, 'ls-remote', settings['url'], 'refs/heads/' + settings['branch'])
    if not repo.exists():
        if advertised:
            git(repo.parent, *options, 'clone', '--branch', settings['branch'], settings['url'], str(repo))
        else:
            git(repo.parent, 'init', '--initial-branch=' + settings['branch'], str(repo))
            git(repo, 'remote', 'add', 'origin', settings['url'])
    for entry in git(repo, 'status', '--porcelain', '-z', '--untracked-files=all').split('\0'):
        if entry and not entry[3:].startswith('config/'):
            raise BackupError('unrelated checkout edits require manual review')
    if ssh:
        git(repo, 'config', 'core.sshCommand', ssh)
    remote = None
    if advertised:
        git(repo, 'fetch', 'origin', settings['branch'])
        local = git(repo, 'rev-parse', 'HEAD')
        remote = git(repo, 'rev-parse', 'FETCH_HEAD')
        base = git(repo, 'merge-base', local, remote)
        if base == local and local != remote:
            if git(repo, 'diff', '--name-only', local, remote, '--', 'config'):
                raise BackupError('remote managed config changed; manual review required')
            git(repo, 'merge', '--ff-only', remote)
        elif base != remote:
            raise BackupError('remote divergence; manual review required')
    elif read_status(repo.parent).get(name, {}).get('remote_head'):
        raise BackupError('previously published remote branch is missing')
    git(repo, 'config', 'user.name', 'Printer snapshot')
    git(repo, 'config', 'user.email', 'printer-backup@localhost')
    destination = repo / 'config'
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    for relative, content in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    git(repo, 'add', '-A', '--', 'config')
    verify_index(repo, files)
    if name == 'public':
        publication_gate(repo, remote)
    if git(repo, 'diff', '--cached', '--name-only'):
        git(repo, 'commit', '-m', name + ' printer snapshot')
    if name == 'public':
        publication_gate(repo, remote)
    expected = git(repo, 'rev-parse', 'HEAD')
    try:
        git(repo, 'push', 'origin', 'HEAD:refs/heads/' + settings['branch'])
    except (BackupError, OSError, subprocess.SubprocessError):
        pass  # A lost reply may follow a successful push: verify either way.
    advertised = git(repo, 'ls-remote', 'origin', 'refs/heads/' + settings['branch']).split()
    actual = advertised[0] if advertised else None
    if expected != actual:
        raise BackupError('remote HEAD verification failed')
    return {'remote_head': actual, 'last_success': time.time(), 'error': None}


def write_status(state, status):
    temporary = state / 'status.json.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump(status, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, state / 'status.json')


def read_status(state):
    path = state / 'status.json'
    return json.loads(path.read_text()) if path.exists() else {'paused': False}


def validate_config(config):
    import re
    source, state = Path(config['source']).resolve(), Path(config['state']).resolve()
    if state.is_relative_to(source) or source.is_relative_to(state):
        raise BackupError('source and state must be separate')
    urls = [config['repositories'][name]['url'] for name in ('private', 'public')]
    if urls[0] == urls[1]:
        raise BackupError('repositories must be independent')
    for url in urls:
        local = config.get('allow_local_remotes', False) and Path(url).is_absolute()
        if not local and not re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', url):
            raise BackupError('only scoped SSH remotes are supported')
    for settings in config['repositories'].values():
        key = settings.get('ssh_key')
        if not key and not config.get('allow_local_remotes', False):
            raise BackupError('a scoped SSH identity is required per repository')
        if key:
            path = Path(key).resolve(strict=True)
            if path.is_relative_to(source) or path.is_relative_to(state) or path.stat().st_mode & 0o077:
                raise BackupError('SSH identity must be private and outside source and state')
            Path(settings['known_hosts']).resolve(strict=True)


def cycle(config, command='now'):
    import fcntl
    validate_config(config)
    state = Path(config['state'])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    with open(state / 'cycle.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = read_status(state)
        now = time.time()
        if command == 'tick':
            status['watcher_alive_at'] = now
            if status.get('paused'):
                status['paused_seen_at'] = now
            write_status(state, status)
        if command == 'status':
            return status
        if command in {'pause', 'resume'}:
            status['paused'] = command == 'pause'
            status['control_at'] = time.time()
            write_status(state, status)
        if status.get('paused'):
            return status
        if command == 'tick':
            import hashlib
            try:
                files = snapshot(config)
                digest = hashlib.sha256()
                for path, content in sorted(files.items()):
                    digest.update(path.encode() + b'\0' + content + b'\0')
                fingerprint = digest.hexdigest()
                if fingerprint != status.get('observed_fingerprint'):
                    status.update(observed_fingerprint=fingerprint, quiet_since=now)
                    status['last_reconcile'] = 0
                write_status(state, status)
                if now - status['quiet_since'] < config.get('quiet_seconds', 60):
                    return status
            except (BackupError, OSError, ValueError):
                pass
            if now - status.get('last_reconcile', 0) < config.get('reconcile_seconds', 300):
                return status
        return cycle_locked(config)


def cycle_locked(config):
    state = Path(config['state'])
    status = read_status(state)
    status['last_reconcile'] = time.time()
    try:
        files = snapshot(config)
    except (BackupError, OSError, ValueError):
        for name in ('private', 'public'):
            previous = status.get(name, {})
            status[name] = {**previous, 'error': 'source snapshot rejected',
                            'last_attempt': time.time(), 'failure_since': previous.get('failure_since', time.time())}
        write_status(state, status)
        return status
    for name in ('private', 'public'):
        try:
            status[name] = deliver(config, name, sanitize(config, files) if name == 'public' else files)
        except (BackupError, OSError, ValueError, subprocess.SubprocessError) as error:
            previous = status.get(name, {})
            status[name] = {**previous, 'error': str(error) if isinstance(error, BackupError) else 'delivery failed',
                            'last_attempt': time.time(), 'failure_since': previous.get('failure_since', time.time())}
    write_status(state, status)
    return status


def watch(config):
    validate_config(config)
    metrics = None
    if config.get('metrics'):
        from snapshot_metrics import start_server
        settings = config['metrics']
        metrics = start_server(Path(config['state']) / 'status.json',
                               tuple(settings['bind']), settings['allowed_clients'])
    try:
        while True:
            try:
                cycle(config, 'tick')
            except BlockingIOError:
                pass
            time.sleep(config.get('poll_seconds', 5))
    finally:
        if metrics:
            server, thread = metrics
            server.shutdown()
            thread.join()
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('command', choices=['now', 'pause', 'resume', 'status', 'watch'])
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text())
        if args.command == 'watch':
            watch(config)
            return 0
        status = cycle(config, args.command)
        print(json.dumps(status))
        if args.command in {'pause', 'status'}:
            return 0
        return int(status.get('paused', False) or any(status.get(name, {}).get('error') for name in ('private', 'public')))
    except (BackupError, OSError, ValueError, subprocess.SubprocessError):
        print('backup failed (details suppressed to protect configuration)')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
