"""Source identity checks against real temporary Git repositories."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'apps/hepta-native/tools/prepare_current_source.py'
spec = importlib.util.spec_from_file_location('native_source_under_test', SCRIPT)
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'apps/hepta-native'
        self.app.mkdir(parents=True)
        self.file = self.app / 'source.rs'
        self.file.write_text('fn main() {}\n', encoding='utf-8')
        self.git('init', '--quiet')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.git('checkout', '--quiet', '-b', 'work/ui-native-closure-20260927')
        self.commit('source')
        for name, value in [('ROOT', self.root), ('APP', self.app), ('INTEGRATION_FILES', ())]:
            patched = patch.object(source, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        env = patch.dict(os.environ, HEPTA_UI_NATIVE_WRITE_BRANCH='work/ui-native-closure-20260927')
        env.start()
        self.addCleanup(env.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            source.fingerprint(True)
        self.commit('metadata')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '--quiet', '-m', message)

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            source.fingerprint(False)

    def test_round_trip(self):
        self.check()

    def test_untracked_build_output_is_not_a_source(self):
        (self.app / 'transient.log').write_text('not source')
        self.check()

    def test_dirty_tracked_file_refused(self):
        self.file.write_text('changed')
        with self.assertRaises(RuntimeError): self.check()

    def test_deleted_tracked_file_refused(self):
        self.file.unlink()
        with self.assertRaises(RuntimeError): self.check()

    def test_new_committed_source_needs_refreeze(self):
        (self.app / 'new.rs').write_text('fn added() {}')
        self.commit('new source')
        with self.assertRaises(RuntimeError): self.check()

    @unittest.skipIf(os.name == 'nt', 'symlink creation requires host privilege')
    def test_symlink_substitution_refused(self):
        target = self.root / 'external.rs'
        target.write_bytes(self.file.read_bytes())
        self.file.unlink()
        self.file.symlink_to(target)
        with self.assertRaises(RuntimeError): self.check()

    def test_nonpromoting_flags_are_strict_booleans(self):
        path = self.app / 'CURRENT_SOURCE.json'
        original = path.read_bytes()
        for field in ('productionQualified', 'releaseAuthorized'):
            for value in (True, None, 0):
                data = json.loads(original)
                data[field] = value
                path.write_text(json.dumps(data))
                with self.assertRaises(RuntimeError): self.check()
        path.write_bytes(original)
        self.check()

    def test_stale_candidate_branch_is_rejected(self):
        path = self.app / 'CURRENT_SOURCE.json'
        data = json.loads(path.read_text())
        data['canonicalBranch'] = 'work/stale-candidate'
        path.write_text(json.dumps(data))
        with self.assertRaises(RuntimeError): self.check()

    def test_unregistered_write_branch_refused(self):
        with patch.dict(os.environ, HEPTA_UI_NATIVE_WRITE_BRANCH='main'):
            with self.assertRaises(RuntimeError): source.require_branch()

    def test_wrong_current_branch_refused(self):
        self.git('checkout', '--quiet', '-b', 'unrelated-owner')
        with self.assertRaises(RuntimeError): source.require_branch()

    def test_metadata_only_commit_does_not_change_source_identity(self):
        source_id = self.git('log', '-1', '--format=%H', '--', *source.SOURCE_LOG_PATHS)
        path = self.app / 'CURRENT_SOURCE.json'
        path.write_text(path.read_text(encoding="utf-8") + '\n')
        self.commit('metadata only')
        self.assertEqual(source_id, self.git('log', '-1', '--format=%H', '--', *source.SOURCE_LOG_PATHS))


if __name__ == '__main__':
    unittest.main()
