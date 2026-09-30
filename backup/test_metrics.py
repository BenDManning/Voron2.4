"""Real loopback HTTP tests; no printer or external hosts required."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import snapshot_metrics


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'status.json'
        self.status = {
            'public': {'last_success': 123.5, 'error': None, 'remote_head': 'DO_NOT_EXPORT'},
            'private': {'last_success': 456, 'error': 'DO_NOT_EXPORT'},
            'watcher_alive_at': 789, 'paused': False,
            'DO_NOT_EXPORT': {'last_success': 999},
        }
        self.write_status()

    def write_status(self):
        self.path.write_text(json.dumps(self.status), encoding='utf-8')

    def start(self, allowed=('127.0.0.1',)):
        server, thread = snapshot_metrics.start_server(self.path, ('127.0.0.1', 0), allowed)
        self.assertTrue(thread.daemon)
        self.assertTrue(thread.is_alive())
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path='/metrics', method='GET', headers=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=2)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def test_denied_clients_are_rejected_before_routing(self):
        server = self.start(allowed=())
        self.path.unlink()
        for method in ('GET', 'HEAD', 'POST', 'OPTIONS', 'DELETE'):
            for path in ('/metrics', '/', '/status.json'):
                with self.subTest(method=method, path=path):
                    code, _, body = self.request(server, path, method,
                                                {'X-Forwarded-For': '127.0.0.1'})
                    self.assertEqual(code, 403)
                    self.assertNotIn(str(self.path), body)

    def test_only_get_metrics_is_served_without_request_logging(self):
        server = self.start()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            for path in ('/', '/status.json', '/metrics?x=1', '/metrics/', '/../../'):
                with self.subTest(path=path):
                    code, _, body = self.request(server, path)
                    self.assertEqual(code, 404)
                    self.assertNotIn('printer_backup_', body)
            for method in ('HEAD', 'POST', 'OPTIONS', 'DELETE', 'DO_NOT_EXPORT'):
                code, _, body = self.request(server, method=method)
                self.assertEqual(code, 405)
                self.assertNotIn('DO_NOT_EXPORT', body)
            self.assertEqual(self.request(server)[0], 200)
        self.assertEqual(errors.getvalue(), '')

    def test_bad_status_fails_closed_without_details_or_logging(self):
        server = self.start()
        errors = io.StringIO()
        invalid = [None, '{', '[]', '{}', '{"paused": false}', '"DO_NOT_EXPORT"']
        for field in ('last_success', 'watcher_alive_at'):
            for value in (-1, float('nan'), float('inf'), -float('inf'), True, 'DO_NOT_EXPORT', [], 10**400):
                status = json.loads(json.dumps(self.status))
                target = status['public'] if field == 'last_success' else status
                target[field] = value
                invalid.append(json.dumps(status))
        for field, value in (('paused', 'false'), ('public', []), ('private', None)):
            invalid.append(json.dumps({**self.status, field: value}))
        with contextlib.redirect_stderr(errors):
            for document in invalid:
                with self.subTest(document=str(document)[:100]):
                    if document is None:
                        self.path.unlink(missing_ok=True)
                    else:
                        self.path.write_text(document)
                    code, _, body = self.request(server)
                    self.assertEqual(code, 503)
                    self.assertNotIn('DO_NOT_EXPORT', body)
                    self.assertNotIn('printer_backup_', body)
                    self.assertNotIn(str(self.path), body)
        self.assertEqual(errors.getvalue(), '')

    def test_fresh_status_and_never_succeeded_destinations(self):
        server = self.start()
        self.assertEqual(self.request(server)[0], 200)
        self.status = {'paused': True, 'watcher_alive_at': 1000,
                       'public': {'error': 'DO_NOT_EXPORT'}}
        self.write_status()
        code, _, body = self.request(server)
        self.assertEqual(code, 200)
        self.assertIn('printer_backup_paused 1\n', body)
        self.assertIn('printer_backup_watcher_alive_timestamp_seconds 1000\n', body)
        for name in ('public', 'private'):
            self.assertIn('printer_backup_last_success_timestamp_seconds'
                          f'{{destination="{name}"}} 0\n', body)
        self.assertIn('printer_backup_failure{destination="public"} 1\n', body)
        self.assertIn('printer_backup_failure{destination="private"} 0\n', body)

    def test_invalid_error_field_is_not_reported_as_success(self):
        server = self.start()
        for value in (False, 0, [], {}):
            with self.subTest(value=value):
                self.status['public']['error'] = value
                self.write_status()
                self.assertEqual(self.request(server)[0], 503)

    def test_exports_only_fixed_numeric_metrics(self):
        server = self.start()
        status, headers, body = self.request(server)
        self.assertEqual(status, 200)
        self.assertIn('text/plain', headers['Content-Type'])
        samples = {line.split()[0]: float(line.split()[1]) for line in body.splitlines()
                   if line and not line.startswith('#')}
        self.assertEqual(samples, {
            'printer_backup_last_success_timestamp_seconds{destination="public"}': 123.5,
            'printer_backup_last_success_timestamp_seconds{destination="private"}': 456,
            'printer_backup_failure{destination="public"}': 0,
            'printer_backup_failure{destination="private"}': 1,
            'printer_backup_watcher_alive_timestamp_seconds': 789,
            'printer_backup_paused': 0,
        })
        self.assertNotIn('DO_NOT_EXPORT', body)


if __name__ == '__main__':
    unittest.main()
