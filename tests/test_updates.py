#!/usr/bin/env python3
"""Real local Git repositories test safe installer updates; no network needed."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='goatcounter-update-test-')
        self.root = Path(self.temp.name)
        self.remote = self.root/'upstream.git'
        self.seed = self.root/'seed'
        self.clone = self.root/'installed source with spaces'
        self.state = self.root/'private state'
        self.state.mkdir()
        (self.state/'receipts.json').write_text('private receipts')
        self.git('init', '--bare', '--initial-branch=main', str(self.remote))
        self.git('init', '--initial-branch=main', str(self.seed))
        for key, value in [('user.name', 'Test Fixture'), ('user.email', 'fixture@example.invalid')]:
            self.git('-C', str(self.seed), 'config', key, value)
        (self.seed/'VERSION').write_text('0.1.0\n')
        shutil.copyfile(ROOT/'tests/fixtures/updated-installer', self.seed/'install.sh')
        self.git('-C', str(self.seed), 'add', '.')
        self.git('-C', str(self.seed), 'commit', '-m', 'Initial fixture')
        self.git('-C', str(self.seed), 'remote', 'add', 'origin', str(self.remote))
        self.git('-C', str(self.seed), 'push', '-u', 'origin', 'main')
        self.git('clone', str(self.remote), str(self.clone))
        for key, value in [('user.name', 'Test Fixture'), ('user.email', 'fixture@example.invalid')]:
            self.git('-C', str(self.clone), 'config', key, value)
        self.env = dict(os.environ, GC_INSTALLER=str(ROOT/'install.sh'),
                        GC_UPDATE_ROOT=str(self.clone), GC_UPDATE_ORIGIN=str(self.remote),
                        GC_UPDATE_STATE=str(self.state), GC_RESTART_MARKER=str(self.root/'restarted'))

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', *args], text=True, capture_output=True, check=True).stdout.strip()

    def publish(self):
        (self.seed/'VERSION').write_text('0.2.0\n')
        self.git('-C', str(self.seed), 'add', 'VERSION')
        self.git('-C', str(self.seed), 'commit', '-m', 'Update fixture')
        self.git('-C', str(self.seed), 'push', 'origin', 'main')

    def update(self, answer='y'):
        command = ('source "$GC_INSTALLER"; PROJECT_ROOT="$GC_UPDATE_ROOT"; '
                   'PROJECT_UPSTREAM="$GC_UPDATE_ORIGIN"; STATE_DIR="$GC_UPDATE_STATE"; '
                   'update_project update --monitor-only')
        return subprocess.run(['bash', '-c', command], env=self.env,
                              input=answer+'\n', text=True, capture_output=True, timeout=10)

    def test_no_update_does_not_restart(self):
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('up to date', result.stdout)
        self.assertFalse((self.root/'restarted').exists())

    def test_fast_forward_updates_installer_and_restarts_without_touching_state(self):
        self.publish()
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.clone/'VERSION').read_text(), '0.2.0\n')
        self.assertEqual((self.root/'restarted').read_text().splitlines(), ['--skip-update-check', 'update', '--monitor-only'])
        self.assertEqual((self.state/'receipts.json').read_text(), 'private receipts')

    def test_declining_leaves_source_unchanged(self):
        self.publish()
        result = self.update('n')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.clone/'VERSION').read_text(), '0.1.0\n')

    def test_dirty_checkout_is_not_overwritten(self):
        self.publish()
        (self.clone/'local-notes.txt').write_text('keep me')
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Local source changes', result.stderr)
        self.assertEqual((self.clone/'local-notes.txt').read_text(), 'keep me')

    def test_divergence_is_not_reset_or_merged(self):
        (self.clone/'local.txt').write_text('local change')
        self.git('-C', str(self.clone), 'add', 'local.txt')
        self.git('-C', str(self.clone), 'commit', '-m', 'Local fixture commit')
        before = self.git('-C', str(self.clone), 'rev-parse', 'HEAD')
        self.publish()
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('history diverged', result.stderr)
        self.assertEqual(self.git('-C', str(self.clone), 'rev-parse', 'HEAD'), before)

    def test_unexpected_remote_is_rejected(self):
        self.git('-C', str(self.clone), 'remote', 'set-url', 'origin', 'https://example.invalid/other.git')
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected utility repository', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
