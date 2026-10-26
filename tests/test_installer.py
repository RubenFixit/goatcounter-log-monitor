#!/usr/bin/env python3
"""Linux integration tests. Fake downloads, keys, CLI, and crontab; no network."""
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import fcntl
import pty
import select
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import tempfile
import termios
import threading
import time
import unittest

INSTALLER = Path(__file__).resolve().parents[1] / 'install.sh'
FAKE_CLI = (Path(__file__).with_name('fixtures') / 'goatcounter').read_bytes()
CUSTOM_FORMAT = 'log:$remote_addr $ignore [$datetime] "$method $path $http" $status $size "$referrer" "$user_agent"$ignore'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='goatcounter-monitor-test-')
        self.root = Path(self.temp.name)
        self.bin = self.root / 'executables with spaces'
        self.config = self.root / 'private config'
        self.state = self.root / 'private state'
        self.mocks = self.root / 'mocks'
        self.mocks.mkdir()
        self.log = self.root / "access 'quoted' $(touch SHOULD_NOT_EXIST).log"
        self.log.write_text('')
        self.token = "fixture-token-'$()=not-a-real-key"
        archive = gzip.compress(FAKE_CLI, mtime=0)
        (self.root / 'download.gz').write_bytes(archive)
        metadata = {
            'tag_name': 'v2.7.0',
            'assets': [{
                'name': 'goatcounter-v2.7.0-linux-amd64.gz',
                'digest': 'sha256:' + hashlib.sha256(archive).hexdigest(),
                'browser_download_url': 'https://github.com/arp242/goatcounter/releases/download/v2.7.0/goatcounter-v2.7.0-linux-amd64.gz',
            }],
        }
        (self.root / 'release.json').write_text(json.dumps(metadata))
        self.write_mock('uname', (Path(__file__).with_name('fixtures') / 'uname').read_text())
        self.write_mock('curl', (Path(__file__).with_name('fixtures') / 'curl').read_text())
        self.write_mock('crontab', (Path(__file__).with_name('fixtures') / 'crontab').read_text())
        self.env = dict(os.environ, PATH=str(self.mocks)+':'+os.environ['PATH'],
                        GC_TEST_ROOT=str(self.root), GC_INSTALLER=str(INSTALLER),
                        GC_TEST_CONFIG=str(self.config), GC_TEST_STATE=str(self.state),
                        GC_TEST_CAPTURE=str(self.root / 'arguments'),
                        GC_TEST_CALLS=str(self.root / 'calls'), GC_TEST_CONTENTS=str(self.root / 'contents'))
        self.harness = 'source "$GC_INSTALLER"; CONFIG_DIR="$GC_TEST_CONFIG"; STATE_DIR="$GC_TEST_STATE"; '

    def tearDown(self):
        self.temp.cleanup()

    def write_mock(self, name, contents):
        p = self.mocks / name
        p.write_text(contents)
        p.chmod(0o700)

    def wizard(self, inputs, args='--skip-update-check'):
        return subprocess.run(['bash', '-c', self.harness+'main '+args], input='\n'.join(inputs)+'\n',
                              text=True, capture_output=True, env=self.env, cwd=self.root, timeout=15)

    def inputs(self, mode='panel'):
        return [str(self.bin), 'blog-https', 'https://logs.example.test/', self.token,
                str(self.log), '', '', '', mode]

    def test_rerunning_installer_detects_existing_monitors_and_preserves_settings(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        config = self.config/'blog-https.conf'
        original = config.read_bytes()
        # If a same-version CLI is accidentally downloaded again, verification
        # fails. Correct update detection must avoid that download.
        (self.root/'download.gz').write_bytes(b'not a valid replacement')
        result = self.wizard([str(self.bin), 'n'])
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Existing monitors', result.stdout)
        self.assertIn('CLI is up to date', result.stdout)
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(len(list(self.config.glob('*.conf'))), 1)

    def test_installer_monitor_only_update_skips_cli_network_and_preserves_receipts(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        receipt = self.state/'example-receipt.json'
        receipt.write_text('{"keep":true}')
        config = (self.config/'blog-https.conf').read_bytes()
        self.write_mock('curl', '#!/bin/sh\necho unexpected-network >&2\nexit 99\n')
        result = self.wizard([str(self.bin)], 'update --monitor-only --skip-update-check')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Skipping GoatCounter CLI updates', result.stdout)
        self.assertEqual(receipt.read_text(), '{"keep":true}')
        self.assertEqual((self.config/'blog-https.conf').read_bytes(), config)

    def test_installer_offers_and_installs_newer_cli_without_recreating_monitors(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        cli = self.bin/'goatcounter'
        cli.write_bytes(FAKE_CLI.replace(b'v2.7.0', b'v2.6.0'))
        result = self.wizard([str(self.bin), 'y'], 'update --skip-update-check')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Latest stable CLI: v2.7.0', result.stdout)
        self.assertIn(b'v2.7.0', cli.read_bytes())
        self.assertEqual(len(list(self.config.glob('*.conf'))), 1)

    def test_installer_does_not_downgrade_newer_cli(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        cli = self.bin/'goatcounter'
        newer = FAKE_CLI.replace(b'v2.7.0', b'v2.8.0')
        cli.write_bytes(newer)
        result = self.wizard([str(self.bin)], 'update --skip-update-check')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('newer than the latest stable', result.stdout)
        self.assertEqual(cli.read_bytes(), newer)

    def test_gist_launcher_migration_keeps_private_config_and_receipts(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        launcher = self.bin/'goatcounter-log-monitor'
        launcher.unlink()
        launcher.write_text('# legacy standalone gist runner\n')
        (self.state/'install-bin').unlink()
        config = (self.config/'blog-https.conf').read_bytes()
        result = self.wizard([str(self.bin), 'y'], 'update --skip-update-check')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue(launcher.is_symlink())
        self.assertEqual((self.config/'blog-https.conf').read_bytes(), config)

    def test_monitor_has_no_update_command(self):
        runner = INSTALLER.parent/'bin'/'goatcounter-log-monitor'
        result = subprocess.run(['bash', str(runner), 'update'], text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unknown command', result.stderr)

    def batch_fixture(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        for day, content, compressed in [('2026-10-19', b'older\n', True),
                                          ('2026-10-24', b'previous\n', False),
                                          ('2026-10-25', b'yesterday\n', False)]:
            p = self.root / (self.log.name + '.' + day + ('.gz' if compressed else ''))
            p.write_bytes(gzip.compress(content) if compressed else content)
        # Match DreamHost's alias, a compressed copy of a plain archive, and
        # unrelated files. None should be submitted twice or parsed as logs.
        (self.root/(self.log.name+'.0')).symlink_to(self.log.name+'.2026-10-25')
        (self.root/(self.log.name+'.2026-10-24.gz')).write_bytes(gzip.compress(b'previous\n'))
        (self.root/'error.log.2026-10-25').write_text('not access data')
        self.log.write_text('active log must not be imported\n')

    def batch(self, flags='', env=None):
        return subprocess.run(['bash', '-c', self.harness+'batch_monitor blog-https '+flags],
                              text=True, capture_output=True, env=env or self.env,
                              cwd=self.root, timeout=30)

    def receipt(self):
        return next((self.state/'batches').glob('*/receipts.json'))

    def test_custom_format_is_saved_and_passed_to_watcher_without_filters(self):
        inputs = self.inputs()
        inputs[5:6] = ['custom', '', '']
        result = self.wizard(inputs)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('batch blog-https --include-current', result.stdout)
        self.assertIn('BEFORE starting a watcher', result.stdout)
        result = subprocess.run(['bash', '-c', self.harness+'watch_monitor blog-https'],
                                env=self.env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.root/'arguments').read_bytes().split(b'\0')
        self.assertIn(os.fsencode('-format='+CUSTOM_FORMAT), args)
        self.assertIn(b'-datetime=02/Jan/2006:15:04:05 -0700', args)
        self.assertIn(b'-debug=import-api', args)
        self.assertEqual([arg for arg in args if arg.startswith(b'-exclude=')], [b'-exclude=path:re:a^'])
        self.assertNotIn(b'-silent', args)

    def test_batch_include_current_passes_snapshot_unchanged_and_skips_repeat(self):
        self.batch_fixture()
        self.log.write_bytes(b'current log with partial last line')
        result = self.batch('--include-current --yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 4)
        self.assertEqual((self.root/'contents').read_bytes(), b'older\nprevious\nyesterday\ncurrent log with partial last line')
        result = self.batch('--include-current --yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 4)

    def test_batch_include_current_also_works_without_archives(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.log.write_bytes(b'today\n')
        result = self.batch('--include-current --before 2000-01-01 --yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'contents').read_bytes(), b'today\n')
        self.assertIn('Date bounds apply only to archives', result.stdout)

    def test_stop_watcher_releases_lock_for_batch_and_can_repeat(self):
        self.batch_fixture()
        watcher = subprocess.Popen(['bash', '-c', self.harness+'watch_monitor blog-https'],
                                   env=dict(self.env, GC_TEST_SLEEP='30'))
        try:
            for _ in range(100):
                if (self.root/'arguments').exists():
                    break
                time.sleep(.02)
            self.assertTrue((self.root/'arguments').exists())
            result = subprocess.run(['bash', '-c', self.harness+'stop_monitor blog-https'],
                                    env=self.env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('stopped', result.stdout)
            self.assertIn('Cron may start it again', result.stdout)
            self.assertEqual(watcher.wait(timeout=3), -signal.SIGTERM)
            result = subprocess.run(['bash', '-c', self.harness+'stop_monitor blog-https'],
                                    env=self.env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('not running', result.stdout)
            result = self.batch('--dry-run')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        finally:
            if watcher.poll() is None:
                watcher.terminate()
                watcher.wait(timeout=3)

    def test_stop_leaves_non_watcher_lock_holder_running(self):
        self.batch_fixture()
        with (self.state/'blog-https.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(['bash', '-c', self.harness+'stop_monitor blog-https'],
                                    env=self.env, text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('no matching watcher', result.stderr)
        result = self.batch('--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_batch_preview_has_no_uploads_or_receipts(self):
        self.batch_fixture()
        result = self.batch('--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('3 unique files', result.stdout)
        self.assertNotIn(self.log.name+'.0 (', result.stdout)
        self.assertFalse((self.root/'calls').exists())
        self.assertEqual(list((self.state/'batches').glob('*/receipts.json')), [])

    def test_batch_interactive_confirmation_uses_terminal(self):
        self.batch_fixture()
        master, slave = pty.openpty()
        def setup_terminal():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        process = subprocess.Popen(['bash', '-c', self.harness+'batch_monitor blog-https'],
                                   env=self.env, stdin=slave, stdout=slave, stderr=slave,
                                   preexec_fn=setup_terminal, cwd=self.root)
        os.close(slave)
        output = b''
        answered = False
        try:
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                ready, _, _ = select.select([master], [], [], .1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                    if b'Type IMPORT' in output and not answered:
                        os.write(master, b'IMPORT\n')
                        answered = True
                if process.poll() is not None:
                    break
            self.assertEqual(process.wait(timeout=2), 0, output.decode(errors='replace'))
            self.assertTrue(answered, output.decode(errors='replace'))
            self.assertEqual((self.root/'calls').read_text().count('call'), 3)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_batch_handles_rotations_gzip_aliases_and_repeat_runs(self):
        self.batch_fixture()
        result = self.batch('--yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 3)
        self.assertEqual((self.root/'contents').read_bytes(), b'older\nprevious\nyesterday\n')
        receipts = json.loads(self.receipt().read_text())
        self.assertEqual(len(receipts), 3)
        self.assertTrue(all(v['status']=='complete' for v in receipts.values()))
        self.assertEqual(stat.S_IMODE(self.receipt().stat().st_mode), 0o600)
        again = self.batch('--yes')
        self.assertEqual(again.returncode, 0, again.stdout+again.stderr)
        self.assertIn('Nothing new', again.stdout)
        self.assertEqual((self.root/'calls').read_text().count('call'), 3)

    def test_batch_date_bounds_exclude_overlap_days(self):
        self.batch_fixture()
        result = self.batch('--from 2026-10-24 --before 2026-10-25 --yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'contents').read_bytes(), b'previous\n')

    def test_batch_refuses_changed_dated_archive(self):
        self.batch_fixture()
        result = self.batch('--yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        p = self.root/(self.log.name+'.2026-10-25')
        p.write_bytes(p.read_bytes()+b'more lines\n')
        result = self.batch('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('changed since a previous import attempt', result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 3)

    def test_batch_numeric_rotations_supported(self):
        self.batch_fixture()
        (self.root/(self.log.name+'.2.gz')).write_bytes(gzip.compress(b'numbered archive\n'))
        result = self.batch('--yes')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn(b'numbered archive', (self.root/'contents').read_bytes())

    def test_batch_failure_is_uncertain_and_never_automatically_retried(self):
        self.batch_fixture()
        result = self.batch('--yes', dict(self.env, GC_TEST_FAIL='1'))
        self.assertEqual(result.returncode, 7)
        self.assertIn('Some hits may have been uploaded', result.stderr)
        self.assertEqual(next(iter(json.loads(self.receipt().read_text()).values()))['status'], 'uncertain')
        again = self.batch('--yes')
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('refusing automatic retry', again.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 1)

    def test_batch_shows_cli_output_and_accepts_zero_exit(self):
        self.batch_fixture()
        result = self.batch('--yes', dict(self.env, GC_TEST_DIAGNOSTIC='1'))
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('simulated partial upload warning', result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 3)
        self.assertTrue(all(v['status']=='complete' for v in json.loads(self.receipt().read_text()).values()))
        self.assertNotIn(b'-silent', (self.root/'arguments').read_bytes().split(b'\0'))

    def test_batch_corrupt_gzip_fails_before_any_upload(self):
        self.batch_fixture()
        (self.root/(self.log.name+'.2026-10-26.gz')).write_bytes(b'not gzip')
        result = self.batch('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Nothing from this batch was uploaded', result.stderr)
        self.assertFalse((self.root/'calls').exists())

    def test_batch_passes_archives_without_local_parser_preflight(self):
        self.batch_fixture()
        result = self.batch('--yes', dict(self.env, GC_TEST_INSPECT_ZERO='1'))
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('call'), 3)
        self.assertEqual((self.root/'contents').read_bytes(), b'older\nprevious\nyesterday\n')
        self.assertNotIn('eligible records', result.stdout)

    def test_inspect_never_uses_destination_or_real_token(self):
        self.batch_fixture()
        result = subprocess.run(['bash', '-c', self.harness+'inspect_monitor blog-https'],
                                env=self.env, cwd=self.root, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Read-only inspection', result.stdout)
        self.assertIn('Configured import settings: 1 candidate', result.stdout)
        self.assertNotIn(self.token, result.stdout+result.stderr)
        self.assertFalse((self.root/'calls').exists())
        self.assertFalse((self.state/'batches').exists())

    @unittest.skipUnless(os.environ.get('GC_REAL_CLI'), 'Set GC_REAL_CLI for native CLI format/filter inspection.')
    def test_inspect_actual_cli_combined_http2_filters_and_bot_hints(self):
        self.batch_fixture()
        self.log.write_bytes((Path(__file__).with_name('fixtures')/'apache-http2.log').read_bytes())
        with (self.config/'blog-https.conf').open('a') as config:
            config.write('\nBINARY='+shlex.quote(os.environ['GC_REAL_CLI'])+'\n')
        result = subprocess.run(['bash', '-c', self.harness+'inspect_monitor blog-https'],
                                env=self.env, cwd=self.root, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Format only (no exclusions): 7 candidate records', result.stdout)
        self.assertIn('GET requests only: 6 candidate records', result.stdout)
        self.assertIn('HTTP 200 only: 5 candidate records', result.stdout)
        self.assertIn('Configured import settings: 7 candidate records', result.stdout)
        self.assertIn('User-Agent hints among eligible records: 4/7', result.stdout)
        self.assertFalse((self.root/'calls').exists())

    def test_batch_refuses_running_watcher(self):
        self.batch_fixture()
        env = dict(self.env, GC_TEST_SLEEP='3')
        first = subprocess.Popen(['bash', '-c', self.harness+'watch_monitor blog-https'], env=env)
        try:
            for _ in range(100):
                if (self.root/'arguments').exists(): break
                time.sleep(.02)
            result = self.batch('--yes')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('goatcounter-log-monitor stop blog-https', result.stderr)
            self.assertFalse((self.root/'calls').exists())
        finally:
            first.wait(timeout=5)

    @unittest.skipUnless(os.environ.get('GC_REAL_CLI'), 'Set GC_REAL_CLI to exercise the actual CLI against a local fake API.')
    def test_batch_actual_cli_parses_archives_against_local_api(self):
        self.batch_fixture()
        received = []
        requests = []
        class API(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"token":{"permissions":2},"user":{},"perm":2}')
            def do_POST(self):
                requests.append(self.path)
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/api/v0/count':
                    received.extend(body['hits'])
                self.send_response(202 if self.path.endswith('/count') else 200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok","perm":2}')
        api = ThreadingHTTPServer(('127.0.0.1', 0), API)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        config = self.config/'blog-https.conf'
        with config.open('a') as f:
            f.write('\nBINARY='+shlex.quote(os.environ['GC_REAL_CLI'])+'\n')
            f.write(f'GOATCOUNTER_SITE=http://127.0.0.1:{api.server_port}\n')
            f.write('LOG_FORMAT='+shlex.quote(CUSTOM_FORMAT)+'\n')
            f.write("LOG_DATETIME='02/Jan/2006:15:04:05 -0700'\n")
        expected_paths = []
        for day, path in [('19', '/older'), ('24', '/previous'), ('25', '/yesterday')]:
            lines = []
            for method, suffix, status in [('GET', '', 200), ('HEAD', '/head', 200), ('GET', '/redirect', 301), ('GET', '/image.png', 404)]:
                expected_paths.append(path+suffix)
                lines.append(f'203.0.113.10 - - [{day}/Oct/2026:10:00:00 +0000] "{method} {path+suffix} HTTP/2.0" {status} 10 "-" "Mozilla/5.0" \n')
            line = ''.join(lines).encode()
            for p in self.root.glob(self.log.name+f'.2026-10-{day}*'):
                if not p.is_symlink():
                    p.write_bytes(gzip.compress(line) if p.suffix=='.gz' else line)
        try:
            result = self.batch('--yes')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr+'\n'+str(requests))
            self.assertEqual([hit['path'] for hit in received], expected_paths)
            self.assertTrue(all(not hit['created_at'].startswith('0001-') for hit in received))
            self.assertIn('GoatCounter CLI exited 0', result.stdout)
            self.assertIn('DEBUG import-api', result.stderr+result.stdout)
            self.assertTrue(all(v['status']=='complete' for v in json.loads(self.receipt().read_text()).values()))
            again = self.batch('--yes')
            self.assertEqual(again.returncode, 0, again.stdout+again.stderr)
            self.assertEqual(len(received), 12)
            watcher = subprocess.Popen(['bash', '-c', self.harness+'watch_monitor blog-https'], env=self.env)
            try:
                for _ in range(100):
                    descriptors = Path(f'/proc/{watcher.pid}/fd')
                    if descriptors.exists() and any(
                        os.path.realpath(fd) == str(self.log) for fd in descriptors.iterdir()
                    ):
                        break
                    time.sleep(.02)
                else:
                    self.fail('Native watcher did not open its configured log.')
                time.sleep(.2)
                live_paths = []
                with self.log.open('a') as log:
                    for index in range(100):
                        method, status, path = [
                            ('GET', 200, '/live'), ('HEAD', 200, '/live-head'),
                            ('GET', 301, '/live-redirect'), ('GET', 404, '/live.png'),
                        ][index % 4]
                        live_paths.append(path)
                        log.write(f'203.0.113.10 - - [26/Oct/2026:10:00:00 +0000] "{method} {path} HTTP/2.0" {status} 10 "-" "Mozilla/5.0" \n')
                deadline = time.monotonic()+15
                while len(received) < 112 and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertEqual([hit['path'] for hit in received[12:]], live_paths)
            finally:
                watcher.terminate()
                watcher.wait(timeout=5)
        finally:
            api.shutdown()
            api.server_close()
            thread.join(timeout=2)

    def test_install_and_watcher_preserve_paths_and_hide_token(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertNotIn(self.token, result.stdout+result.stderr)
        self.assertTrue((self.bin / 'goatcounter').exists())
        self.assertTrue((self.bin / 'goatcounter-log-monitor').exists())
        self.assertEqual(stat.S_IMODE((self.config/'blog-https.conf').stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o700)
        self.assertEqual(list(self.state.glob('.install.*')), [])
        # Loading generated shell configuration must preserve quote/metacharacter
        # data as literal strings and never execute it.
        run = subprocess.run(['bash', '-c', self.harness+'watch_monitor blog-https'],
                             env=self.env, capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 0)
        args = (self.root/'arguments').read_bytes().split(b'\0')
        self.assertIn(os.fsencode(self.log), args)
        self.assertIn(b'-site=https://logs.example.test', args)
        self.assertIn(b'-follow', args)
        self.assertFalse((self.root/'SHOULD_NOT_EXIST').exists())
        command = (self.state/'cron-suggestions.txt').read_text()
        self.assertIn(shlex.quote(str(self.bin/'goatcounter-log-monitor')), command)
        self.assertNotIn(self.token, command)

    def test_checksum_failure_does_not_install_executable(self):
        (self.root/'download.gz').write_bytes(b'bad download')
        result = self.wizard([str(self.bin)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse((self.bin/'goatcounter').exists())
        self.assertFalse(self.config.exists() and list(self.config.glob('*.conf')))

    def test_end_of_input_cancels_even_when_caller_disables_errexit(self):
        result = subprocess.run(['bash', '-c', self.harness+'set +e; main --skip-update-check'],
                                input=str(self.bin)+'\n', text=True, capture_output=True,
                                env=self.env, cwd=self.root, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Input ended', result.stderr)
        self.assertLess(len(result.stderr), 2000)
        self.assertEqual(list(self.state.glob('.install.*')), [])

    def test_rejects_release_url_from_another_repository(self):
        release = json.loads((self.root/'release.json').read_text())
        release['assets'][0]['browser_download_url'] = 'https://example.test/other.gz'
        (self.root/'release.json').write_text(json.dumps(release))
        result = self.wizard([str(self.bin)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unexpected release download URL', result.stderr)
        self.assertFalse((self.bin/'goatcounter').exists())

    def test_token_retry_and_multiple_monitors(self):
        inputs = [str(self.bin), 'blog-https', 'https://logs.example.test', 'BAD-KEY', '',
                  self.token, str(self.log), '', '', 'y',
                  'blog-http', '', '', str(self.log), '', '', '', 'panel']
        result = self.wizard(inputs)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('HTTP 403', result.stderr)
        self.assertNotIn(self.token, result.stdout+result.stderr)
        self.assertEqual(len(list(self.config.glob('*.conf'))), 2)
        self.assertEqual((self.state/'cron-suggestions.txt').read_text().count('*/5'), 2)

    def test_crontab_preserves_existing_jobs_and_backups(self):
        result = self.wizard(self.inputs('crontab')+['y'])
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        cron = (self.root/'installed-crontab').read_text()
        self.assertIn('existing-job', cron)
        self.assertIn('# goatcounter-log-monitor:blog-https', cron)
        backups = list(self.state.glob('crontab-backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertIn('existing-job', backups[0].read_text())

    def test_declining_crontab_changes_nothing(self):
        result = self.wizard(self.inputs('crontab')+['n'])
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertFalse((self.root/'installed-crontab').exists())

    def test_duplicate_watcher_exits_and_status_checks_lock(self):
        result = self.wizard(self.inputs())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        env = dict(self.env, GC_TEST_SLEEP='3')
        first = subprocess.Popen(['bash', '-c', self.harness+'watch_monitor blog-https'], env=env)
        try:
            for _ in range(100):
                if (self.root/'arguments').exists(): break
                time.sleep(.02)
            second = subprocess.run(['bash', '-c', self.harness+'watch_monitor blog-https'],
                                    env=env, timeout=1, capture_output=True)
            self.assertEqual(second.returncode, 0)
            status = subprocess.run(['bash', '-c', self.harness+'show_status'], env=env,
                                    text=True, capture_output=True, timeout=1)
            self.assertIn('running (lock held)', status.stdout)
        finally:
            first.wait(timeout=5)

    def test_invalid_site_does_not_receive_token(self):
        inputs = self.inputs()
        inputs[2:3] = ['http://unsafe.example', 'https://logs.example.test/count',
                       'https://logs.example.test']
        result = self.wizard(inputs)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('without /count', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
