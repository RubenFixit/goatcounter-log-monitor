#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the real CLI against an isolated loopback API, never the real site."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import threading

INSPECTION_KEY = 'goatcounter-offline-inspection'
BOT_HINT = re.compile(r'bot\b|crawler|spider|facebookexternalhit|uptimerobot|sitemonitor|slurp', re.I)


def inspect_log(binary, cli_args, snapshot, diagnostic_path):
    result = {'rows': 0, 'batches': 0, 'bot_user_agent_hints': 0, 'invalid_candidates': 0,
              'first_record_at': None, 'last_record_at': None}

    class LocalAPI(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split('?')[0] not in ('/api/v0/me', '/api/v0/test'):
                return self.reply(404, {})
            self.reply(200, {'token': {'permissions': 2}, 'user': {}, 'perm': 2})

        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            if length < 0 or length > 4_000_000:
                return self.reply(413, {})
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                return self.reply(400, {})
            if self.path == '/api/v0/test':
                return self.reply(200, {'perm': 2})
            if self.path != '/api/v0/count':
                return self.reply(404, {})
            hits = body.get('hits', [])
            if not isinstance(hits, list):
                return self.reply(400, {})
            result['batches'] += 1
            for hit in hits:
                result['rows'] += 1
                result['bot_user_agent_hints'] += bool(BOT_HINT.search(hit.get('user_agent', '')))
                when = hit.get('created_at')
                if not hit.get('path') or not when or when.startswith('0001-'):
                    result['invalid_candidates'] += 1
                if when:
                    if result['first_record_at'] is None or when < result['first_record_at']:
                        result['first_record_at'] = when
                    if result['last_record_at'] is None or when > result['last_record_at']:
                        result['last_record_at'] = when
            # Count only a nonidentifying summary; never forward or persist hits.
            self.reply(202, {'status': 'ok'})

    api = ThreadingHTTPServer(('127.0.0.1', 0), LocalAPI)
    thread = threading.Thread(target=api.serve_forever, daemon=True)
    thread.start()
    args = []
    skip_next = False
    for arg in cli_args:
        if skip_next:
            skip_next = False
        elif arg in ('-site', '--site'):
            skip_next = True
        elif arg.startswith(('-site=', '--site=')) or arg == '-follow':
            continue
        else:
            args.append(arg)
    args.append(f'-site=http://127.0.0.1:{api.server_port}')
    env = dict(os.environ, GOATCOUNTER_API_KEY=INSPECTION_KEY)
    try:
        with open(diagnostic_path, 'wb') as diagnostics:
            completed = subprocess.run([binary, *args, str(snapshot)], env=env,
                                       stdout=diagnostics, stderr=subprocess.STDOUT)
        result['exit_code'] = completed.returncode
        result['diagnostic_bytes'] = Path(diagnostic_path).stat().st_size
        return result
    finally:
        api.shutdown()
        api.server_close()
        thread.join(timeout=2)
