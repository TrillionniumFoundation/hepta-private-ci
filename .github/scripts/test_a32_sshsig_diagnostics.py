"""Portable source/controller regressions; synthetic fixtures are not native evidence."""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import a32_sshsig_collection as collection
import a32_sshsig_evidence as proof
import a32_sshsig_format_boundaries as boundaries
import a32_sshsig_guard as guard
import a32_sshsig_preflight as preflight
import a32_sshsig_qualification as runner
import a32_sshsig_source_bytes as source_bytes
import test_a32_sshsig_qualification as fixtures


class RawSourceTests(unittest.TestCase):
    def test_ordinary_eol_checkout_can_be_clean_but_full_raw_guard_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            guard.git(root, 'init', '-q'); guard.git(root, 'config', 'user.name', 'fixture')
            guard.git(root, 'config', 'user.email', 'fixture@invalid')
            guard.git(root, 'config', 'core.autocrlf', 'false')
            (root / '.gitattributes').write_bytes(b'unchanged.rs text eol=crlf\n')
            (root / 'unchanged.rs').write_bytes(b'unchanged\n')
            guard.git(root, 'add', '.'); guard.git(root, 'commit', '-qm', 'fixture')
            (root / 'unchanged.rs').unlink(); guard.git(root, 'checkout', '--', 'unchanged.rs')
            self.assertEqual((root / 'unchanged.rs').read_bytes(), b'unchanged\r\n')
            self.assertEqual(guard.git(root, 'status', '--porcelain'), b'')
            with self.assertRaisesRegex(RuntimeError, 'worktree bytes/mode.*unchanged.rs'):
                guard.check_clean(root)

    def test_windows_logical_git_executable_mode_is_not_a_posix_mode_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'regular').write_bytes(b'data')
            result = source_bytes.windows_raw_snapshot(root, {'regular': {'mode': '100755'}})
            self.assertEqual(result['regular']['mode'], '100755')
            self.assertEqual(result['regular']['blob'], guard.blob(b'data'))

    def test_windows_regular_symlink_placeholder_is_hold_not_a_real_link(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'LICENSE').write_bytes(b'../COPYING')
            with self.assertRaisesRegex(RuntimeError, 'HOLD.*real tracked symlink'):
                source_bytes.windows_raw_snapshot(root, {'LICENSE': {'mode': '120000'}})

    def test_reviewed_helper_bodies_are_byte_identical_to_accepted_source_extract(self):
        expected = {
            'blob': 'eb359d0701d711d6ee283adb229dec2a4615033f79399a461913d1bec450a1d1',
            'git': '00ee8ce40e9f7721b760754e18ea1582ad6e6dbfd64697af3c7c597af140889c',
            'inventory': 'd269ef0b1166681f15448033ce95fe1e68b9f271960e607593d98882e1ec547f',
            'snapshot': 'd6a40bab1ead50c46ec34ec58d11e0f6af5d62e14e5d3a6c2853faaffc9940ee',
            'tree_hash': 'ba715df6dcb9afc2db8d26ca23cecf3d21178cef09ed0cff7559a2287fce7d52',
            'boundary': '7a51a0226968ad54cab406bb69970598d63803c733a0048e320809cc959db0ae',
        }
        # This literal is an exact function-body digest, not a claim that the whole collector is copied.
        data = Path(boundaries.__file__).read_text(); lines = data.splitlines(keepends=True)
        actual = {node.name: hashlib.sha256(''.join(lines[node.lineno-1:node.end_lineno]).encode()).hexdigest()
                  for node in ast.parse(data).body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(actual, expected)


class AnalysisBepTests(unittest.TestCase):
    def events(self, reason='NO_BUILD', command='build'):
        identifiers = [{'started': {}}, {'targetCompleted': {'label': '//fixture:target'}}, {'buildFinished': {}}]
        events = [{'id': identifiers[0], 'children': identifiers[1:], 'started': {'command': command, 'buildToolVersion': '9.3.0'}},
                  {'id': identifiers[1], 'aborted': {'reason': reason}},
                  {'id': identifiers[2], 'finished': {'exitCode': {'name': 'SUCCESS', 'code': 0}}, 'lastMessage': True}]
        return b'\n'.join(json.dumps(event).encode() for event in events)

    def test_only_analysis_allows_expected_no_build_not_native_execution(self):
        self.assertEqual(len(proof.bep_events(self.events(), 0, 'build', allow_no_build=True)), 3)
        for reason in ('NO_BUILD', 'USER_INTERRUPTED', 'ANALYSIS_FAILURE'):
            with self.assertRaises(RuntimeError): proof.bep_events(self.events(reason, 'test'), 0, 'test')
        with self.assertRaises(RuntimeError): proof.bep_events(self.events('USER_INTERRUPTED'), 0, 'build', allow_no_build=True)
        with self.assertRaises(RuntimeError): proof.bep_events(self.events(command='test'), 0, 'test', allow_no_build=True)

    def test_configuration_path_and_no_workspace_links_are_consistent_across_analysis(self):
        for platform in ('linux', 'win32'):
            with tempfile.TemporaryDirectory() as folder:
                value = fixtures.RunnerGuardTests().fixture(folder)
                target = '//codex-rs/state:state-unit-tests'
                guard.save(value.evidence / 'source-manifest.json', {'bazel_targets': {'linux': [target], 'windows': [target]}})
                def run(name, command):
                    if name == 'configured-cquery': return (target + ' (configured)\n').encode()
                    if name == 'configured-analysis': (value.evidence / 'analysis.bep.jsonl').write_bytes(self.events())
                    return b'{}'
                value.run = Mock(side_effect=run)
                with patch.object(runner.sys, 'platform', platform), patch.dict(os.environ, {'PATH': 'selected-windows-tools'}):
                    value.graph()
                expected_path = (str(value.evidence / 'tools') + ':/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
                                 if platform == 'linux' else 'selected-windows-tools')
                expected = ['--experimental_convenience_symlinks=ignore', '--test_env=PATH=' + expected_path]
                self.assertEqual(value.state['bazel_configuration_flags'], expected)
                for call in value.run.call_args_list:
                    for flag in expected: self.assertIn(flag, call.args[1])
                self.assertEqual(value.state['analysis_bep']['expected_no_build_events'], 1)
                self.assertFalse(value.state['analysis_bep']['native_execution'])
        import inspect
        self.assertIn('*self.state["bazel_configuration_flags"]', inspect.getsource(runner.Qualification.native))


class IndependentPreflightTests(unittest.TestCase):
    token = {'schema': 'a32.sshsig-token-probe.v1', 'thread_impersonating': False, 'query_errors': [],
             'owner_capable_sid': None, 'linked_token': {'status': 'unavailable_or_query_failed'}, 'process': {}}

    def fixture(self, root):
        path = root / 'probe.py'
        path.write_text('import json\nfrom pathlib import Path\ndef main(argv):\n    with Path(argv[1]).open("x") as stream:\n        json.dump(' + repr(self.token) + ', stream)\n    return 0\n')
        return path

    def test_hash_check_precedes_execution_and_observation_is_create_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.fixture(root); output = root / 'preflight'
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                preflight.execute_probe(source, output)
            self.assertFalse(output.exists())
            env = {name: 'fixture' for name in preflight.IDENTITY_ENV.values()}
            with patch.dict(os.environ, env), patch.object(preflight, 'PROBE_SHA256', guard.digest(source.read_bytes())):
                self.assertEqual(preflight.execute_probe(source, output), 0)
                with self.assertRaises(FileExistsError): preflight.execute_probe(source, output)
            receipt = json.loads((output / 'receipt.json').read_bytes())
            self.assertFalse(receipt['source_admitted']); self.assertFalse(receipt['native_functional_qualification'])

    def test_original_probe_failure_survives_receipt_write_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'probe.py'
            source.write_text('def main(argv):\n    raise ValueError("original probe failure")\n')
            env = {name: 'fixture' for name in preflight.IDENTITY_ENV.values()}
            original = Path.open
            def open_path(path, *args, **kwargs):
                if path.name == 'receipt.json': raise OSError('receipt denied')
                return original(path, *args, **kwargs)
            with patch.dict(os.environ, env), patch.object(preflight, 'PROBE_SHA256', guard.digest(source.read_bytes())), patch.object(Path, 'open', open_path):
                with self.assertRaisesRegex(ValueError, 'original probe failure') as caught:
                    preflight.execute_probe(source, root / 'preflight')
            self.assertTrue(any('receipt denied' in note for note in caught.exception.__notes__))

    def test_consume_once_then_native_does_not_requery_or_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = self.fixture(root); incoming = root / 'preflight'
            env = {name: 'fixture' for name in preflight.IDENTITY_ENV.values()}
            with patch.dict(os.environ, env), patch.object(preflight, 'PROBE_SHA256', guard.digest(source.read_bytes())), patch.object(runner.sys, 'platform', 'win32'):
                preflight.execute_probe(source, incoming)
                value = fixtures.RunnerGuardTests().fixture(root / 'evidence'); value.evidence.mkdir()
                value.probe(incoming); before = (value.evidence / 'token.json').read_bytes()
                with self.assertRaisesRegex(RuntimeError, 'already consumed'): value.probe(incoming)
                value.state.update(candidate={}, same_run_locks_verified=True, lane='windows')
                value.versions = Mock(); value.probe = Mock(side_effect=AssertionError('must not requery'))
                value.graph = Mock(side_effect=RuntimeError('bounded test stop before native commands'))
                with self.assertRaisesRegex(RuntimeError, 'bounded test stop'): value.native()
                value.probe.assert_not_called()
                self.assertEqual((value.evidence / 'token.json').read_bytes(), before)
                self.assertFalse(value.state['token_probe']['normal_user_execution_proved'])

    def test_workflow_has_exact_preflight_admit_consume_bootstrap_order(self):
        path = Path(__file__).parent.parent / 'workflows/a32-sshsig-custody-qualification.yml'
        text = path.read_text().split('  native-windows:', 1)[1]
        positions = [text.index('id: ' + name + '\n') for name in ('preflight', 'source', 'probe', 'download', 'consume', 'build', 'dotslash', 'bazel', 'rust', 'native')]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count('a32_sshsig_preflight.py '), 1)
        self.assertEqual(text.count('a32_sshsig_qualification.py probe '), 1)


class PartialNestedTests(unittest.TestCase):
    def test_unmatched_native_or_version_admission_latches_partial_despite_outer_exit(self):
        for kind in ('native', 'version-query'):
            with tempfile.TemporaryDirectory() as folder:
                value = fixtures.RunnerGuardTests().fixture(folder)
                value.state['input_verified'] = True
                value.commands = [{'name': 'outer', 'exit_code': 1}]
                journal = Path(folder) / 'acquisition-controls.no-kill.jsonl'
                journal.write_text(json.dumps({'event': kind + '-admitted'}) + '\n')
                value.collect(); value.guard.assert_not_called()
                receipt = json.loads((Path(folder + '-sealed') / 'PARTIAL-NOT-SETTLED.json').read_bytes())
                self.assertEqual(receipt['state']['nested_child_uncertainty'][0]['unmatched_admission'], kind + '-admitted')
                # Owned fixture cleanup only; sealed evidence is a fixture, not a native receipt.
                import shutil
                shutil.rmtree(folder + '-sealed')

    def test_complete_pairs_are_settled_and_malformed_journals_are_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'recovery-controls.no-kill.jsonl'
            path.write_text('\n'.join(json.dumps({'event': event}) for event in ('native-admitted', 'native-finished')))
            self.assertEqual(collection.nested_child_uncertainty(root), [])
            path.write_text('{partial')
            self.assertTrue(collection.nested_child_uncertainty(root))

    def test_active_external_formatter_log_has_bounded_incomplete_prefix_not_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); evidence = root / 'evidence'; evidence.mkdir()
            value = fixtures.RunnerGuardTests().fixture(evidence)
            value.state.update(input_verified=True, format_writer_may_be_active=True)
            live = root / 'a32-format-live-fixture'; live.mkdir()
            (live / 'generate-format-only.log').write_bytes(b'raw active formatter prefix')
            (live / 'unrelated-secret').write_bytes(b'must not copy')
            guard.save(evidence / 'format-discovery/receipt.json', {'live_logs_not_uploaded': str(live)})
            value.collect(); value.guard.assert_not_called()
            sealed = root / 'evidence-sealed'
            self.assertEqual((sealed / 'partial-prefixes/format-discovery-live/generate-format-only.log').read_bytes(), b'raw active formatter prefix')
            self.assertFalse(any(path.name == 'unrelated-secret' for path in sealed.rglob('*')))
            receipt = json.loads((sealed / 'PARTIAL-NOT-SETTLED.json').read_bytes())
            self.assertTrue(all(not item['complete'] for item in receipt['diagnostic_prefixes_only']))


if __name__ == '__main__':
    unittest.main()
