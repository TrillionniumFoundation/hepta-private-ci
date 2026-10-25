import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cargo_deny_diagnostic as d


class DiagnosticTests(unittest.TestCase):
    def test_retained_bytes_and_bound(self):
        for size in [0, 4, 8, 9, 10000]:
            data = bytes(i % 256 for i in range(size))
            s = d.Stream(4)
            for offset in range(0, size, 3):
                s.feed(data[offset:offset + 3])
            result = s.finish()
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(result['bytes'], size)
            self.assertEqual(result['truncated'], size > 8)
            self.assertEqual(s.retained(), data if size <= 8 else data[:4] + data[-4:])

    def test_cross_chunk_and_truncation_secret_withheld(self):
        data = b'normal\nhttps://user:credential@github.com/private\n' + b'x' * 100
        s = d.Stream(4)
        for byte in data:
            s.feed(bytes([byte]))
        s.finish()
        self.assertTrue(s.suspect)
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'public'
            result = {'stop': None}
            d.publish(target, [('run', result, [s, d.Stream()])], True)
            self.assertFalse(result['raw_published'])
            self.assertEqual(list(target.iterdir()), [])

    def test_sensitive_patterns(self):
        for data in [b'ghp_abcdefgh12345', b'-----BEGIN RSA PRIVATE KEY-----',
                     b'https://private.invalid/path', b'https://github.com/public?token=abc',
                     b'password=123456789', b'ssh://git@github.com/x']:
            self.assertTrue(d.suspicious(data), data)
        self.assertFalse(d.suspicious(b'https://github.com/rustsec/advisory-db'))

    def test_very_long_line_fails_closed(self):
        s = d.Stream(4)
        s.feed(b'a' * 70000)
        s.finish()
        self.assertTrue(s.suspect)

    def test_input_gate_failure_prevents_raw_publication(self):
        s = d.Stream()
        s.feed(b'public fixture')
        s.finish()
        with tempfile.TemporaryDirectory() as td:
            result = {'stop': None}
            d.publish(Path(td) / 'public', [('build', result, [s, d.Stream()])], False)
            self.assertFalse(result['raw_published'])

    def test_stopped_capture_prevents_raw_publication(self):
        with tempfile.TemporaryDirectory() as td:
            result = {'stop': 'timeout'}
            d.publish(Path(td) / 'public', [('run', result, [d.Stream(), d.Stream()])], True)
            self.assertFalse(result['raw_published'])

    def test_simultaneous_streams_and_nonzero_exit(self):
        code = "import os; os.write(1,b'a'*100000); os.write(2,b'b'*100000); raise SystemExit(7)"
        result, streams = d.capture([sys.executable, '-c', code], os.environ.copy(), 5)
        self.assertEqual(result['exit'], 7)
        self.assertIsNone(result['stop'])
        self.assertEqual([s.count for s in streams], [100000, 100000])

    def test_launch_failure(self):
        result, _ = d.capture(['/nonexistent-diagnostic-fixture'], {}, 1)
        self.assertIsNone(result['exit'])
        self.assertEqual(result['stop'], 'launch_failed')

    def test_timeout(self):
        result, _ = d.capture([sys.executable, '-c', 'import time; time.sleep(30)'], os.environ.copy(), 0.1)
        self.assertEqual(result['stop'], 'timeout')
        self.assertNotEqual(result['exit'], 0)

    def test_environment_allowlist(self):
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'secret', 'SSH_AUTH_SOCK': 'socket'}):
            env = d.minimal_env(Path('/fixture'))
        self.assertNotIn('GITHUB_TOKEN', env)
        self.assertNotIn('SSH_AUTH_SOCK', env)

    def test_identity_rejects_wrong_head_tree_and_dirty_source(self):
        for values in [[b'wrong\n'], [b'commit\n', b'wrong\n'], [b'commit\n', b'tree\n', b' M file']]:
            with mock.patch.object(d, 'git', side_effect=values):
                with self.assertRaises(ValueError):
                    d.identity(Path('/fixture'), 'commit', 'tree', {})

    def test_input_credential_url_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Cargo.toml').write_text('git="https://user:secret@github.com/repo"')
            with mock.patch.object(d, 'git', return_value=b'Cargo.toml\0'):
                self.assertFalse(d.input_gate(root, {}))

    def test_advisory_bounded_head_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cargo = Path(td)
            head = cargo / 'advisory-dbs/db/.git/HEAD'
            head.parent.mkdir(parents=True)
            head.write_text('a' * 40 + '\n')
            self.assertEqual(d.advisory_revisions(cargo), ['a' * 40])
            head.unlink()
            head.symlink_to('/etc/passwd')
            self.assertIsNone(d.advisory_revisions(cargo))

    def test_unavailable_advisory_is_null(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(d.advisory_revisions(Path(td)))

    def test_source_snapshot_detects_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            file = root / 'Cargo.lock'
            file.write_text('old')
            with mock.patch.object(d, 'git', return_value=b'Cargo.lock\0'):
                old = d.snapshot(root, {})
                file.write_text('new')
                self.assertNotEqual(old, d.snapshot(root, {}))


    def exercise_main(self, build_exit=0, run_exit=0, changed=False, gate=True, cleanup_exit=0, cleanup_stop=None, control_change=False, run_stop=None, action_error=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, action, temp = [root / name for name in ['source', 'action', 'temp']]
            for path in [source / 'codex-rs', action, temp]:
                path.mkdir(parents=True)
            (source / 'codex-rs/Cargo.lock').write_text('fixture')
            for name in ['Dockerfile', 'entrypoint.sh']:
                (action / name).write_text('fixture')
            calls = []
            def fake_capture(argv, env, seconds, disk=None, abort=None):
                calls.append(argv)
                if argv[1] == 'run' and run_stop and abort:
                    abort()
                streams = [d.Stream(), d.Stream()]
                streams[0].feed(b'public result')
                code = build_exit if argv[1] == 'build' else run_exit if argv[1] == 'run' else cleanup_exit
                return {'argv': argv, 'exit': code, 'stop': cleanup_stop if argv[1] == 'rm' else run_stop if argv[1] == 'run' else None,
                        'streams': [stream.finish() for stream in streams]}, streams
            with mock.patch.object(d, 'control_receipt', side_effect=[{'head': 'fixed'}, {'head': 'changed' if control_change else 'fixed'}]), mock.patch.object(d, 'action_identity', return_value={'tag_object': d.ACTION}, side_effect=action_error), mock.patch.object(d, 'identity'), mock.patch.object(d, 'BLOBS', {}), \
                 mock.patch.object(d, 'input_gate', return_value=gate), \
                 mock.patch.object(d, 'snapshot', side_effect=['before', 'after' if changed else 'before']), \
                 mock.patch.object(d, 'git', return_value=b''), \
                 mock.patch.object(d, 'checked', side_effect=lambda argv, env: b'sha256:' + b'a' * 64 if argv[1] == 'image' else f'exited {run_exit} false'.encode()), \
                 mock.patch.object(d.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 20 * 1024**3})()), \
                 mock.patch.object(d, 'capture', side_effect=fake_capture):
                code = d.main(source, action, temp, root, "a" * 40, "a" * 40)
            receipt = json.loads((temp / 'public/receipt.json').read_text())
            return code, receipt, calls

    def test_main_preserves_run_failure_and_exact_arguments(self):
        code, receipt, calls = self.exercise_main(run_exit=7)
        self.assertEqual(code, 7)
        self.assertEqual(receipt['exit_requested'], 7)
        runs = [argv for argv in calls if argv[1] == 'run']
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][-12:], d.ARGS)
        self.assertIsNone(receipt['tool_actual'])
        self.assertIsNone(receipt['advisory_revisions'])
        for forbidden in ['--privileged', '--network=host', '/var/run/docker.sock', '--cap-add']:
            self.assertFalse(any(forbidden in value for value in runs[0]))

    def test_build_failure_never_runs_container(self):
        code, receipt, calls = self.exercise_main(build_exit=9)
        self.assertEqual(code, 9)
        self.assertFalse(any(argv[1] == 'run' for argv in calls))
        self.assertEqual(receipt['records'][0]['exit'], 9)

    def test_source_drift_never_passes(self):
        code, receipt, _ = self.exercise_main(changed=True)
        self.assertEqual(code, 125)
        self.assertTrue(receipt['source_changed'])
        self.assertEqual(receipt['records'][-1]['exit'], 0)

    def test_input_failure_never_builds_or_runs(self):
        code, receipt, calls = self.exercise_main(gate=False)
        self.assertEqual(code, 125)
        self.assertFalse(any(argv[1] in ['build', 'run'] for argv in calls))
        self.assertFalse(receipt['inputs_ok'])

    def test_toml_comments_not_mistaken_for_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.git').mkdir()
            (root / '.git/config').write_text('[core]\n repositoryformatversion = 0\n')
            (root / 'Cargo.toml').write_text('# token=not-a-real-secret\n[package]\nname="fixture"\n')
            with mock.patch.object(d, 'git', return_value=b'Cargo.toml\0'):
                self.assertTrue(d.input_gate(root, {}))


    def test_cleanup_failure_withholds_and_does_not_retry(self):
        for code, stop in [(1, None), (0, 'timeout')]:
            result, receipt, calls = self.exercise_main(run_exit=7, cleanup_exit=code, cleanup_stop=stop)
            self.assertEqual(result, 125)
            self.assertEqual(receipt['records'][-1]['exit'], 7)
            self.assertEqual(receipt['cleanup']['exit'], code)
            self.assertEqual(receipt['cleanup']['stop'], stop)
            self.assertFalse(receipt['cleanup_confirmed'])
            self.assertEqual(sum(argv[1] == 'rm' for argv in calls), 1)
            self.assertFalse(any(r['raw_published'] for r in receipt['records']))
            self.assertFalse(any('diagnostic_summaries' in r for r in receipt['records']))

    def test_control_change_fails_and_withholds(self):
        result, receipt, _ = self.exercise_main(control_change=True)
        self.assertEqual(result, 125)
        self.assertFalse(receipt['control_unchanged'])
        self.assertFalse(any(r['raw_published'] for r in receipt['records']))
        self.assertFalse(any('diagnostic_summaries' in r for r in receipt['records']))

    def test_control_sha_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            d.control_receipt(Path('/unused'), 'a' * 40, 'b' * 40, {})

    def test_closed_pipes_live_child_obeys_deadline(self):
        code = 'import os,time; os.close(1); os.close(2); time.sleep(30)'
        result, _ = d.capture([sys.executable, '-c', code], os.environ.copy(), 0.1)
        self.assertEqual(result['stop'], 'timeout')
        self.assertNotEqual(result['exit'], 0)


    def test_abort_cleanup_not_repeated_from_finally(self):
        result, receipt, calls = self.exercise_main(run_exit=-15, run_stop='timeout', cleanup_exit=1)
        self.assertEqual(result, 125)
        self.assertEqual(sum(argv[1] == 'rm' for argv in calls), 1)
        self.assertEqual(receipt['records'][-1]['exit'], -15)
        self.assertFalse(receipt['cleanup_confirmed'])

    def test_control_real_git_dirty_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in d.CONTROL_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip()
            before = d.control_receipt(root, sha, sha, os.environ.copy())
            self.assertEqual(set(before['files_sha256']), set(d.CONTROL_FILES))
            (root / d.CONTROL_FILES[0]).write_text('changed')
            with self.assertRaises(ValueError):
                d.control_receipt(root, sha, sha, os.environ.copy())


    def test_exact_six_lock_sources_and_patch_key(self):
        sources = ['git+https://github.com/openai-oss-forks/crossterm?rev=45fecb9508105988f42fe6ff0441783ed3717f92#45fecb9508105988f42fe6ff0441783ed3717f92', 'git+https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee#4253de9faabb4e5c6d81d946a5e35a90f87347ee', 'git+https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee#4253de9faabb4e5c6d81d946a5e35a90f87347ee', 'git+https://github.com/dzbarsky/rules_rust?rev=b56cbaa8465e74127f1ea216f813cd377295ad81#b56cbaa8465e74127f1ea216f813cd377295ad81', 'git+https://github.com/openai-oss-forks/tokio-tungstenite?rev=0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186#0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186', 'git+https://github.com/openai-oss-forks/tungstenite-rs?rev=4fffad30fe373adbdcffab9545e9e9bf4f2fc19f#4fffad30fe373adbdcffab9545e9e9bf4f2fc19f']
        parsed = {'package': [{'source': value} for value in sources]}
        before = json.dumps(parsed, sort_keys=True)
        self.assertFalse(d.source_sensitive(parsed, 'Cargo.lock'))
        self.assertEqual(json.dumps(parsed, sort_keys=True), before)
        for value in sources:
            self.assertTrue(d.reviewed_source_url(value, 'lock_source'))
            self.assertTrue(d.suspicious(value.encode()))  # runtime unchanged
        key = 'ssh://git@github.com/openai-oss-forks/tungstenite-rs.git'
        self.assertTrue(d.reviewed_source_url(key, 'patch_key'))
        self.assertFalse(d.source_sensitive({'patch': {key: {'version': '1'}}}, 'Cargo.toml'))
        self.assertTrue(d.source_sensitive({'dependencies': {'x': {'git': key}}}, 'Cargo.toml'))
        self.assertTrue(d.suspicious(key.encode()))

    def test_static_exception_negative_variants(self):
        lock = 'git+https://github.com/owner/repo?rev=' + 'a' * 40 + '#' + 'b' * 40
        patch = 'ssh://git@github.com/owner/repo'
        variants = [
            (lock.replace('?rev=', '?token=x&rev='), 'lock_source'),
            (lock.replace('#', '&extra=x#'), 'lock_source'),
            (lock.replace('github.com', 'private.invalid'), 'lock_source'),
            (lock.replace('github.com', 'git%40github.com'), 'lock_source'),
            (lock.replace('github.com', 'user:password@github.com'), 'lock_source'),
            (lock.replace('a' * 40, 'a' * 39), 'lock_source'),
            (lock.replace('b' * 40, 'xyz'), 'lock_source'),
            (lock.replace('/owner/repo', '/owner/../repo'), 'lock_source'),
            (lock.replace('/owner/repo', '/owner/%2e%2e'), 'lock_source'),
            (patch + '?rev=x', 'patch_key'), (patch + '#x', 'patch_key'),
            (patch.replace('git@', 'git:password@'), 'patch_key'),
            (patch.replace('git@', '%67it@'), 'patch_key'),
            (patch.replace('/owner/repo', '/owner/..'), 'patch_key'),
            (patch.replace('github.com', 'github.com.evil.invalid'), 'patch_key'),
        ]
        for value, kind in variants:
            self.assertFalse(d.reviewed_source_url(value, kind), (value, kind))


    def test_annotated_tag_is_not_head_and_peels_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            config = ['git', '-C', str(root), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid']
            subprocess.run(config + ['commit', '--allow-empty', '-qm', 'fixture'], check=True)
            subprocess.run(config + ['tag', '-a', 'fixture', '-m', 'fixed public tag'], check=True)
            def rev(name):
                return subprocess.check_output(['git', '-C', str(root), 'rev-parse', name]).decode().strip()
            tag, commit, tree = rev('fixture'), rev('HEAD'), rev('HEAD^{tree}')
            self.assertNotEqual(tag, commit)
            with self.assertRaises(ValueError):
                d.identity(root, tag, tree, os.environ.copy())  # original bug
            with mock.patch.object(d, 'ACTION', tag), mock.patch.object(d, 'ACTION_COMMIT', commit), mock.patch.object(d, 'ACTION_TREE', tree):
                receipt = d.action_identity(root, os.environ.copy())
                self.assertEqual(receipt['tag_object'], tag)
                self.assertEqual(receipt['peeled_commit'], commit)
                self.assertEqual(receipt['tree'], tree)
                for wrong in ['ACTION_COMMIT', 'ACTION_TREE']:
                    with mock.patch.object(d, wrong, '0' * 40):
                        with self.assertRaises(ValueError):
                            d.action_identity(root, os.environ.copy())
            with mock.patch.object(d, 'ACTION', commit):
                with self.assertRaises(ValueError):
                    d.action_identity(root, os.environ.copy())

    def test_bounded_metadata_error_has_no_raw_output_or_argv(self):
        with self.assertRaises(d.MetadataFailure) as caught:
            d.checked([sys.executable, '-c', 'import sys; print("secret-fixture"); sys.exit(7)'], os.environ.copy())
        self.assertEqual(set(caught.exception.safe), {'exit', 'stop', 'stdout_bytes', 'stderr_bytes'})
        self.assertEqual(caught.exception.safe['exit'], 7)
        self.assertNotIn('secret-fixture', str(caught.exception.safe))


    def test_fixed_stage_identifies_action_identity_failure(self):
        code, receipt, calls = self.exercise_main(action_error=ValueError('private fixture not exported'))
        self.assertEqual(code, 125)
        self.assertEqual(receipt['stage'], 'action_identity')
        self.assertTrue(receipt['collector_error'])
        self.assertEqual(receipt['records'], [])
        self.assertNotIn('private fixture', json.dumps(receipt))
        self.assertFalse(any(argv[1] in ['build', 'run'] for argv in calls))


    def test_all_known_headers_are_counted_for_each_severity(self):
        counter = d.DiagnosticCounts()
        for severity in d.SEVERITIES:
            for code in d.DIAGNOSTIC_CODES:
                counter.feed(f'{severity}[{code}]: ignored text\n'.encode())
        counter.finish()
        receipt = counter.receipt(True)
        self.assertTrue(receipt['known_header_observed'])
        self.assertFalse(receipt['cargo_substage_success_proven'])
        for counts in receipt['counts'].values():
            self.assertEqual(set(counts.values()), {1})

    def test_header_and_sgr_every_chunk_boundary(self):
        data = b'\x1b[31merror\x1b[0m[vulnerability]: secret-fixture\n'
        for split in range(len(data) + 1):
            counter = d.DiagnosticCounts()
            counter.feed(data[:split])
            counter.feed(data[split:])
            counter.finish()
            receipt = counter.receipt(True)
            self.assertEqual(receipt['counts']['error']['vulnerability'], 1)
            self.assertNotIn('secret-fixture', json.dumps(receipt))
            self.assertEqual(receipt['invalid_ansi_lines_skipped'], 0)

    def test_secret_messages_withhold_raw_but_only_emit_fixed_counts(self):
        stream = d.Stream(8)
        stream.feed(b'error[unlicensed]: token=privatecredential123 https://u:p@private.invalid/x\n')
        stream.finish()
        with tempfile.TemporaryDirectory() as td:
            result = {'stop': None}
            target = Path(td) / 'public'
            d.publish(target, [('run', result, [stream, d.Stream()])], True)
            self.assertFalse(result['raw_published'])
            self.assertEqual(list(target.iterdir()), [])
            summary = result['diagnostic_summaries'][0]
            self.assertEqual(summary['counts']['error']['unlicensed'], 1)
            text = json.dumps(summary)
            for secret in ['privatecredential123', 'private.invalid', 'token=', 'https://']:
                self.assertNotIn(secret, text)

    def test_unknown_code_is_only_a_number(self):
        counter = d.DiagnosticCounts()
        counter.feed(b'error[secret-fixture-code]: ignored\n')
        counter.finish()
        receipt = counter.receipt(True)
        self.assertEqual(receipt['unknown_code_headers'], 1)
        self.assertNotIn('secret-fixture-code', json.dumps(receipt))
        self.assertFalse(receipt['known_header_observed'])

    def test_longline_skipped_whole_not_tail_header(self):
        counter = d.DiagnosticCounts()
        counter.feed(b'error[banned]: ' + b'x' * 65536)
        counter.feed(b'error[vulnerability]: fake-tail\nwarning[duplicate]: real\n')
        counter.finish()
        receipt = counter.receipt(True)
        self.assertEqual(receipt['overlong_lines_skipped'], 1)
        self.assertEqual(receipt['counts']['error']['banned'], 0)
        self.assertEqual(receipt['counts']['error']['vulnerability'], 0)
        self.assertEqual(receipt['counts']['warning']['duplicate'], 1)
        self.assertEqual(counter.pending, b'')

    def test_invalid_ansi_skips_entire_line(self):
        for line in [b'\x1b[31Kerror[banned]: x', b'error[banned]: x\x1b]8;;secret\x07',
                     b'error[banned]: x\x1b[', b'\x1b[9999merror[banned]: x']:
            counter = d.DiagnosticCounts()
            for byte in line:
                counter.feed(bytes([byte]))
            counter.finish()
            receipt = counter.receipt(True)
            self.assertEqual(receipt['invalid_ansi_lines_skipped'], 1)
            self.assertFalse(receipt['known_header_observed'])

    def test_counts_independent_of_raw_head_tail_truncation(self):
        stream = d.Stream(8)
        stream.feed(b'error[banned]: first\n' + b'harmless\n' * 1000 + b'warning[duplicate]: last')
        meta = stream.finish()
        self.assertTrue(meta['truncated'])
        self.assertLessEqual(len(stream.retained()), 16)
        receipt = stream.diagnostics.receipt(True)
        self.assertEqual(receipt['counts']['error']['banned'], 1)
        self.assertEqual(receipt['counts']['warning']['duplicate'], 1)
        stream.finish()
        self.assertEqual(stream.diagnostics.receipt(True), receipt)

    def test_counter_saturation_bounded(self):
        counter = d.DiagnosticCounts()
        counter.counts['error']['banned'] = counter.LIMIT
        counter.unknown_code_headers = counter.LIMIT
        counter.feed(b'error[banned]: x\nerror[unknown-fixture]: x\n')
        counter.finish()
        receipt = counter.receipt(True)
        self.assertTrue(receipt['count_saturated'])
        self.assertEqual(receipt['counts']['error']['banned'], 2**32 - 1)
        self.assertEqual(receipt['unknown_code_headers'], 2**32 - 1)

    def test_no_code_text_does_not_claim_substage(self):
        counter = d.DiagnosticCounts()
        counter.feed(b'error: rustup failure fixture\ninfo: cargo-deny succeeded fixture\n')
        counter.finish()
        receipt = counter.receipt(True)
        self.assertFalse(receipt['known_header_observed'])
        self.assertFalse(receipt['cargo_substage_success_proven'])
        self.assertEqual(receipt['unknown_code_headers'], 0)

    def test_summary_incomplete_on_stop_and_withheld_on_failed_safety_gate(self):
        stream = d.Stream()
        stream.feed(b'error[banned]: fixture\n')
        stream.finish()
        with tempfile.TemporaryDirectory() as td:
            result = {'stop': 'timeout'}
            d.publish(Path(td) / 'public', [('run', result, [stream, d.Stream()])], True)
            self.assertFalse(result['diagnostic_summaries'][0]['summary_complete'])
            self.assertFalse(result['raw_published'])
        with tempfile.TemporaryDirectory() as td:
            result = {'stop': None}
            d.publish(Path(td) / 'public', [('run', result, [stream, d.Stream()])], False)
            self.assertTrue(result['diagnostic_summary_withheld'])
            self.assertNotIn('diagnostic_summaries', result)


if __name__ == '__main__':
    unittest.main()
