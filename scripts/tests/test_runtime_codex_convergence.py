"""Regression for actual command dispatch, not a fabricated command receipt."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module_at(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConvergenceTests(unittest.TestCase):
    def test_actual_executor_runs_and_binds_exact_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (root / 'tracked').write_text('fixed source\n')
            git('add', 'tracked')
            git('commit', '-qm', 'source fixture')
            sha = git('rev-parse', 'HEAD')
            env = dict(os.environ, SOURCE_SHA=sha, TESTED_SHA=sha, BASE_SHA='', HEPTA_CI_LANE='source-head')
            output = Path(temp) / 'records' / 'actual.json'
            command = [sys.executable, '-c', "print('test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out')"]
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/hepta_ci_exec.py'),
                '--output', str(output), '--minimum-tests', '1', '--', *command],
                cwd=root, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(output.read_text())
            self.assertEqual(record['status'], 'passed')
            self.assertEqual(record['command_exit_code'], 0)
            self.assertEqual(record['observed_passed_tests'], 1)
            self.assertEqual(record['before'], record['after'])
            self.assertEqual(record['tested_sha'], sha)
            bad = Path(temp) / 'records' / 'bad.json'
            env.pop('TESTED_SHA')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/hepta_ci_exec.py'),
                '--output', str(bad), '--minimum-tests', '1', '--', *command],
                cwd=root, env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(json.loads(bad.read_text())['command_exit_code'])

    def test_workflow_exports_executor_environment(self):
        text = (ROOT / '.github/workflows/runtime-codex-qualification.yml').read_text()
        self.assertIn('echo "TESTED_SHA=$(git rev-parse HEAD)"', text)
        self.assertIn('fail-fast: false', text)
        self.assertIn('if: always()', text)

    def test_target_evidence_rejects_duplicate_keys_nonfinite_and_zero_digest(self):
        module = module_at('runtime_codex_target_host_evidence')
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'input.json'
            for payload in ['{"verified":false,"verified":true}', '{"a": NaN}']:
                file.write_text(payload)
                with self.assertRaises(module.EvidenceError):
                    module.load_json(file)
        for elapsed in ['nan', 'inf', '-1', '1:60']:
            with self.assertRaises(module.EvidenceError):
                module.parse_elapsed(elapsed)
        with self.assertRaises(module.EvidenceError):
            module.require_sha('0' * 64, 'zero', module.HEX64)

    def test_typestate_cannot_abort_owner_committed(self):
        source = (ROOT / 'codex-rs/hepta-infer-worker-host/src/runtime_codex_attempt.rs').read_text()
        owner = source.split('impl Attempt<OwnerCommitted> {', 1)[1].split('impl Attempt<EffectEntered>', 1)[0]
        self.assertNotIn('abort_before_effect', owner)
        self.assertIn('impl Attempt<DurablePrepared> {\n    pub fn abort_before_effect', source)


if __name__ == '__main__':
    unittest.main()
