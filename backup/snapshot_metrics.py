"""Read-only, standard-library metrics for the snapshot watcher."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading


def _timestamp(value):
    if type(value) not in (int, float) or value < 0 or not math.isfinite(value):
        raise ValueError('invalid timestamp')
    return value


def _render(status):
    if not isinstance(status, dict) or type(status.get('paused')) is not bool:
        raise ValueError('invalid status')
    alive = _timestamp(status['watcher_alive_at'])
    lines = []
    for name in ('public', 'private'):
        destination = status.get(name, {})
        if not isinstance(destination, dict):
            raise ValueError('invalid destination')
        error = destination.get('error')
        if error is not None and not isinstance(error, str):
            raise ValueError('invalid error flag')
        success = _timestamp(destination.get('last_success', 0))
        lines.append('printer_backup_last_success_timestamp_seconds'
                     f'{{destination="{name}"}} {success}')
        lines.append(f'printer_backup_failure{{destination="{name}"}} '
                     f'{int(bool(destination.get("error")))}')
    lines.append(f'printer_backup_watcher_alive_timestamp_seconds {alive}')
    lines.append(f'printer_backup_paused {int(status["paused"])}')
    return ('\n'.join(lines) + '\n').encode('ascii')


def start_server(state_path, bind_tuple, allowed_clients):
    """Start a daemon HTTP thread; return (server, thread).

    state_path is the status.json file, not its directory. The caller owns
    shutdown(): server.shutdown(), thread.join(), server.server_close().
    """
    path = Path(state_path)
    allowed = frozenset(allowed_clients)

    class Handler(BaseHTTPRequestHandler):
        def parse_request(self):
            if not super().parse_request():
                return False
            if self.client_address[0] not in allowed:
                self.send_error(403)
                return False
            if self.path != '/metrics':
                self.send_error(404)
                return False
            if self.command != 'GET':
                self.send_error(405)
                return False
            return True

        def do_GET(self):
            try:
                body = _render(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(bind_tuple, Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name='snapshot-metrics')
    thread.start()
    return server, thread
