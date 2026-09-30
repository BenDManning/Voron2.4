import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'printer_snapshot.py'


def git(where, *args, check=True):
    p = subprocess.run(['git', '-C', str(where), *args], capture_output=True, text=True)
    if check and p.returncode:
        raise AssertionError(p.stderr)
    return p.stdout.strip()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=HERE, prefix='.test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'printer.cfg').write_text('[printer]\nkinematics: corexy\n')
        self.remotes = {}
        for name in ('private', 'public'):
            bare = self.root / (name + '.git')
            subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(bare)], check=True, capture_output=True)
            seed = self.root / (name + '-seed')
            subprocess.run(['git', 'clone', str(bare), str(seed)], check=True, capture_output=True)
            git(seed, 'config', 'user.email', 'test@example.invalid')
            git(seed, 'config', 'user.name', 'Test')
            (seed / 'README.md').write_text('Important documentation\n')
            git(seed, 'add', 'README.md')
            git(seed, 'commit', '-m', 'Initial documentation')
            git(seed, 'push', 'origin', 'main')
            self.remotes[name] = bare
        self.config = {'source': str(self.source), 'state': str(self.root / 'state'),
                       'roots': ['printer.cfg'], 'directories': ['hardware', 'macros', 'addons', 'machine'],
                       'private_exclusions': [], 'replacements': [], 'vendor_map': {},
                       'allow_local_remotes': True,
                       'repositories': {k: {'url': str(v), 'branch': 'main'} for k, v in self.remotes.items()}}
        self.config_path = self.root / 'settings.json'

    def run_cli(self, command='now'):
        self.config_path.write_text(json.dumps(self.config))
        return subprocess.run(['python3', str(SCRIPT), '--config', str(self.config_path), command],
                              capture_output=True, text=True)

    def load_module(self):
        spec = importlib.util.spec_from_file_location('printer_snapshot', SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def status(self):
        return json.loads((Path(self.config['state']) / 'status.json').read_text())

    def test_short_command_uses_private_settings_under_home(self):
        home = self.root / 'home'
        (home / '.local/lib').mkdir(parents=True)
        (home / '.local/lib/printer-git-backup').symlink_to(HERE)
        settings = home / '.config/printer-git-backup/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(self.config))
        result = subprocess.run(['sh', str(HERE / 'printer-backup'), 'status'],
                                env={**os.environ, 'HOME': str(home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['paused'])

    def test_watch_metrics_lifecycle(self):
        from unittest.mock import patch
        import snapshot_metrics
        mod = self.load_module()
        self.config['metrics'] = {'bind': ['127.0.0.1', 0], 'allowed_clients': ['127.0.0.1']}
        started = []
        real = snapshot_metrics.start_server
        def start(*args):
            result = real(*args)
            started.append(result)
            return result
        with patch.object(snapshot_metrics, 'start_server', side_effect=start), patch.object(mod, 'cycle'), patch.object(mod.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                mod.watch(self.config)
        self.assertEqual(len(started), 1)
        self.assertFalse(started[0][1].is_alive())
        self.assertEqual(started[0][0].socket.fileno(), -1)

    def test_existing_remote_photos_do_not_block_configuration_backup(self):
        seed = self.root / 'public-seed'
        (seed / 'photo.jpg').write_bytes(b'\xff\xd8\xff\xe0test-image\xff\xd9')
        git(seed, 'add', 'photo.jpg')
        git(seed, 'commit', '-m', 'Existing public photo')
        git(seed, 'push', 'origin', 'main')
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout)
        blob = subprocess.check_output(['git', '-C', str(self.remotes['public']), 'show', 'main:photo.jpg'])
        self.assertEqual(blob, b'\xff\xd8\xff\xe0test-image\xff\xd9')

    def test_scope_recursion_excludes_bulk_credentials_and_private_patterns(self):
        for name in ['macros/new/deep.cfg', 'macros/.git/config', 'macros/id_ed25519',
                     'macros/export.zip', 'macros/run.log', 'macros/printer-20260929_154116.cfg',
                     'macros/secrets.conf', 'unreviewed.cfg']:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('[test]\nvalue: 1\n')
        self.config['private_exclusions'] = ['macros/secrets.conf']
        files = self.load_module().snapshot(self.config)
        self.assertEqual(set(files), {'printer.cfg', 'macros/new/deep.cfg'})

    def test_required_includes_fail_closed_for_missing_excluded_or_outside_scope(self):
        mod = self.load_module()
        for include in ['missing.cfg', 'macros/hidden.cfg', '../outside.cfg', '/etc/passwd']:
            (self.source / 'printer.cfg').write_text('[include ' + include + ']\n')
            with self.subTest(include=include):
                with self.assertRaises(mod.BackupError):
                    mod.snapshot(self.config)
        (self.source / 'macros').mkdir()
        (self.source / 'macros' / 'hidden.cfg').write_text('[gcode_macro X]\ngcode: G28\n')
        self.config['private_exclusions'] = ['macros/hidden.cfg']
        (self.source / 'printer.cfg').write_text('[include macros/*.cfg]\n')
        with self.assertRaises(mod.BackupError):
            mod.snapshot(self.config)
        self.config['private_exclusions'] = []
        self.assertIn('macros/hidden.cfg', mod.snapshot(self.config))

    def test_external_links_require_exact_vendor_mapping_and_copy_bytes(self):
        vendor = self.root / 'vendor.cfg'
        vendor.write_text('[gcode_macro VENDOR]\ngcode: G28\n')
        (self.source / 'mainsail.cfg').symlink_to(vendor)
        self.config['roots'].append('mainsail.cfg')
        mod = self.load_module()
        with self.assertRaises(mod.BackupError):
            mod.snapshot(self.config)
        self.config['vendor_map'] = {'mainsail.cfg': str(vendor)}
        self.assertEqual(mod.snapshot(self.config)['mainsail.cfg'], vendor.read_bytes())
        self.config['vendor_map'] = {'mainsail.cfg': str(self.root / 'other.cfg')}
        with self.assertRaises(mod.BackupError):
            mod.snapshot(self.config)
        self.config['roots'] = ['../vendor.cfg']
        with self.assertRaises(mod.BackupError):
            mod.snapshot(self.config)

    def test_source_drift_aborts_snapshot_before_delivery(self):
        from unittest.mock import patch
        mod = self.load_module()
        original = Path.read_bytes
        target = self.source / 'printer.cfg'
        reads = []
        def racing_read(path):
            data = original(path)
            if path == target and not reads:
                reads.append(True)
                path.write_text('[printer]\nkinematics: cartesian\n')
            return data
        with patch.object(Path, 'read_bytes', racing_read):
            with self.assertRaises(mod.BackupError):
                mod.snapshot(self.config)
        self.assertFalse(Path(self.config['state']).exists())

    def test_public_replacements_leave_private_original_untouched(self):
        original = '[notifier backup]\nurl: https://notify.invalid/private-topic\n[printer]\nkinematics: corexy\n'
        (self.source / 'printer.cfg').write_text(original)
        self.config['replacements'] = [{'path': 'printer.cfg', 'section': 'notifier backup', 'key': 'url', 'value': 'REDACTED'}]
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.source / 'printer.cfg').read_text(), original)
        self.assertEqual(git(self.remotes['private'], 'show', 'main:config/printer.cfg'), original.strip())
        self.assertIn('url: REDACTED', git(self.remotes['public'], 'show', 'main:config/printer.cfg'))
        self.assertNotIn('private-topic', git(self.remotes['public'], 'show', 'main:config/printer.cfg'))

    def test_unrecognized_secrets_block_only_public_without_leaking_values(self):
        original = '[mystery]\napi_token: dummy-test-sensitive-value\n'
        (self.source / 'printer.cfg').write_text(original)
        before = git(self.remotes['public'], 'rev-parse', 'main')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, git(self.remotes['public'], 'rev-parse', 'main'))
        self.assertEqual(git(self.remotes['private'], 'show', 'main:config/printer.cfg'), original.strip())
        self.assertNotIn('dummy-test-sensitive-value', result.stdout + result.stderr + json.dumps(self.status()))
        self.assertIsNone(self.status()['private']['error'])
        self.assertTrue(self.status()['public']['error'])

    def test_status_permissions_heartbeat_and_no_change(self):
        import time
        self.assertEqual(self.run_cli().returncode, 0)
        first = self.status()
        heads = {name: git(remote, 'rev-parse', 'main') for name, remote in self.remotes.items()}
        time.sleep(0.01)
        self.assertEqual(self.run_cli().returncode, 0)
        state = Path(self.config['state'])
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertEqual((state / 'status.json').stat().st_mode & 0o777, 0o600)
        for name, remote in self.remotes.items():
            self.assertEqual(heads[name], git(remote, 'rev-parse', 'main'))
            self.assertGreater(self.status()[name]['last_success'], first[name]['last_success'])

    def test_cycle_lock_prevents_concurrent_publication(self):
        import fcntl
        state = Path(self.config['state'])
        state.mkdir(mode=0o700)
        with open(state / 'cycle.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_cli()
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((state / 'public').exists())
        self.assertEqual(self.run_cli().returncode, 0)

    def test_pause_persists_and_now_refuses_until_resume(self):
        self.assertEqual(self.run_cli('pause').returncode, 0)
        self.assertTrue(self.status()['paused'])
        self.assertNotEqual(self.run_cli('now').returncode, 0)
        self.assertFalse((Path(self.config['state']) / 'public').exists())
        self.assertEqual(self.run_cli('status').returncode, 0)
        self.assertEqual(self.run_cli('resume').returncode, 0)
        self.assertFalse(self.status()['paused'])
        self.assertTrue(self.status()['public']['last_success'])

    def test_remote_documentation_fast_forward_preserves_new_docs(self):
        self.assertEqual(self.run_cli().returncode, 0)
        seed = self.root / 'public-seed'
        git(seed, 'pull', '--ff-only')
        (seed / 'NEW.md').write_text('New documentation')
        git(seed, 'add', 'NEW.md')
        git(seed, 'commit', '-m', 'Document')
        git(seed, 'push')
        (self.source / 'printer.cfg').write_text('[printer]\nkinematics: cartesian\n')
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.remotes['public'], 'show', 'main:NEW.md'), 'New documentation')

    def test_remote_config_edits_stop_without_overwrite(self):
        self.assertEqual(self.run_cli().returncode, 0)
        seed = self.root / 'public-seed'
        git(seed, 'pull', '--ff-only')
        (seed / 'config/printer.cfg').write_text('[printer]\nkinematics: delta\n')
        git(seed, 'commit', '-am', 'Unexpected remote config')
        git(seed, 'push')
        before = git(self.remotes['public'], 'rev-parse', 'main')
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(before, git(self.remotes['public'], 'rev-parse', 'main'))

    def test_deleted_secret_in_pending_history_blocks_public_push(self):
        self.assertEqual(self.run_cli().returncode, 0)
        repo = Path(self.config['state']) / 'public'
        before = git(self.remotes['public'], 'rev-parse', 'main')
        (repo / 'leaked.cfg').write_text('[x]\npassword: dummy-pending-secret\n')
        git(repo, 'add', 'leaked.cfg')
        git(repo, 'commit', '-m', 'Accidental unpushed secret')
        (repo / 'leaked.cfg').unlink()
        git(repo, 'commit', '-am', 'Remove secret')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, git(self.remotes['public'], 'rev-parse', 'main'))
        self.assertNotIn('dummy-pending-secret', result.stdout + result.stderr)

    def test_failed_push_retains_success_then_retries_unchanged_snapshot(self):
        self.assertEqual(self.run_cli().returncode, 0)
        first = self.status()['public']['last_success']
        before = git(self.remotes['public'], 'rev-parse', 'main')
        hook = self.remotes['public'] / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o700)
        (self.source / 'printer.cfg').write_text('[printer]\nkinematics: cartesian\n')
        self.assertNotEqual(self.run_cli().returncode, 0)
        pending = git(Path(self.config['state']) / 'public', 'rev-parse', 'HEAD')
        self.assertNotEqual(before, pending)
        self.assertEqual(self.status()['public'].get('last_success'), first)
        hook.unlink()
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(pending, git(self.remotes['public'], 'rev-parse', 'main'))
        self.assertGreater(self.status()['public']['last_success'], first)

    def test_missing_source_never_deletes_backup_and_sets_failure_status(self):
        self.assertEqual(self.run_cli().returncode, 0)
        before = {n: git(r, 'rev-parse', 'main') for n, r in self.remotes.items()}
        (self.source / 'printer.cfg').unlink()
        self.assertNotEqual(self.run_cli().returncode, 0)
        for name, remote in self.remotes.items():
            self.assertEqual(before[name], git(remote, 'rev-parse', 'main'))
            self.assertTrue(self.status()[name].get('error'))
            self.assertTrue(self.status()[name]['last_success'])

    def test_unsafe_deployment_settings_fail_before_checkout(self):
        original = json.loads(json.dumps(self.config))
        variants = []
        bad = json.loads(json.dumps(original)); bad['state'] = str(self.source / 'state'); variants.append(bad)
        bad = json.loads(json.dumps(original)); bad['repositories']['public']['url'] = 'https://example.invalid/owner/public.git'; variants.append(bad)
        bad = json.loads(json.dumps(original)); bad['repositories']['public']['url'] = bad['repositories']['private']['url']; variants.append(bad)
        for config in variants:
            self.config = config
            with self.subTest(kind=len(config['state'])):
                self.assertNotEqual(self.run_cli().returncode, 0)
                self.assertFalse(Path(config['state']).exists())

    def test_empty_private_remote_bootstraps_without_public_history(self):
        git(self.remotes['private'], 'update-ref', '-d', 'refs/heads/main')
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.remotes['private'], 'rev-list', '--count', 'main'), '1')
        self.assertNotIn('README.md', git(self.remotes['private'], 'ls-tree', '--name-only', 'main'))
        self.assertIn('config', git(self.remotes['private'], 'ls-tree', '--name-only', 'main'))

    def test_ambiguous_push_response_is_verified_against_remote(self):
        from unittest.mock import patch
        self.assertEqual(self.run_cli().returncode, 0)
        mod = self.load_module()
        original = mod.git
        def ambiguous(repo, *args, **kwargs):
            result = original(repo, *args, **kwargs)
            if args[0] == 'push':
                raise mod.BackupError('simulated lost acknowledgement')
            return result
        (self.source / 'printer.cfg').write_text('[printer]\nkinematics: cartesian\n')
        with patch.object(mod, 'git', ambiguous):
            status = mod.cycle(self.config)
        self.assertIsNone(status['public']['error'])
        self.assertEqual(status['public']['remote_head'], git(self.remotes['public'], 'rev-parse', 'main'))

    def test_watcher_debounces_updates_and_reports_paused_liveness(self):
        import time
        self.config.update({'quiet_seconds': 0.4, 'poll_seconds': 0.05, 'reconcile_seconds': 0.15})
        self.config_path.write_text(json.dumps(self.config))
        proc = subprocess.Popen(['python3', str(SCRIPT), '--config', str(self.config_path), 'watch'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.terminate(), proc.wait(timeout=5)) if proc.poll() is None else None)
        deadline = time.monotonic() + 5
        while not (Path(self.config['state']) / 'status.json').exists() and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.03)
        self.assertIsNone(proc.poll(), 'watch command must stay alive')
        self.assertFalse((Path(self.config['state']) / 'public').exists())
        (self.source / 'printer.cfg').write_text('[printer]\nkinematics: cartesian\n')
        deadline = time.monotonic() + 5
        while not self.status().get('public', {}).get('last_success') and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.status().get('public', {}).get('last_success'))
        for _ in range(30):
            if self.run_cli('pause').returncode == 0:
                break
            time.sleep(0.05)
        success = self.status()['public']['last_success']
        time.sleep(0.2)
        self.assertTrue(self.status()['paused'])
        self.assertGreater(self.status()['paused_seen_at'], success)
        self.assertGreater(self.status()['watcher_alive_at'], success)
        self.assertEqual(self.status()['public']['last_success'], success)

    def test_wildcard_include_cannot_silently_omit_excluded_dependency(self):
        (self.source / 'macros').mkdir()
        (self.source / 'printer.cfg').write_text('[include macros/*.cfg]\n')
        (self.source / 'macros/good.cfg').write_text('[gcode_macro GOOD]\ngcode: G28\n')
        (self.source / 'macros/secret.cfg').write_text('[x]\npassword: dummy-test-value\n')
        self.config['private_exclusions'] = ['macros/secret.cfg']
        mod = self.load_module()
        with self.assertRaises(mod.BackupError):
            mod.snapshot(self.config)

    def test_each_checkout_has_dedicated_external_ssh_identity(self):
        hosts = self.root / 'known_hosts'
        hosts.write_text('test fixture, not a real host key\n')
        for name in ('private', 'public'):
            key = self.root / (name + '-identity')
            key.write_text('test fixture, not a real private key\n')
            key.chmod(0o600)
            self.config['repositories'][name].update(ssh_key=str(key), known_hosts=str(hosts))
        self.assertEqual(self.run_cli().returncode, 0)
        for name in ('private', 'public'):
            command = git(Path(self.config['state']) / name, 'config', '--get', 'core.sshCommand', check=False)
            self.assertIn(str(self.root / (name + '-identity')), command)
            self.assertIn('IdentitiesOnly=yes', command)
            self.assertIn('StrictHostKeyChecking=yes', command)
        (self.root / 'private-identity').chmod(0o644)
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_scanner_rejects_multiline_json_and_high_entropy_credentials(self):
        mod = self.load_module()
        samples = [b'[x]\npassword:\n  dummy-secret\n', json.dumps({'password': 'dummy-secret'}).encode(),
                   b'[x]\nopaque: ' + b''.join([b'Ab9Qw2Er5Ty8', b'Ui1Op4As7Df0', b'Gh3Jk6Lz9Xc2', b'Vb5Nm8']) + b'\n']
        for content in samples:
            with self.subTest(sample=content[:4]):
                with self.assertRaises(mod.BackupError):
                    mod.scan_content(content)

    def test_scanner_preserves_sensitive_context_across_comments_and_blanks(self):
        mod = self.load_module()
        for gap in ('  # ordinary comment\n', '  ; ordinary comment\n', '\n', '  \n',
                    '# harmless: value\n', '; harmless: value\n'):
            for continuation in ('  shortsecret\n', '  harmless: shortsecret\n'):
                with self.subTest(gap=gap, continuation=continuation):
                    with self.assertRaises(mod.BackupError):
                        mod.scan_content(('[x]\npassword:\n' + gap + continuation).encode())

    def test_scanner_accepts_redacted_fields_and_resets_at_new_fields_or_sections(self):
        mod = self.load_module()
        for ending in ('', 'ordinary: value\n  continuation\n', '[ordinary]\n  value: safe\n'):
            with self.subTest(ending=ending):
                mod.scan_content(('[x]\npassword: REDACTED\n  # ordinary comment\n\n' + ending).encode())

    def test_optional_dependency_manifest_is_private_only(self):
        manifest = self.root / 'dependencies.json'
        manifest.write_text(json.dumps({'firmware': 'Kalico', 'vendor': {'client.cfg': 'reviewed revision'}}))
        self.config['dependency_manifest'] = str(manifest)
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertIn('Kalico', git(self.remotes['private'], 'show', 'main:config/_recovery/dependencies.json', check=False))
        self.assertNotIn('_recovery', git(self.remotes['public'], 'ls-tree', '-r', '--name-only', 'main'))

    def test_restore_materializes_private_commit_into_new_directory(self):
        (self.source / 'macros').mkdir()
        original = b'[gcode_macro OLD]\ngcode: G28\n'
        (self.source / 'macros/old.cfg').write_bytes(original)
        self.assertEqual(self.run_cli().returncode, 0)
        recovery_commit = git(self.remotes['private'], 'rev-parse', 'main')
        (self.source / 'macros/old.cfg').unlink()
        (self.source / 'macros/new.cfg').write_text('[gcode_macro NEW]\ngcode: G28\n')
        self.assertEqual(self.run_cli().returncode, 0)
        tree = git(self.remotes['private'], 'ls-tree', '-r', '--name-only', 'main')
        self.assertNotIn('old.cfg', tree)
        self.assertIn('new.cfg', tree)
        destination = self.root / 'restored'
        command = ['python3', str(HERE / 'restore_snapshot.py'), '--repo', str(self.remotes['private']),
                   '--commit', recovery_commit, '--destination', str(destination)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((destination / 'macros/old.cfg').read_bytes(), original)
        self.assertFalse((destination / 'macros/new.cfg').exists())
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_unreadable_approved_directory_blocks_deletions(self):
        if os.geteuid() == 0:
            self.skipTest('permission semantics require non-root test user')
        directory = self.source / 'macros'
        directory.mkdir()
        (directory / 'keep.cfg').write_text('[gcode_macro KEEP]\ngcode: G28\n')
        self.assertEqual(self.run_cli().returncode, 0)
        before = git(self.remotes['private'], 'rev-parse', 'main')
        directory.chmod(0)
        try:
            self.assertNotEqual(self.run_cli().returncode, 0)
            self.assertEqual(before, git(self.remotes['private'], 'rev-parse', 'main'))
        finally:
            directory.chmod(0o700)

    def test_unrelated_staged_edits_are_not_committed_by_backup(self):
        self.assertEqual(self.run_cli().returncode, 0)
        repo = Path(self.config['state']) / 'public'
        before = git(self.remotes['public'], 'rev-parse', 'main')
        (repo / 'README.md').write_text('Unrelated staged user work')
        git(repo, 'add', 'README.md')
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(before, git(self.remotes['public'], 'rev-parse', 'main'))
        self.assertEqual((repo / 'README.md').read_text(), 'Unrelated staged user work')

    def test_ignored_source_file_cannot_be_reported_as_backed_up(self):
        seed = self.root / 'public-seed'
        (seed / '.gitignore').write_text('config/macros/ignored.cfg\n')
        git(seed, 'add', '.gitignore'); git(seed, 'commit', '-m', 'Ignore test file'); git(seed, 'push')
        (self.source / 'macros').mkdir()
        (self.source / 'macros/ignored.cfg').write_text('[gcode_macro IMPORTANT]\ngcode: G28\n')
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertTrue(self.status()['public']['error'])

    def test_snapshot_preserves_docs_in_independent_repos(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, remote in self.remotes.items():
            self.assertEqual(git(remote, 'show', 'main:README.md'), 'Important documentation')
            self.assertEqual(git(remote, 'show', 'main:config/printer.cfg'), '[printer]\nkinematics: corexy')
            self.assertEqual(self.status()[name]['remote_head'], git(remote, 'rev-parse', 'main'))
        self.assertNotEqual(git(self.remotes['public'], 'rev-parse', 'main'), git(self.remotes['private'], 'rev-parse', 'main'))


if __name__ == '__main__':
    unittest.main()
