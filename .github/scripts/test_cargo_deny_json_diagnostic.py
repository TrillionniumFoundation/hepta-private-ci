import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cargo_deny_json_diagnostic as d
import cargo_deny_json_support as j


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        d.owned.OWNERSHIP_UNCERTAIN = False  # Isolate test-only simulated failures.

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
        self.assertEqual(result['stop'], 'capture_or_ownership_failed')

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

    def test_source_snapshot_detects_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            file = root / 'Cargo.lock'
            file.write_text('old')
            with mock.patch.object(d, 'git', return_value=b'Cargo.lock\0'):
                old = d.snapshot(root, {})
                file.write_text('new')
                self.assertNotEqual(old, d.snapshot(root, {}))


    def exercise_main(self, build_exit=0, run_exit=0, changed=False, gate=True, cleanup_exit=0, cleanup_stop=None, control_change=False, run_stop=None, action_error=None, db_fail=False, db_change=False, real_cleanup_capture=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, action, temp = [root / name for name in ['source', 'action', 'temp']]
            for path in [source / 'codex-rs', action, temp]:
                path.mkdir(parents=True)
            (source / 'codex-rs/Cargo.lock').write_text('[[package]]\nname="ammonia"\nversion="0.7.0"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n')
            (source / 'codex-rs/deny.toml').write_text('[advisories]')
            for name in ['Dockerfile', 'entrypoint.sh']:
                (action / name).write_text('fixture')
            calls = []
            original_capture = d.capture
            def fake_capture(argv, env, seconds, disk=None, abort=None, observer=None):
                calls.append(argv)
                if argv[1] == 'rm' and real_cleanup_capture:
                    return original_capture(argv, env, seconds, disk=disk)
                if argv[1] == 'run' and run_stop and abort:
                    abort()
                streams = [d.Stream(), d.Stream()]
                streams[0].feed(b'public result')
                if observer is not None:
                    streams[1].json_observer = observer
                    streams[1].feed(json.dumps(OFFICIAL_FIXTURES[0]).encode() + b'\n')
                code = build_exit if argv[1] == 'build' else run_exit if argv[1] == 'run' else cleanup_exit
                return {'argv': argv, 'exit': code, 'stop': cleanup_stop if argv[1] == 'rm' else run_stop if argv[1] == 'run' else None,
                        'cleanup': {'confirmed':True}, 'streams': [stream.finish() for stream in streams]}, streams
            db_receipt={'status':'verified','commit':d.DB_COMMIT,'tree':d.DB_TREE}
            def after_db(*args):
                if db_fail:raise ValueError('fixed_db_denied')
                return dict(db_receipt,tree='changed') if db_change else db_receipt
            with mock.patch.object(d,'initialize_budget',return_value={'test':True}), mock.patch.object(d,'source_blobs',return_value={}), \
                 mock.patch.object(d,'prepare_fixed_db',return_value=db_receipt), \
                 mock.patch.object(d,'fixed_db_receipt',side_effect=after_db), \
                 mock.patch.object(d, 'control_receipt', side_effect=[{'head': 'fixed'}, {'head': 'changed' if control_change else 'fixed'}]), mock.patch.object(d, 'action_identity', return_value={'tag_object': d.ACTION}, side_effect=action_error), mock.patch.object(d, 'identity'), mock.patch.object(d, 'BLOBS', {}), \
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
        self.assertEqual(receipt['advisory_revisions'], [d.DB_COMMIT])
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
            subprocess.run(['git', '-C', str(root), '-c','gc.auto=0','-c','maintenance.auto=false','-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip()
            with mock.patch.dict(os.environ, {'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/'+d.BRANCH,
                'GITHUB_WORKFLOW_REF':'TrillionniumFoundation/hepta-private-ci/.github/workflows/cargo-deny-fixed-tls.yml@refs/heads/'+d.BRANCH}):
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
            config = ['git', '-C', str(root), '-c','gc.auto=0','-c','maintenance.auto=false','-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid']
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



# Official EmbarkStudios/cargo-deny 0.19.0 snapshot schema fixtures, not live findings.
# Source blobs 8295d2d47673e9e69a0e9bdca9abe82d9cf12b20 and 48cc0d73d38023f13ccc05b663b5651bde7771fb.
OFFICIAL_FIXTURES = json.loads('[{"fields":{"advisory":{"aliases":["CVE-2019-15542","GHSA-5hp8-35wj-m525"],"categories":[],"collection":"crates","cvss":"CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H","date":"2019-04-27","description":"Affected versions of this crate did use recursion for serialization of HTML\\nDOM trees.\\n\\nThis allows an attacker to cause abort due to stack overflow by providing\\na pathologically nested input.\\n\\nThe flaw was corrected by serializing the DOM tree iteratively instead.","id":"RUSTSEC-2019-0001","informational":null,"keywords":["stack-overflow","crash"],"license":"CC0-1.0","package":"ammonia","references":[],"related":[],"source":null,"title":"Uncontrolled recursion leads to abort in HTML serialization","url":"https://github.com/rust-ammonia/ammonia/blob/master/CHANGELOG.md#210","withdrawn":null},"code":"vulnerability","graphs":[{"Krate":{"name":"ammonia","version":"0.7.0"},"parents":[{"Krate":{"name":"advisories","version":"0.1.0"}}]}],"labels":[{"column":1,"line":4,"message":"security vulnerability detected","span":"ammonia 0.7.0 registry+https://github.com/rust-lang/crates.io-index"}],"message":"Uncontrolled recursion leads to abort in HTML serialization","notes":["ID: RUSTSEC-2019-0001","Advisory: https://rustsec.org/advisories/RUSTSEC-2019-0001","Affected versions of this crate did use recursion for serialization of HTML\\nDOM trees.\\n\\nThis allows an attacker to cause abort due to stack overflow by providing\\na pathologically nested input.\\n\\nThe flaw was corrected by serializing the DOM tree iteratively instead.","Announcement: https://github.com/rust-ammonia/ammonia/blob/master/CHANGELOG.md#210","Solution: Upgrade to >=2.1.0 (try `cargo update -p ammonia`)"],"severity":"error"},"type":"diagnostic"},{"fields":{"advisory":{"aliases":["CVE-2019-25010","CVE-2020-25575","GHSA-jq66-xh47-j9f3","GHSA-r98r-j25q-rmpr"],"categories":[],"collection":"crates","cvss":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","date":"2020-05-02","description":"The `failure` crate is officially end-of-life: it has been marked as deprecated\\nby the former maintainer, who has announced that there will be no updates or\\nmaintenance work on it going forward.\\n\\nThe following are some suggested actively developed alternatives to switch to:\\n\\n- [`anyhow`](https://crates.io/crates/anyhow)\\n- [`eyre`](https://crates.io/crates/eyre)\\n- [`fehler`](https://crates.io/crates/fehler)\\n- [`snafu`](https://crates.io/crates/snafu)\\n- [`thiserror`](https://crates.io/crates/thiserror)","id":"RUSTSEC-2020-0036","informational":"unmaintained","keywords":[],"license":"CC0-1.0","package":"failure","references":[],"related":[],"source":null,"title":"failure is officially deprecated/unmaintained","url":"https://github.com/rust-lang-nursery/failure/pull/347","withdrawn":null},"code":"unmaintained","graphs":[{"Krate":{"name":"failure","version":"0.1.8"},"parents":[{"Krate":{"name":"advisories","version":"0.1.0"}}]}],"labels":[{"column":1,"line":30,"message":"unmaintained advisory detected","span":"failure 0.1.8 registry+https://github.com/rust-lang/crates.io-index"}],"message":"failure is officially deprecated/unmaintained","notes":["ID: RUSTSEC-2020-0036","Advisory: https://rustsec.org/advisories/RUSTSEC-2020-0036","The `failure` crate is officially end-of-life: it has been marked as deprecated\\nby the former maintainer, who has announced that there will be no updates or\\nmaintenance work on it going forward.\\n\\nThe following are some suggested actively developed alternatives to switch to:\\n\\n- [`anyhow`](https://crates.io/crates/anyhow)\\n- [`eyre`](https://crates.io/crates/eyre)\\n- [`fehler`](https://crates.io/crates/fehler)\\n- [`snafu`](https://crates.io/crates/snafu)\\n- [`thiserror`](https://crates.io/crates/thiserror)","Announcement: https://github.com/rust-lang-nursery/failure/pull/347","Solution: No safe upgrade is available!"],"severity":"error"},"type":"diagnostic"},{"fields":{"advisory":{"aliases":[],"categories":[],"collection":"crates","cvss":null,"date":"2024-09-01","description":"This crate is no longer maintained, and the author recommends using the maintained [`web-time`] crate instead.\\n\\n[`web-time`]: https://crates.io/crates/web-time","id":"RUSTSEC-2024-0384","informational":"unmaintained","keywords":[],"license":"CC0-1.0","package":"instant","references":["https://crates.io/crates/instant/0.1.13","https://github.com/sebcrozet/instant/issues/52"],"related":[],"source":null,"title":"`instant` is unmaintained","url":null,"withdrawn":null},"code":"unmaintained","graphs":[{"Krate":{"name":"instant","version":"0.1.10"},"parents":[{"Krate":{"name":"fastrand","version":"1.4.1"},"parents":[{"Krate":{"name":"lettre","version":"0.10.0-rc.3"},"parents":[{"Krate":{"name":"advisories","version":"0.1.0"}}]}]},{"Krate":{"name":"parking_lot","version":"0.11.1"},"parents":[{"Krate":{"name":"r2d2","version":"0.8.9"},"parents":[{"Krate":{"name":"lettre","version":"0.10.0-rc.3"},"repeat":true}]},{"Krate":{"name":"scheduled-thread-pool","version":"0.2.5"},"parents":[{"Krate":{"name":"r2d2","version":"0.8.9"},"repeat":true}]},{"Krate":{"name":"trust-dns-resolver","version":"0.20.4"},"parents":[{"Krate":{"name":"advisories","version":"0.1.0"},"repeat":true}]}]},{"Krate":{"name":"parking_lot_core","version":"0.8.3"},"parents":[{"Krate":{"name":"parking_lot","version":"0.11.1"},"repeat":true}]}]}],"labels":[{"column":1,"line":58,"message":"unmaintained advisory detected","span":"instant 0.1.10 registry+https://github.com/rust-lang/crates.io-index"}],"message":"`instant` is unmaintained","notes":["ID: RUSTSEC-2024-0384","Advisory: https://rustsec.org/advisories/RUSTSEC-2024-0384","This crate is no longer maintained, and the author recommends using the maintained [`web-time`] crate instead.\\n\\n[`web-time`]: https://crates.io/crates/web-time","Solution: No safe upgrade is available!"],"severity":"error"},"type":"diagnostic"},{"fields":{"advisory":{"aliases":[],"categories":[],"collection":"crates","cvss":null,"date":"2016-09-10","description":"The `libusb` crate has not seen a release since September 2016, and its author\\nis unresponsive.\\n\\nThe `rusb` crate is a maintained fork:\\n\\nhttps://github.com/a1ien/rusb","id":"RUSTSEC-2016-0004","informational":"unmaintained","keywords":[],"license":"CC0-1.0","package":"libusb","references":[],"related":[],"source":null,"title":"libusb is unmaintained; use rusb instead","url":"https://github.com/dcuddeback/libusb-rs/issues/33","withdrawn":null},"code":"unmaintained","graphs":[{"Krate":{"name":"libusb","version":"0.3.0"},"parents":[{"Krate":{"name":"advisories","version":"0.1.0"}}]}],"labels":[{"column":1,"line":67,"message":"unmaintained advisory detected","span":"libusb 0.3.0 registry+https://github.com/rust-lang/crates.io-index"}],"message":"libusb is unmaintained; use rusb instead","notes":["ID: RUSTSEC-2016-0004","Advisory: https://rustsec.org/advisories/RUSTSEC-2016-0004","The `libusb` crate has not seen a release since September 2016, and its author\\nis unresponsive.\\n\\nThe `rusb` crate is a maintained fork:\\n\\nhttps://github.com/a1ien/rusb","Announcement: https://github.com/dcuddeback/libusb-rs/issues/33","Solution: No safe upgrade is available!"],"severity":"error"},"type":"diagnostic"}]')

class JSONTests(unittest.TestCase):
    def setUp(self):
        d.owned.OWNERSHIP_UNCERTAIN = False

    def parser(self):
        # Pairs independently checked against official fixture lock blob c9a47fcd056c44817170a56e227e998c671b195d.
        pairs = [('ammonia', '0.7.0'), ('failure', '0.1.8'), ('instant', '0.1.10'), ('libusb', '0.3.0')]
        return j.JSONObservations(dict(zip(pairs, pairs)))

    def obj(self):
        return json.loads(json.dumps(OFFICIAL_FIXTURES[0]))

    def test_official_four_and_byte_chunk_split(self):
        parser = self.parser()
        for obj in OFFICIAL_FIXTURES:
            for byte in json.dumps(obj).encode() + b'\n':
                parser.feed(bytes([byte]))
        parser.finish()
        receipt = parser.receipt(True, True)
        self.assertEqual(len(receipt['tuples']), 4)
        self.assertEqual(sum(parser.rejected.values()), 0)
        self.assertEqual({row['advisory_id'] for row in receipt['tuples']},
                         {'RUSTSEC-2019-0001', 'RUSTSEC-2020-0036', 'RUSTSEC-2024-0384', 'RUSTSEC-2016-0004'})
        self.assertFalse(receipt['advisory_content_verified'])

    def test_secret_fields_parent_and_raw_withholding(self):
        obj = self.obj()
        secret = 'token=fixture_secret_not_for_public_output'
        obj['fields']['message'] = secret
        obj['fields']['advisory']['description'] = secret
        obj['fields']['graphs'][0]['parents'] = [{'Krate': {'name': secret, 'version': secret}}]
        parser = self.parser()
        stream = d.Stream(4)
        stream.json_observer = parser
        stream.feed(json.dumps(obj).encode() + b'\n')
        stream.finish()
        self.assertTrue(stream.suspect)
        self.assertNotIn(secret, json.dumps(parser.receipt(True, True)))
        self.assertEqual(len(parser.receipt(True, True)['tuples']), 1)
        with tempfile.TemporaryDirectory() as td:
            result = {'stop': None}
            d.publish(Path(td) / 'public', [('run', result, [d.Stream(), stream])], True)
            self.assertFalse(result['raw_published'])
            self.assertFalse(list((Path(td) / 'public').iterdir()))

    def test_advisory_and_root_negative_variants(self):
        edits = [
            lambda o: o['fields']['advisory'].update(id='RUSTSEC-2019-0001?token=fixture'),
            lambda o: o['fields']['advisory'].update(id='RUSTSEC-2019-%30%30%30%31'),
            lambda o: o['fields']['advisory'].update(package='unknown'),
            lambda o: o['fields']['advisory'].update(source='https://private.invalid'),
            lambda o: o['fields']['advisory'].update(collection='other'),
            lambda o: o['fields']['advisory'].update(withdrawn='2026-01-01'),
            lambda o: o['fields']['advisory'].update(informational='unmaintained'),
            lambda o: o['fields']['graphs'][0]['Krate'].update(version='9.9.9'),
            lambda o: o['fields']['graphs'][0].update(Feature={}),
            lambda o: o['fields'].update(graphs=[]),
            lambda o: o['fields'].update(graphs=o['fields']['graphs'] * 2),
            lambda o: o['fields'].update(code='arbitrary_secret_code'),
            lambda o: o['fields'].update(severity='arbitrary_secret_severity'),
            lambda o: o['fields']['graphs'][0]['Krate'].update(name=[]),
        ]
        for edit in edits:
            with self.subTest(edit=edits.index(edit)):
                obj = self.obj(); edit(obj); parser = self.parser()
                parser.feed(json.dumps(obj).encode()); parser.finish()
                self.assertEqual(parser.receipt(True, True)['tuples'], [])
                self.assertEqual(sum(parser.rejected.values()), 1)

    def test_malformed_bounds_and_no_tail_parse(self):
        values = [b'{"type":"diagnostic","type":"diagnostic"}',
                  b'{"nested":{"x":0,"x":1}}', b'{"x":NaN}', b'{"x":Infinity}',
                  b'{"x":' + b'[' * 257 + b'0' + b']' * 257 + b'}',
                  b'{"x":"\xff"}', b'{"unfinished":', b'\x1b[31m{"x":1}',
                  json.dumps({str(i): i for i in range(257)}).encode()]
        parser = self.parser()
        for value in values:
            parser.feed(value + b'\n')
        parser.LINE_LIMIT = 100
        parser.feed(b'x' * 101)
        parser.feed(json.dumps(self.obj()).encode() + b'\n')
        parser.finish()
        self.assertFalse(parser.rows)
        self.assertEqual(sum(parser.rejected.values()), len(values) + 1)
        self.assertEqual(parser.rejected['overlong'], 1)
        self.assertEqual(parser.rejected['depth'], 1)

    def test_eof_valid_and_invalid(self):
        for suffix, expected in [(b'', 1), (b' trailing', 0)]:
            parser = self.parser(); parser.feed(json.dumps(self.obj()).encode() + suffix); parser.finish()
            self.assertEqual(len(parser.rows), expected)

    def test_exponent_overflow_rejected_in_ignored_nested_fields(self):
        for number in ('1e999', '-1e999'):
            for nested in (False, True):
                with self.subTest(number=number, nested=nested):
                    obj = self.obj()
                    obj['fields']['advisory']['description'] = {'ignored': ['FLOAT_SENTINEL']} if nested else 'FLOAT_SENTINEL'
                    raw = json.dumps(obj).replace('"FLOAT_SENTINEL"', number).encode()
                    parser = self.parser(); parser.feed(raw); parser.finish()
                    self.assertEqual(parser.receipt(True, True)['tuples'], [])
                    self.assertEqual(parser.rejected['invalid_json'], 1)

    def test_finite_json_float_in_ignored_field_allowed(self):
        obj = self.obj(); obj['fields']['advisory']['description'] = {'ignored': [1.25, -1e100, 1e-100]}
        parser = self.parser(); parser.feed(json.dumps(obj).encode()); parser.finish()
        self.assertEqual(len(parser.receipt(True, True)['tuples']), 1)
        self.assertEqual(sum(parser.rejected.values()), 0)

    def test_exact_depth256_allowed_and257_rejected(self):
        for depth, accepted in [(256, True), (257, False)]:
            obj = self.obj()
            # Root/fields/advisory are three levels; description is ignored data.
            marker = 'DEEP_SENTINEL'
            obj['fields']['advisory']['description'] = marker
            raw = json.dumps(obj).replace('"DEEP_SENTINEL"', '[' * (depth - 3) + '0' + ']' * (depth - 3)).encode()
            parser = self.parser(); parser.feed(raw); parser.finish()
            self.assertEqual(bool(parser.rows), accepted)
            self.assertEqual(parser.rejected['depth'], 0 if accepted else 1)

    def test_deep_wide_official_graph_shape_resource_bound(self):
        import time
        import tracemalloc
        obj = self.obj()
        node = obj['fields']['graphs'][0]
        # Graph root depth4; 126 parent-list/object pairs give exact depth256.
        for _ in range(126):
            parent = {'Krate': {'name': 'private_parent_fixture', 'version': '0.0.0'}}
            node['parents'] = [parent]
            node = parent
        # The last Krate object would add a level, so use an empty terminal node.
        node.clear()
        # A wide shallow ancestry branch stresses object allocation without outputting parents.
        obj['fields']['graphs'][0]['parents'].extend(
            {'Krate': {'name': 'private_parent_fixture', 'version': '0.0.0'}}
            for _ in range(6000))
        raw = json.dumps(obj, separators=(',', ':')).encode()
        self.assertLess(len(raw), j.JSONObservations.LINE_LIMIT)
        parser = self.parser()
        tracemalloc.start()
        started = time.monotonic()
        parser.feed(raw); parser.finish()
        elapsed = time.monotonic() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLess(peak, 64 * 1024**2)
        self.assertLess(elapsed, 5)
        self.assertEqual(len(parser.rows), 1)
        self.assertNotIn('private_parent_fixture', json.dumps(parser.receipt(True, True)))
        self.assertEqual(sum(parser.rejected.values()), 0)

    def test_nonfinite_and_duplicate_at_depth256_rejected(self):
        for payload in ('1e999', '-1e999', '{"same":0,"same":1}'):
            obj = self.obj(); obj['fields']['advisory']['description'] = 'DEEP_SENTINEL'
            # Objects add their own level; all cases stay inside accepted depth256.
            nesting = 252 if payload.startswith('{') else 253
            raw = json.dumps(obj).replace('"DEEP_SENTINEL"', '[' * nesting + payload + ']' * nesting).encode()
            parser = self.parser(); parser.feed(raw); parser.finish()
            self.assertFalse(parser.rows)
            self.assertEqual(parser.rejected['invalid_json'], 1)
            self.assertEqual(parser.rejected['depth'], 0)

    def test_depth_strings_and_escaped_quotes(self):
        obj = self.obj(); obj['fields']['message'] = '[{\\"' * 100
        parser = self.parser(); parser.feed(json.dumps(obj).encode()); parser.finish()
        self.assertEqual(len(parser.rows), 1)

    def test_caps_saturation_and_provenance_gate(self):
        parser = self.parser(); parser.COUNT_LIMIT = 1; parser.ROW_LIMIT = 1
        parser.feed((json.dumps(self.obj()) + '\n').encode() * 3)
        obj = self.obj(); obj['fields']['advisory']['id'] = 'RUSTSEC-2026-0001'
        parser.feed((json.dumps(obj) + '\n').encode() * 3)
        self.assertTrue(parser.saturated)
        self.assertEqual(len(parser.rows), 1)
        self.assertEqual(parser.rejected['rows_full'], 1)
        self.assertEqual(parser.receipt(False, True)['tuples'], [])
        self.assertEqual(parser.receipt(True, False)['tuples'][0]['count'], 1)

    def test_lock_source_ambiguity_and_input_config(self):
        lock = b'[[package]]\nname="a"\nversion="1.0.0"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n'
        self.assertIn(('a', '1.0.0'), j.lock_allowlist(lock))
        self.assertEqual(j.lock_allowlist(lock + b'[[package]]\nname="a"\nversion="1.0.0"\n'), {})
        self.assertTrue(j.default_db_config(b'[advisories]\nignore=[]'))
        for data in [b'[advisories]\ndb-path="x"', b'[advisories]\ndb-urls=[]',
                     b'[advisories]\ngit-fetch-with-cli=true', b'invalid']:
            self.assertFalse(j.default_db_config(data))
        with self.assertRaises(ValueError):
            j.lock_allowlist(b'x' * (4 * 1024**2 + 1))

    def test_new_command_manifest_position(self):
        self.assertEqual(len(d.ARGS), 12)
        self.assertEqual(d.ORIGINAL_ARGS[9], '--all-features')
        self.assertEqual(d.ARGS[9], '--all-features --locked --format json')
        self.assertEqual(d.ARGS[11], '--disable-fetch')
        self.assertEqual(d.ARGS[5:][3], './codex-rs/Cargo.toml')
        self.assertEqual([i for i in range(12) if d.ARGS[i] != d.ORIGINAL_ARGS[i]], [9,11])

    def test_only_stderr_observed_and_nonzero_preserved(self):
        parser = self.parser()
        payload = json.dumps(self.obj())
        code = 'import sys; print(' + repr(payload) + '); print(' + repr(payload) + ', file=sys.stderr); sys.exit(7)'
        result, _ = d.capture([sys.executable, '-c', code], os.environ.copy(), 5, observer=parser)
        self.assertEqual(result['exit'], 7)
        self.assertEqual(sum(parser.rows.values()), 1)


class IntegrationTests(unittest.TestCase):
    exercise_main = DiagnosticTests.exercise_main
    setUp = DiagnosticTests.setUp

    def test_fixed_revision_and_nonzero_preserved(self):
        code,receipt,calls=self.exercise_main(run_exit=7)
        self.assertEqual(code,7)
        self.assertEqual(receipt['advisory_revisions'],[d.DB_COMMIT])
        self.assertEqual(receipt['db_before'],receipt['db_after'])
        self.assertEqual(len(receipt['json_observations']['tuples']),1)
        self.assertEqual(sum(c[1]=='rm' for c in calls),1)
        self.assertTrue(all(not r['raw_published'] for r in receipt['records']))

    def test_execution_gates_suppress_tuples(self):
        for options in ({'changed':True},{'cleanup_exit':1},{'control_change':True},
                        {'run_stop':'timeout'},{'gate':False},{'build_exit':9},
                        {'db_fail':True},{'db_change':True}):
            with self.subTest(options=options):
                code,receipt,_=self.exercise_main(**options)
                self.assertNotEqual(code,0)
                self.assertEqual(receipt.get('json_observations',{}).get('tuples',[]),[])
                self.assertTrue(all(not r['raw_published'] for r in receipt['records']))



class RevisionTests(unittest.TestCase):
    def fixture(self, root, head=None):
        cargo = root / 'cargo'
        git = cargo.joinpath(*j.DB_PARTS)
        git.mkdir(parents=True)
        (cargo / 'advisory-dbs/db.lock').write_text('unread lock fixture')
        (git / 'HEAD').write_bytes(head if head is not None else b'a' * 40 + b'\n')
        (git / 'FETCH_HEAD').write_bytes(b'a' * 40 + b'\t\thttps://github.com/RustSec/advisory-db\n')
        return cargo, git

    def test_direct_head_and_db_lock_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            cargo, git = self.fixture(Path(td))
            result = j.revision_receipt(cargo)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(result['commit'], 'a' * 40)
            self.assertEqual(set(result['metadata_sha256']), {'head', 'fetch_head'})
            self.assertNotIn('https', json.dumps(result))

    def test_main_master_loose_and_packed(self):
        for branch in ('main', 'master'):
            for packed in (False, True):
                with self.subTest(branch=branch, packed=packed), tempfile.TemporaryDirectory() as td:
                    cargo, git = self.fixture(Path(td), f'ref: refs/heads/{branch}\n'.encode())
                    if packed:
                        (git / 'packed-refs').write_text('# pack-refs with: peeled fully-peeled sorted\n' + 'a' * 40 + f' refs/heads/{branch}\n')
                    else:
                        (git / 'refs/heads').mkdir(parents=True)
                        (git / f'refs/heads/{branch}').write_text('a' * 40 + '\n')
                    result = j.revision_receipt(cargo)
                    self.assertEqual(result['status'], 'verified')
                    self.assertEqual(result['head_form'], branch)

    def test_missing_mismatch_unsupported_and_oversized(self):
        cases = [('HEAD', b'ref: refs/heads/private\n'), ('HEAD', b'x' * 257),
                 ('HEAD', b'a' * 39), ('FETCH_HEAD', b'b' * 40 + b'\t\thttps://github.com/RustSec/advisory-db\n'),
                 ('FETCH_HEAD', b'a' * 40 + b'\t\thttps://user:pass@github.com/RustSec/advisory-db\n'),
                 ('FETCH_HEAD', b'a' * 40 + b'\t\thttps://github.com/RustSec/advisory-db?token=fixture\n'),
                 ('FETCH_HEAD', b'x' * 4097), ('FETCH_HEAD', None)]
        for name, data in cases:
            with self.subTest(name=name, data_length=len(data) if data else None), tempfile.TemporaryDirectory() as td:
                cargo, git = self.fixture(Path(td))
                if data is None:
                    (git / name).unlink()
                else:
                    (git / name).write_bytes(data)
                result = j.revision_receipt(cargo)
                self.assertIsNone(result['commit'])
                self.assertEqual(result['metadata_sha256'], {})

    def test_symlink_every_ancestor_and_files(self):
        for relative in ('cargo', 'cargo/advisory-dbs', 'cargo/advisory-dbs/advisory-db-3157b0e258782691',
                         'cargo/advisory-dbs/advisory-db-3157b0e258782691/.git',
                         'cargo/advisory-dbs/advisory-db-3157b0e258782691/.git/HEAD',
                         'cargo/advisory-dbs/advisory-db-3157b0e258782691/.git/FETCH_HEAD'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td); cargo, git = self.fixture(root)
                original = root / relative
                replacement = original.with_name(original.name + '-saved')
                original.rename(replacement); original.symlink_to(replacement, target_is_directory=replacement.is_dir())
                self.assertIsNone(j.revision_receipt(cargo)['commit'])

    def test_ref_symlinks_and_packed_symlink(self):
        for name in ('refs', 'refs/heads', 'refs/heads/main', 'packed-refs'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                cargo, git = self.fixture(Path(td), b'ref: refs/heads/main\n')
                (git / 'refs/heads').mkdir(parents=True)
                (git / 'refs/heads/main').write_text('a' * 40 + '\n')
                (git / 'packed-refs').write_text('a' * 40 + ' refs/heads/main\n')
                if name == 'packed-refs':
                    (git / 'refs/heads/main').unlink()
                target = git / name; saved = target.with_name(target.name + '-saved')
                target.rename(saved); target.symlink_to(saved, target_is_directory=saved.is_dir())
                self.assertIsNone(j.revision_receipt(cargo)['commit'])

    def test_denied_does_not_fallback_or_second_read(self):
        for denied in ('HEAD', 'refs', 'main', 'FETCH_HEAD'):
            with self.subTest(denied=denied), tempfile.TemporaryDirectory() as td:
                cargo, git = self.fixture(Path(td), b'ref: refs/heads/main\n')
                (git / 'refs/heads').mkdir(parents=True)
                (git / 'refs/heads/main').write_text('a' * 40 + '\n')
                (git / 'packed-refs').write_text('a' * 40 + ' refs/heads/main\n')
                original = os.open; calls = []
                def controlled(name, *args, **kwargs):
                    calls.append(name)
                    if name == denied:
                        raise PermissionError(13, 'private error fixture')
                    return original(name, *args, **kwargs)
                with mock.patch.object(j.os, 'open', side_effect=controlled):
                    result = j.revision_receipt(cargo)
                self.assertEqual(result['status'], 'denied')
                self.assertEqual(calls.count(denied), 1)
                self.assertNotIn('packed-refs', calls)
                self.assertNotIn('private', json.dumps(result))

    def test_changed_second_read_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cargo, git = self.fixture(Path(td)); original = os.open; counts = {}
            def controlled(name, *args, **kwargs):
                counts[name] = counts.get(name, 0) + 1
                if name == 'HEAD' and counts[name] == 2:
                    (git / 'HEAD').write_text('b' * 40 + '\n')
                return original(name, *args, **kwargs)
            with mock.patch.object(j.os, 'open', side_effect=controlled):
                result = j.revision_receipt(cargo)
            self.assertEqual(result['status'], 'invalid_or_changed')
            self.assertIsNone(result['commit'])

    def test_packed_duplicate_malformed_and_bounds(self):
        for data in [('a' * 40 + ' refs/heads/main\n') * 2, 'secret invalid line\n',
                     'a' * 40 + ' refs/heads/../main\n', '# x\n' * 1025, 'x' * 65537]:
            with tempfile.TemporaryDirectory() as td:
                cargo, git = self.fixture(Path(td), b'ref: refs/heads/main\n')
                (git / 'packed-refs').write_text(data)
                self.assertIsNone(j.revision_receipt(cargo)['commit'])

    def test_nonregular_metadata_rejected_without_block(self):
        with tempfile.TemporaryDirectory() as td:
            cargo, git = self.fixture(Path(td)); (git / 'HEAD').unlink(); os.mkfifo(git / 'HEAD')
            self.assertIsNone(j.revision_receipt(cargo)['commit'])


class FixedDBTests(unittest.TestCase):
    def fixture(self, root):
        cargo,gitdir=RevisionTests().fixture(root,head=d.DB_COMMIT.encode()+b'\n')
        (gitdir/'FETCH_HEAD').write_bytes(self.fetch_line())
        return cargo,gitdir

    def fetch_line(self):
        sha=d.DB_COMMIT.encode()
        return sha+b"\t\t'"+sha+b"' of https://github.com/RustSec/advisory-db\n"

    def test_exact_sha_fetch_form_only(self):
        with tempfile.TemporaryDirectory() as td:
            cargo,gitdir=self.fixture(Path(td))
            result=j.revision_receipt(cargo,expected_commit=d.DB_COMMIT)
            self.assertEqual(result['status'],'verified')
            self.assertEqual(result['head_form'],'direct')
            self.assertEqual(result['commit'],d.DB_COMMIT)
            self.assertEqual(j.revision_receipt(cargo)['status'],'invalid_or_changed')
            variations=[self.fetch_line()+b'\n',self.fetch_line().replace(b"' of",b"' evil of"),
                self.fetch_line().replace(b'https://github.com',b'https://user@github.com'),
                self.fetch_line().replace(b'RustSec/advisory-db',b'RustSec/advisory-db?x=y'),
                self.fetch_line().replace(d.DB_COMMIT.encode(),b'a'*40,1),
                self.fetch_line().replace(b"\t\t'",b"\tnot-for-merge\t'")]
            for value in variations:
                (gitdir/'FETCH_HEAD').write_bytes(value)
                self.assertEqual(j.revision_receipt(cargo,expected_commit=d.DB_COMMIT)['status'],'invalid_or_changed')

    def test_fixed_reader_denial_never_retries(self):
        import errno
        with tempfile.TemporaryDirectory() as td:
            cargo,_=self.fixture(Path(td));original=j.os.open;denied=[]
            def open_file(path,*args,**kwargs):
                if path=='FETCH_HEAD':
                    denied.append(path);raise PermissionError(errno.EACCES,'secret')
                return original(path,*args,**kwargs)
            with mock.patch.object(j.os,'open',side_effect=open_file):
                result=j.revision_receipt(cargo,expected_commit=d.DB_COMMIT)
            self.assertEqual(result['status'],'denied');self.assertEqual(denied,['FETCH_HEAD'])
            self.assertNotIn('secret',json.dumps(result))

    def test_fixed_db_commit_tree_remote_and_footprint_binding(self):
        with tempfile.TemporaryDirectory() as td:
            cargo,_=self.fixture(Path(td))
            with mock.patch.object(d,'identity') as identity,                  mock.patch.object(d,'git',side_effect=[d.DB_COMMIT.encode(),d.DB_URL.encode()]):
                receipt=d.fixed_db_receipt(cargo,{})
            identity.assert_called_once_with(d.db_directory(cargo),d.DB_COMMIT,d.DB_TREE,{})
            self.assertEqual(receipt['tree'],d.DB_TREE);self.assertEqual(receipt['origin'],d.DB_URL)
            for values in [[b'a'*40,d.DB_URL.encode()],[d.DB_COMMIT.encode(),b'https://evil.invalid']]:
                with mock.patch.object(d,'identity'),mock.patch.object(d,'git',side_effect=values):
                    with self.assertRaises(ValueError):d.fixed_db_receipt(cargo,{})
            with mock.patch.object(d,'identity',side_effect=ValueError('tree_changed')):
                with self.assertRaises(ValueError):d.fixed_db_receipt(cargo,{})
            outside=Path(td)/'outside';outside.write_text('do not read')
            (d.db_directory(cargo)/'linked').symlink_to(outside)
            with mock.patch.object(d,'identity'),mock.patch.object(d,'git',side_effect=[d.DB_COMMIT.encode(),d.DB_URL.encode()]):
                with self.assertRaisesRegex(ValueError,'fixed_db_symlink'):d.fixed_db_receipt(cargo,{})

    def test_fixed_db_footprint_cap_and_denied_walk(self):
        with tempfile.TemporaryDirectory() as td:
            cargo,_=self.fixture(Path(td))
            with (d.db_directory(cargo)/'oversize').open('wb') as f:
                f.truncate(64*1024**2+1)
            with mock.patch.object(d,'identity'), mock.patch.object(d,'git',side_effect=[d.DB_COMMIT.encode(),d.DB_URL.encode()]):
                with self.assertRaisesRegex(ValueError,'fixed_db_size_limit'):
                    d.fixed_db_receipt(cargo,{})
            def denied(*args,**kwargs):
                kwargs['onerror'](PermissionError('private-denial'))
            with mock.patch.object(d,'identity'), mock.patch.object(d,'git',side_effect=[d.DB_COMMIT.encode(),d.DB_URL.encode()]), mock.patch.object(d.os,'walk',side_effect=denied) as walk:
                with self.assertRaises(PermissionError):d.fixed_db_receipt(cargo,{})
                self.assertEqual(walk.call_count,1)

    def test_preparation_exact_fresh_commands_and_no_retry(self):
        for denied in (False,True):
            with tempfile.TemporaryDirectory() as td:
                cargo=Path(td)/'cargo';cargo.mkdir();records=[];calls=[]
                def capture(argv,*args,**kwargs):
                    calls.append(argv)
                    status=128 if denied and 'fetch' in argv else 0
                    streams=[d.Stream(),d.Stream()]
                    return {'argv':argv,'exit':status,'stop':None,'cleanup':{'confirmed':True},
                            'streams':[s.finish() for s in streams]},streams
                with mock.patch.object(d,'capture',side_effect=capture),mock.patch.object(d,'fixed_db_receipt',return_value={'bound':True}):
                    if denied:
                        with self.assertRaises(d.DiagnosticStop):d.prepare_fixed_db(cargo,{},records,Path(td))
                    else:self.assertEqual(d.prepare_fixed_db(cargo,{},records,Path(td)),{'bound':True})
                self.assertEqual(sum('fetch' in a for a in calls),1)
                fetch=next(a for a in calls if 'fetch' in a)
                self.assertEqual(fetch[-5:],['fetch','--depth=1','--no-tags','origin',d.DB_COMMIT])
                self.assertFalse(any('reset' in a or 'touch' in a for a in calls))
                if denied:self.assertFalse(any('checkout' in a for a in calls))
                else:
                    self.assertEqual(calls[-1][-3:],['checkout','--detach',d.DB_COMMIT])
                    with self.assertRaises(FileExistsError):d.prepare_fixed_db(cargo,{},records,Path(td))

    def test_raw_never_exported_even_clean_and_execution_success(self):
        with tempfile.TemporaryDirectory() as td:
            streams=[d.Stream(),d.Stream()]
            streams[0].feed(b'clean arbitrary stdout')
            streams[1].feed(b'token=verysecretvalue')
            result={'stop':None}
            d.publish(Path(td)/'public',[('run',result,streams)],True)
            self.assertEqual(list((Path(td)/'public').iterdir()),[])
            self.assertFalse(result['raw_published'])


import time
import signal
import cargo_deny_owned_process as support

DRIVER = '''import sys,json,os
sys.path.insert(0,sys.argv[1]);import cargo_deny_owned_process as s
r,streams=s.capture(json.loads(sys.argv[2]),dict(os.environ),float(sys.argv[3]))
r['retained']=[x.retained().decode(errors='replace') for x in streams]
print(json.dumps(r))
'''

class AdoptedChildEvidence(unittest.TestCase):
    def detached(self, exit_status, lifetime, cleanup_timeout=5):
        driver = DRIVER.replace("r,streams=s.capture", 
            "original=s._cleanup_owned\ns._cleanup_owned=lambda p:original(p,"+str(cleanup_timeout)+")\nr,streams=s.capture")
        child = ('import os,time,sys;from pathlib import Path;os.setsid();'
                 'Path(sys.argv[1]).write_text(str(os.getpid()));'
                 'os.close(1);os.close(2);time.sleep('+str(lifetime)+');sys.exit('+str(exit_status)+')')
        leader = ('import subprocess,sys,time;from pathlib import Path;'
                  'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);'
                  '\nwhile not Path(sys.argv[2]).exists():time.sleep(.005)')
        with tempfile.TemporaryDirectory() as root:
            pidfile=Path(root)/'pid'
            sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)'])
            try:
                result=subprocess.run([sys.executable,'-c',driver,str(Path(support.__file__).parent),
                    json.dumps([sys.executable,'-c',leader,child,str(pidfile)]),'3'],
                    capture_output=True,text=True,timeout=8,check=True)
                self.assertIsNone(sentinel.poll())
                return json.loads(result.stdout),int(pidfile.read_text())
            finally:
                sentinel.terminate();sentinel.wait(timeout=5)

    def test_real_detached_zero_exit_is_observed_exactly_reaped_without_signal(self):
        result,pid=self.detached(0,.15)
        self.assertTrue(result['cleanup']['confirmed'],result)
        self.assertEqual(result['exit'],0)
        self.assertEqual(result['cleanup']['signal_attempts'],['SIGKILL'])
        self.assertEqual(result['cleanup']['adopted_terminal_events'],
                         [{'pid':pid,'uid':os.getuid(),'status':{'kind':'exited','value':0}}])
        self.assertTrue(result['ownership']['initial_children_absent'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_real_detached_nonzero_reaped_but_holds(self):
        result,pid=self.detached(17,.15)
        self.assertFalse(result['cleanup']['confirmed'])
        self.assertEqual(result['cleanup']['error'],'adopted_helper_unsuccessful')
        self.assertEqual(result['cleanup']['adopted_terminal_events'][0]['status']['value'],17)
        self.assertIsNone(result['exit'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_real_detached_live_timeout_not_signalled(self):
        result,pid=self.detached(0,1,.15)
        self.assertFalse(result['cleanup']['confirmed'])
        self.assertEqual(result['cleanup']['error'],'adopted_children_deadline')
        self.assertEqual(result['cleanup']['adopted_terminal_events'],[])
        self.assertEqual(result['cleanup']['signal_attempts'],['SIGKILL'])
        os.kill(pid,0)  # Still live after supervisor stopped: never signalled.
        time.sleep(1.05)  # It exits naturally; no cleanup signal to outside group.

    def event(self,status=0):
        from types import SimpleNamespace
        return SimpleNamespace(si_pid=43210,si_uid=os.getuid(),si_code=os.CLD_EXITED,si_status=status)

    def test_exact_reaping_pid_and_status_mismatch_hold(self):
        for value in [(43211,0),(43210,1<<8),(0,0)]:
            with mock.patch.object(support.os,'waitid',return_value=self.event()),                  mock.patch.object(support.os,'waitpid',return_value=value) as reap,                  mock.patch.object(support.os,'kill',side_effect=AssertionError('No signal')):
                receipt={}
                self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
                self.assertEqual(receipt['error'],'adopted_reap_identity_unconfirmed')
                reap.assert_called_once_with(43210,os.WNOHANG)

    def test_wait_and_reap_denial_once_no_retry(self):
        for which in ('waitid','waitpid'):
            with mock.patch.object(support.os,'waitid',return_value=self.event()) as wait,                  mock.patch.object(support.os,'waitpid',return_value=(43210,0)) as reap:
                denied=wait if which=='waitid' else reap
                denied.side_effect=PermissionError('secret-denial')
                receipt={}
                self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
                self.assertEqual(denied.call_count,1)
                self.assertNotIn('secret',json.dumps(receipt))
                if which=='waitid':reap.assert_not_called()

    def test_assumptions_fail_before_launch(self):
        for target,value in [('active_count',2),('current_thread',object())]:
            with mock.patch.object(support.threading,target,return_value=value),                  mock.patch.object(support.subprocess,'Popen',side_effect=AssertionError('No launch')):
                result,_=support.capture(['never'],{},1)
                self.assertFalse(result['cleanup']['confirmed'])
        with mock.patch.object(support.signal,'getsignal',return_value=signal.SIG_IGN),              mock.patch.object(support.subprocess,'Popen',side_effect=AssertionError('No launch')):
            result,_=support.capture(['never'],{},1)
            self.assertFalse(result['cleanup']['confirmed'])

    def test_unsupported_terminal_uid_holds_without_reap(self):
        event=self.event();event.si_uid=os.getuid()+1
        with mock.patch.object(support.os,'waitid',return_value=event),              mock.patch.object(support.os,'waitpid',side_effect=AssertionError('No reap')):
            receipt={}
            self.assertFalse(support._observe_and_reap_adopted(receipt,time.monotonic()+1))
            self.assertEqual(receipt['error'],'adopted_terminal_identity_unsupported')


class SharedDeadlineTests(unittest.TestCase):
    def tearDown(self):
        d.WORK_DEADLINE=d.HARD_DEADLINE=None
        d.FINALIZING=False
        d.owned.OWNERSHIP_UNCERTAIN=False

    def test_origin_before_checkout_no_reset_and_invalid_origin(self):
        with mock.patch.dict(os.environ,{'DIAGNOSTIC_STARTED_MONOTONIC_NS':'100000000000'}), mock.patch.object(d.time,'monotonic',return_value=200):
            receipt=d.initialize_budget()
            self.assertEqual(d.WORK_DEADLINE,1600)
            self.assertEqual(d.HARD_DEADLINE,1780)
            self.assertFalse(receipt['reset'])
        for value in ['', 'nan', '-1', '1e9', '9'*21]:
            with mock.patch.dict(os.environ,{'DIAGNOSTIC_STARTED_MONOTONIC_NS':value}):
                with self.assertRaises(ValueError):d.initialize_budget()
        workflow=Path(d.__file__).parent.parent/'workflows/cargo-deny-fixed-tls.yml'
        body=workflow.read_text()
        self.assertLess(body.index('DIAGNOSTIC_STARTED_MONOTONIC_NS'),body.index('uses: actions/checkout'))

    def test_phase_accumulation_exhaustion_never_launches_and_reserve(self):
        d.WORK_DEADLINE=100;d.HARD_DEADLINE=280;d.FINALIZING=False
        with mock.patch.object(d.time,'monotonic',side_effect=[20,50]), mock.patch.object(d.owned,'capture',return_value=({'stop':None},[])) as capture:
            d.capture(['first'],{},180);d.capture(['second'],{},180)
            self.assertEqual([x.args[2] for x in capture.call_args_list],[70,40])
        with mock.patch.object(d.time,'monotonic',return_value=95), mock.patch.object(d.owned,'capture',side_effect=AssertionError('no launch')):
            result,_=d.capture(['expired'],{},180)
            self.assertEqual(result['stop'],'shared_deadline')
            with self.assertRaisesRegex(ValueError,'shared_deadline'):d.budget_guard()
        d.FINALIZING=True
        with mock.patch.object(d.time,'monotonic',return_value=95), mock.patch.object(d.owned,'capture',return_value=({'stop':None},[])) as capture:
            d.capture(['cleanup'],{},10)
            self.assertEqual(capture.call_args.args[2],10)
        with mock.patch.object(d.time,'monotonic',return_value=275), mock.patch.object(d.owned,'capture',side_effect=AssertionError('no launch')):
            result,_=d.capture(['expired-cleanup'],{},10)
            self.assertEqual(result['stop'],'shared_deadline')

    def test_main_timeout_cleanup_really_uses_reserve_once(self):
        for failure in ('none', 'denied', 'reserve_expired'):
            d.WORK_DEADLINE=100;d.HARD_DEADLINE=280;d.FINALIZING=False
            now=275 if failure=='reserve_expired' else 95
            result={'exit':0,'stop':None,'cleanup':{'confirmed':True},'streams':[]}
            def owned_capture(*args,**kwargs):
                self.assertTrue(d.FINALIZING)
                self.assertEqual(args[0][1:3],['rm','-f'])
                if failure=='denied':raise PermissionError('private-denial')
                return result,[]
            with mock.patch.object(d.time,'monotonic',return_value=now), mock.patch.object(d.owned,'capture',side_effect=owned_capture) as owned_call:
                code,receipt,calls=DiagnosticTests().exercise_main(run_stop='timeout',real_cleanup_capture=True)
            self.assertEqual(code,125)
            self.assertEqual(sum(a[1]=='rm' for a in calls),1)
            self.assertEqual(owned_call.call_count,0 if failure=='reserve_expired' else 1)
            self.assertEqual(receipt['cleanup_confirmed'],failure=='none')
            self.assertFalse(receipt['json_observations']['tuples'])
            self.assertNotIn('private-denial',json.dumps(receipt))
            self.assertNotIn('source_blobs_after',receipt)

    def test_real_shared_timeout_teardown(self):
        d.owned.OWNERSHIP_UNCERTAIN=False
        d.WORK_DEADLINE=time.monotonic()+10.1;d.FINALIZING=False
        result,_=d.capture([sys.executable,'-c','import time;time.sleep(5)'],dict(os.environ),20)
        self.assertEqual(result['stop'],'timeout')
        self.assertTrue(result['cleanup']['confirmed'])


if __name__ == '__main__':
    unittest.main()
