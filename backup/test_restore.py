"""Disposable Git/filesystem integration tests; no printer or network access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import restore_snapshot as recovery
from printer_snapshot import BackupError


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '--initial-branch=main')
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'config/macros').mkdir(parents=True)
        (self.repo / 'config/printer.cfg').write_text('[include macros/*.cfg]\n[printer]\nkinematics: corexy\n')
        (self.repo / 'config/macros/new.cfg').write_text('[gcode_macro TEST]\ngcode: M400\n')
        self.commit = self.save()
        self.target = self.root / 'live'
        self.target.mkdir()
        (self.target / 'printer.cfg').write_text('[printer]\nkinematics: cartesian\n')
        self.settings = {'source': str(self.target), 'state': str(self.root / 'state'),
                         'roots': ['printer.cfg'], 'directories': ['macros'],
                         'repositories': {'private': {'branch': 'main', 'url': 'unused'}}}
        self.bundle = self.root / 'review'

    def save(self):
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-m', 'fixture')
        return git(self.repo, 'rev-parse', 'HEAD')

    def prepare(self, mode='rollback', target=None):
        return recovery.prepare(self.settings, self.commit, self.bundle,
                                target or self.target, mode, repo=self.repo)

    def test_prepare_captures_baseline_without_touching_target(self):
        self.assertTrue(callable(getattr(recovery, 'prepare', None)), 'prepare API missing')
        original = (self.target / 'printer.cfg').read_bytes()
        digest = self.prepare()
        self.assertRegex(digest, r'^[0-9a-f]{64}$')
        self.assertEqual((self.target / 'printer.cfg').read_bytes(), original)
        self.assertEqual((self.bundle / 'files/printer.cfg').read_bytes(),
                         (self.repo / 'config/printer.cfg').read_bytes())
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.bundle / 'manifest.json').stat().st_mode & 0o777, 0o600)

    def test_apply_replaces_managed_deletes_extras_preserves_unrelated(self):
        self.assertTrue(callable(getattr(recovery, 'apply', None)), 'apply API missing')
        (self.target / 'macros').mkdir()
        (self.target / 'macros/old.cfg').write_text('obsolete')
        (self.target / 'macros/notes.txt').write_text('keep')
        (self.target / 'installer.cfg').write_text('keep installer')
        (self.target / 'vendor').symlink_to(self.root / 'external')
        digest = self.prepare()
        checked = []
        def guard():
            import fcntl
            state = Path(self.settings['state'])
            self.assertTrue(json.loads((state / 'status.json').read_text())['paused'])
            with (state / 'cycle.lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checked.append(True)
        archive = recovery.apply(self.settings, self.bundle, digest, guard=guard)
        self.assertTrue(checked)
        self.assertTrue(Path(archive).is_file())
        import tarfile
        with tarfile.open(archive) as saved:
            self.assertTrue(saved.getmember('target/vendor').issym())
            self.assertEqual(saved.extractfile('target/printer.cfg').read(),
                             b'[printer]\nkinematics: cartesian\n')
        self.assertFalse((self.target / 'macros/old.cfg').exists())
        self.assertEqual((self.target / 'printer.cfg').read_bytes(),
                         (self.repo / 'config/printer.cfg').read_bytes())
        self.assertEqual((self.target / 'installer.cfg').read_text(), 'keep installer')
        self.assertEqual((self.target / 'macros/notes.txt').read_text(), 'keep')
        self.assertTrue((self.target / 'vendor').is_symlink())
        self.assertTrue(json.loads((Path(self.settings['state']) / 'status.json').read_text())['paused'])

    def test_apply_refuses_changed_baseline_or_bundle(self):
        digest = self.prepare()
        path = self.target / 'printer.cfg'
        original = path.read_bytes()
        path.write_bytes(b'concurrent change')
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertEqual(path.read_bytes(), b'concurrent change')

    def test_confirmation_and_payload_integrity_are_required(self):
        digest = self.prepare()
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, '0' * 64, guard=lambda: None)
        (self.bundle / 'files/printer.cfg').write_text('tampered')
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)

    def test_prepare_validates_complete_owned_configuration(self):
        cases = {'empty': ('printer.cfg', ''),
                 'missing': ('printer.cfg', '[include missing.cfg]\n'),
                 'traversal': ('printer.cfg', '[include ../outside.cfg]\n'),
                 'scope': ('unowned.cfg', '[test]\n'),
                 'metadata': ('_recovery/dependencies.json', '{invalid')}
        for case, (name, content) in cases.items():
            with self.subTest(case=case):
                git(self.repo, 'reset', '--hard', self.commit)
                git(self.repo, 'clean', '-fd')
                path = self.repo / 'config' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                bad = self.save()
                with self.assertRaises(BackupError):
                    recovery.prepare(self.settings, bad, self.root / case, self.target,
                                     'rollback', repo=self.repo)

    def test_matching_approved_vendor_link_is_preserved(self):
        vendor = self.root / 'vendor.cfg'
        vendor.write_text('[gcode_macro VENDOR]\ngcode: M400\n')
        (self.target / 'mainsail.cfg').symlink_to(vendor)
        (self.repo / 'config/mainsail.cfg').write_bytes(vendor.read_bytes())
        self.settings['roots'].append('mainsail.cfg')
        self.settings['vendor_map'] = {'mainsail.cfg': str(vendor)}
        self.commit = self.save()
        digest = self.prepare()
        recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertTrue((self.target / 'mainsail.cfg').is_symlink())
        self.assertEqual(vendor.read_bytes(), (self.repo / 'config/mainsail.cfg').read_bytes())

    def test_changed_approved_vendor_link_is_refused(self):
        vendor = self.root / 'vendor.cfg'
        vendor.write_text('different vendor contents')
        (self.target / 'mainsail.cfg').symlink_to(vendor)
        (self.repo / 'config/mainsail.cfg').write_text('snapshot vendor contents')
        self.settings['roots'].append('mainsail.cfg')
        self.settings['vendor_map'] = {'mainsail.cfg': str(vendor)}
        self.commit = self.save()
        with self.assertRaises(BackupError):
            self.prepare()
        self.assertEqual(vendor.read_text(), 'different vendor contents')

    def test_prepare_refuses_managed_destination_symlinks(self):
        (self.target / 'printer.cfg').unlink()
        vendor = self.root / 'vendor.cfg'
        vendor.write_text('vendor bytes')
        (self.target / 'printer.cfg').symlink_to(vendor)
        with self.assertRaisesRegex(BackupError, 'symlink'):
            self.prepare()
        self.assertEqual(vendor.read_text(), 'vendor bytes')

    def test_rebuild_requires_explicit_mapping_and_keeps_metadata_in_bundle(self):
        meta = self.repo / 'config/_recovery/dependencies.json'
        meta.parent.mkdir()
        meta.write_text('{"packages": ["manual-review"]}')
        self.commit = self.save()
        fresh = self.root / 'new-host/config'
        fresh.parent.mkdir()
        digest = self.prepare('rebuild', fresh)
        recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertTrue((fresh / 'printer.cfg').is_file())
        self.assertFalse((fresh / '_recovery').exists())
        self.assertTrue((self.target / 'printer.cfg').is_file())
        with self.assertRaises(BackupError):
            recovery.prepare(self.settings, self.commit, self.root / 'badmode', fresh,
                             'rollback', repo=self.repo)

    def test_rejects_overlapping_bundle_state_and_unsafe_scope(self):
        with self.assertRaises(BackupError):
            recovery.prepare(self.settings, self.commit, self.target / 'review', self.target,
                             'rollback', repo=self.repo)
        self.settings['directories'] = ['../outside']
        with self.assertRaises(BackupError):
            self.prepare()

    def test_private_remote_uses_scoped_identity_and_pinned_hosts(self):
        from unittest.mock import patch
        key = self.root / 'deploy-key'
        key.write_text('not-a-real-key')
        key.chmod(0o600)
        hosts = self.root / 'known_hosts'
        hosts.write_text('test fixture')
        remote = 'git@example.invalid:owner/recovery.git'
        self.settings['repositories']['private'].update(url=remote, ssh_key=str(key), known_hosts=str(hosts))
        actual_git = recovery.git
        fetches = []
        def local_git(where, *args, **kwargs):
            args = list(args)
            if 'fetch' in args:
                self.assertIn(remote, args)
                command = next(x for x in args if x.startswith('core.sshCommand='))
                self.assertIn('StrictHostKeyChecking=yes', command)
                self.assertIn('IdentitiesOnly=yes', command)
                self.assertIn(str(hosts), command)
                args[args.index(remote)] = str(self.repo)
                fetches.append(True)
            return actual_git(where, *args, **kwargs)
        with patch.object(recovery, 'git', side_effect=local_git):
            recovery.prepare(self.settings, self.commit, self.bundle, self.target, 'rollback')
        self.assertEqual(fetches, [True])

    def test_unreachable_missing_and_short_commits_are_refused(self):
        git(self.repo, 'checkout', '--orphan', 'other')
        (self.repo / 'config/printer.cfg').write_text('[printer]\n')
        other = self.save()
        git(self.repo, 'checkout', 'main')
        for commit in (other, 'f' * 40, self.commit[:12]):
            with self.subTest(commit=commit):
                with self.assertRaises(BackupError):
                    recovery.prepare(self.settings, commit, self.bundle, self.target, 'rollback', repo=self.repo)

    def test_stopped_service_guard_accepts_only_loaded_inactive_dead(self):
        from unittest.mock import patch
        self.assertTrue(callable(getattr(recovery, 'services_stopped', None)), 'service guard missing')
        for active, substate, loaded in [('active', 'running', 'loaded'), ('failed', 'failed', 'loaded'),
                                        ('inactive', 'dead', 'not-found'), ('unknown', 'dead', 'loaded')]:
            answer = subprocess.CompletedProcess([], 0,
                f'LoadState={loaded}\nActiveState={active}\nSubState={substate}\n', '')
            with patch.object(recovery.subprocess, 'run', return_value=answer):
                with self.assertRaises(BackupError):
                    recovery.services_stopped()
        answer = subprocess.CompletedProcess([], 0, 'LoadState=loaded\nActiveState=inactive\nSubState=dead\n', '')
        with patch.object(recovery.subprocess, 'run', return_value=answer) as run:
            recovery.services_stopped()
        self.assertEqual(run.call_count, 2)
        self.assertIn('klipper.service', run.call_args_list[0].args[0])
        self.assertIn('moonraker.service', run.call_args_list[1].args[0])

    def test_guard_failure_leaves_pause_and_target_unchanged(self):
        digest = self.prepare()
        before = recovery.inventory(self.target)
        def busy():
            raise BackupError('services running')
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=busy)
        self.assertEqual(recovery.inventory(self.target), before)
        self.assertTrue(json.loads((Path(self.settings['state']) / 'status.json').read_text())['paused'])

    def test_rechecks_baseline_immediately_before_writes(self):
        digest = self.prepare()
        def racing_guard():
            (self.target / 'printer.cfg').write_text('concurrent')
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=racing_guard)
        self.assertEqual((self.target / 'printer.cfg').read_text(), 'concurrent')

    def test_partial_failure_retains_protected_full_archive_and_pause(self):
        from unittest.mock import patch
        self.assertTrue(callable(getattr(recovery, 'atomic_write', None)), 'atomic replacement missing')
        digest = self.prepare()
        original = (self.target / 'printer.cfg').read_bytes()
        real = recovery.atomic_write
        writes = []
        def fail_second(path, content):
            writes.append(path)
            if len(writes) == 2:
                raise OSError('simulated disk failure')
            return real(path, content)
        with patch.object(recovery, 'atomic_write', side_effect=fail_second):
            with self.assertRaisesRegex(BackupError, 'before.tar'):
                recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertEqual((self.target / 'printer.cfg').read_bytes(), original)
        self.assertTrue((self.bundle / 'before.tar').is_file())
        self.assertEqual((self.bundle / 'before.tar').stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.bundle / 'apply-started.json').is_file())
        self.assertFalse((self.bundle / 'applied.json').exists())

    def test_revalidates_scope_and_bundle_symlinks_at_apply(self):
        digest = self.prepare()
        self.settings['directories'] = []
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.settings['directories'] = ['macros']
        path = self.bundle / 'files/printer.cfg'
        path.unlink()
        path.symlink_to(self.repo / 'config/printer.cfg')
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)

    def test_simple_restore_decline_does_not_change_config(self):
        import contextlib
        import io
        from unittest.mock import patch
        settings = self.root / 'settings.json'
        settings.write_text(json.dumps(self.settings))
        before = recovery.inventory(self.target)
        args = ['restore_snapshot.py', 'restore', '--config', str(settings),
                '--repo', str(self.repo), '--commit', self.commit]
        with patch('sys.argv', args), patch('builtins.input', return_value='no'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(recovery.main(), 0)
        self.assertIn('printer.cfg', output.getvalue())
        self.assertNotIn('kinematics', output.getvalue())
        self.assertEqual(recovery.inventory(self.target), before)
        self.assertFalse(Path(self.settings['state']).exists())

    def test_simple_restore_same_command_for_existing_and_new_config(self):
        import contextlib
        import io
        from unittest.mock import patch
        for fresh in (False, True):
            with self.subTest(fresh=fresh):
                if fresh:
                    self.settings['source'] = str(self.root / 'fresh-config')
                settings = self.root / 'settings.json'
                settings.write_text(json.dumps(self.settings))
                args = ['restore_snapshot.py', 'restore', '--config', str(settings),
                        '--repo', str(self.repo), '--commit', self.commit]
                with patch('sys.argv', args), patch('builtins.input', return_value='yes'), patch.object(recovery, 'services_stopped'), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(recovery.main(), 0)
                self.assertEqual((Path(self.settings['source']) / 'printer.cfg').read_bytes(),
                                 (self.repo / 'config/printer.cfg').read_bytes())
                self.assertIn('before.tar', output.getvalue())

    def test_legacy_export_cli(self):
        import contextlib
        import io
        from unittest.mock import patch
        args = ['restore_snapshot.py', '--repo', str(self.repo), '--commit',
                self.commit, '--destination', str(self.root / 'export')]
        with patch('sys.argv', args), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(recovery.main(), 0)
        self.assertEqual((self.root / 'export/printer.cfg').read_bytes(),
                         (self.repo / 'config/printer.cfg').read_bytes())

    def test_changed_watcher_state_path_is_refused(self):
        digest = self.prepare()
        self.settings['state'] = str(self.root / 'wrong-watcher')
        with self.assertRaises(BackupError):
            recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)

    def test_apply_detects_midwrite_concurrent_modification(self):
        from unittest.mock import patch
        digest = self.prepare()
        real = recovery.atomic_write
        def concurrent(path, content):
            real(path, content)
            if path.name != 'printer.cfg':
                (self.target / 'printer.cfg').write_text('concurrent edit must survive')
        with patch.object(recovery, 'atomic_write', side_effect=concurrent):
            with self.assertRaises(BackupError):
                recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertEqual((self.target / 'printer.cfg').read_text(), 'concurrent edit must survive')

    def test_cycle_lock_busy_refuses_apply(self):
        import fcntl
        digest = self.prepare()
        state = Path(self.settings['state'])
        state.mkdir()
        with (state / 'cycle.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertFalse((self.bundle / 'before.tar').exists())

    def test_git_ignores_inherited_transport_and_repository_overrides(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'GIT_DIR': str(self.root / 'wrong.git'),
                                     'GIT_SSH_COMMAND': 'do-not-execute', 'GIT_CONFIG_COUNT': '1',
                                     'GIT_CONFIG_KEY_0': 'core.bare', 'GIT_CONFIG_VALUE_0': 'false'}):
            digest = self.prepare()
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_git_symlink_and_submodule_objects_are_rejected(self):
        path = self.repo / 'config/macros/new.cfg'
        path.unlink()
        path.symlink_to('/outside')
        bad = self.save()
        with self.assertRaises(BackupError):
            recovery.prepare(self.settings, bad, self.bundle, self.target, 'rollback', repo=self.repo)
        git(self.repo, 'reset', '--hard', self.commit)
        git(self.repo, 'update-index', '--add', '--cacheinfo', '160000,' + self.commit + ',config/macros/submodule')
        git(self.repo, 'commit', '-m', 'gitlink fixture')
        bad = git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaises(BackupError):
            recovery.prepare(self.settings, bad, self.bundle, self.target, 'rollback', repo=self.repo)

    def test_rebuild_creates_private_ancestors_with_permissive_umask(self):
        fresh = self.root / 'rebuilt/config'
        digest = self.prepare('rebuild', fresh)
        old = os.umask(0)
        try:
            recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        finally:
            os.umask(old)
        for path in (fresh.parent, fresh, fresh / 'macros'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_lexical_parent_paths_cannot_hide_bundle_overlap(self):
        (self.root / 'other').mkdir()
        with self.assertRaises(BackupError):
            recovery.prepare(self.settings, self.commit, self.root / 'other/../live/review',
                             self.target, 'rollback', repo=self.repo)

    def test_preserved_exclusion_must_not_expand_snapshot_include(self):
        (self.target / 'macros').mkdir()
        (self.target / 'macros/excluded.cfg').write_text('[gcode_macro UNREVIEWED]\n')
        self.settings['private_exclusions'] = ['macros/excluded.cfg']
        with self.assertRaisesRegex(BackupError, 'include'):
            self.prepare()

    def test_rebuild_existing_installer_directory_preserves_unowned_files(self):
        fresh = self.root / 'installer-config'
        fresh.mkdir()
        (fresh / 'printer.cfg').write_text('installer demo')
        (fresh / 'installer.txt').write_text('retain')
        digest = self.prepare('rebuild', fresh)
        recovery.apply(self.settings, self.bundle, digest, guard=lambda: None)
        self.assertEqual((fresh / 'installer.txt').read_text(), 'retain')
        self.assertEqual((fresh / 'printer.cfg').read_bytes(), (self.repo / 'config/printer.cfg').read_bytes())


if __name__ == '__main__':
    unittest.main()
