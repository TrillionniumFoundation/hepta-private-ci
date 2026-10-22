"""Local source/provenance oracle tests; no Rust or native-Windows claims."""
import json
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import time
import a32_sshsig_evidence as proof
import a32_sshsig_controls_nokill as adapter
import a32_sshsig_collection as collection

import a32_sshsig_guard as guard
import a32_sshsig_qualification as runner

BEFORE = b'''version = 4
[[package]]
name = "codex-hepta-operator-acceptance"
version = "0.0.0"
dependencies = ["anyhow"]
[[package]]
name = "anyhow"
version = "1.0.100"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "unchanged"
'''
AFTER = BEFORE.replace(b'["anyhow"]', b'["anyhow", "codex-utils-path", "windows-sys 0.52.0"]')


class BootstrapTests(unittest.TestCase):
    def archive(self, names, symlink=False):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name in names:
                info = tarfile.TarInfo(name)
                if symlink:
                    info.type, info.linkname = tarfile.SYMTYPE, "elsewhere"
                    archive.addfile(info)
                else:
                    info.size = 6
                    archive.addfile(info, io.BytesIO(b"binary"))
        return output.getvalue()

    def test_checksum_pinned_archive_only_returns_binary_bytes(self):
        data = self.archive(["folder/dotslash.exe"])
        self.assertEqual(runner.dotslash_binary(data, len(data), guard.digest(data)), b"binary")
        for size, digest in ((len(data) + 1, guard.digest(data)), (len(data), "0" * 64)):
            with self.assertRaisesRegex(RuntimeError, "hash/size"):
                runner.dotslash_binary(data, size, digest)

    def test_missing_duplicate_and_symlink_binaries_rejected(self):
        for names, symlink in ((["README"], False), (["dotslash", "dotslash.exe"], False), (["dotslash"], True)):
            data = self.archive(names, symlink)
            with self.assertRaisesRegex(RuntimeError, "archive member"):
                runner.dotslash_binary(data, len(data), guard.digest(data))


class RunnerGuardTests(unittest.TestCase):
    def fixture(self, directory):
        instance = object.__new__(runner.Qualification)
        instance.root = instance.evidence = Path(directory)
        instance.commands = []
        instance.state = {"started_unix": time.time(), "admission_seconds": 60}
        instance.guard, instance.flush = Mock(), Mock()
        return instance

    def test_failed_command_still_runs_post_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.fixture(directory)
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                instance.run("fixture", [sys.executable, "-c", "raise SystemExit(1)"])
            self.assertEqual(instance.guard.call_count, 2)
            self.assertEqual(instance.commands[0]["exit_code"], 1)

    def test_successful_command_with_bad_post_guard_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.fixture(directory)
            instance.guard.side_effect = [None, RuntimeError("hidden source")]
            with self.assertRaisesRegex(RuntimeError, "hidden source"):
                instance.run("fixture", [sys.executable, "-c", "pass"])
            self.assertEqual(instance.commands[0]["status"], "failed")
            self.assertEqual(instance.commands[0]["exit_code"], 0)
            self.assertEqual(instance.commands[0]["post_guard_error"], "hidden source")


class LockTests(unittest.TestCase):
    def test_only_two_real_edge_changes_accepted(self):
        self.assertEqual(sorted(guard.cargo_delta(BEFORE, AFTER)), ["codex-utils-path", "windows-sys 0.52.0"])

    def test_no_edge_not_accepted_as_generated(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected lock"):
            guard.cargo_delta(BEFORE, BEFORE)

    def test_package_version_or_source_change_rejected(self):
        for replacement in (AFTER.replace(b"1.0.100", b"1.0.101"), AFTER.replace(b"registry+", b"other+")):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RuntimeError, "package/version/source"):
                guard.cargo_delta(BEFORE, replacement)

    def test_checksum_and_extra_edge_rejected(self):
        for replacement in (AFTER.replace(b'"unchanged"', b'"changed"'), AFTER.replace(b'"anyhow",', b'"extra", "anyhow",')):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RuntimeError, "unexpected lock"):
                guard.cargo_delta(BEFORE, replacement)

    def test_new_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "package/version/source"):
            guard.cargo_delta(BEFORE, AFTER + b'\n[[package]]\nname="extra"\nversion="0.0.0"\n')

    def test_duplicate_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            guard.cargo_delta(BEFORE, AFTER + b'\n[[package]]\nname="codex-hepta-operator-acceptance"\nversion="0.0.0"\n')

    def test_header_change_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "header"):
            guard.cargo_delta(BEFORE, AFTER.replace(b"version = 4", b"version = 3"))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {"source_sha": "source", "run_id": "12", "run_attempt": "1", "input_tree": "tree"}
        for path in guard.LOCKS:
            output = self.root / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(AFTER if path.endswith("Cargo.lock") else b"{}\n")
        guard.save(self.root / "manifest.json", {"identity": self.identity, "files": guard.inventory(self.root),
                                                "resolver_gates_passed": True})

    def test_same_run_exact_bundle_accepted(self):
        self.assertTrue(guard.verify_bundle(self.root, self.identity)["resolver_gates_passed"])

    def test_wrong_run_attempt_or_source_rejected(self):
        for field in ("run_id", "run_attempt", "source_sha", "input_tree"):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "source/run/attempt"):
                guard.verify_bundle(self.root, {**self.identity, field: "wrong"})

    def test_extra_path_rejected(self):
        (self.root / "unreviewed.rs").write_text("unsafe new source")
        with self.assertRaisesRegex(RuntimeError, "exactly"):
            guard.verify_bundle(self.root, self.identity)

    def test_post_download_tamper_rejected(self):
        (self.root / "MODULE.bazel.lock").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "hash/length"):
            guard.verify_bundle(self.root, self.identity)

    def test_manifest_matches_independent_resolver_step_digest(self):
        path = self.root / "manifest.json"
        expected = guard.digest(path.read_bytes())
        guard.verify_bundle(self.root, self.identity, expected)
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "resolver step output"):
            guard.verify_bundle(self.root, self.identity, expected)

    def test_failed_generator_rejected(self):
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["resolver_gates_passed"] = False
        guard.save(path, data)
        with self.assertRaisesRegex(RuntimeError, "gates"):
            guard.verify_bundle(self.root, self.identity)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        guard.git(self.root, "init", "-q")
        guard.git(self.root, "config", "user.name", "local guard test")
        guard.git(self.root, "config", "user.email", "test@invalid")
        guard.git(self.root, "config", "core.autocrlf", "false")
        (self.root / "native.rs").write_bytes(b"old\n")
        for path in guard.LOCKS:
            output = self.root / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(BEFORE if path.endswith("Cargo.lock") else b"{}\n")
        self.base = self.commit()
        base_patch = patch.object(guard, "BASE", self.base)
        base_patch.start(); self.addCleanup(base_patch.stop)
        (self.root / "native.rs").write_bytes(b"reviewed\n")
        guard.git(self.root, "add", "native.rs")
        product_tree = guard.git(self.root, "write-tree").decode().strip()
        self.manifest = {"schema": "a32.sshsig-qualification-source.v1", "status": "frozen-for-native-review",
                         "expected_product_tree": product_tree, "auxiliary_files": [], "base": self.base, "base_tree": guard.git(self.root, "rev-parse", "HEAD^{tree}").decode().strip(),
                         "branch": "diagnostic", "auxiliary_paths": [guard.MANIFEST],
                         "files": [{"path": "native.rs", "base_blob": guard.blob(b"old\n"),
                                    "candidate_blob": guard.blob(b"reviewed\n"), "candidate_sha256": guard.digest(b"reviewed\n")}]}
        guard.save(self.root / guard.MANIFEST, self.manifest)
        self.source = self.commit()

    def commit(self):
        guard.git(self.root, "add", ".")
        guard.git(self.root, "commit", "-qm", "local fixture")
        return guard.git(self.root, "rev-parse", "HEAD").decode().strip()

    def test_exact_input_accepted(self):
        self.assertEqual(guard.verify_input(self.root, self.source, "diagnostic"), self.manifest)

    def test_wrong_branch_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "branch"):
            guard.verify_input(self.root, self.source, "main")

    def test_noncanonical_worktree_bytes_rejected_not_refreshed(self):
        (self.root / "native.rs").write_bytes(b"reviewed\r\n")
        with self.assertRaisesRegex(RuntimeError, "noncanonical"):
            guard.verify_input(self.root, self.source, "diagnostic")
        self.assertEqual((self.root / "native.rs").read_bytes(), b"reviewed\r\n")

    def test_unexpected_committed_path_rejected(self):
        (self.root / "extra.rs").write_text("extra")
        new = self.commit()
        with self.assertRaisesRegex(RuntimeError, "parent"):
            guard.verify_input(self.root, new, "diagnostic")

    def test_same_parent_unreviewed_path_rejected(self):
        (self.root / "extra.rs").write_text("extra")
        guard.git(self.root, "add", ".")
        guard.git(self.root, "commit", "--amend", "--no-edit", "-q")
        new = guard.git(self.root, "rev-parse", "HEAD").decode().strip()
        with self.assertRaisesRegex(RuntimeError, "allowlist"):
            guard.verify_input(self.root, new, "diagnostic")

    def test_same_parent_wrong_reviewed_postimage_rejected(self):
        (self.root / "native.rs").write_text("unreviewed")
        guard.git(self.root, "add", ".")
        guard.git(self.root, "commit", "--amend", "--no-edit", "-q")
        new = guard.git(self.root, "rev-parse", "HEAD").decode().strip()
        with self.assertRaisesRegex(RuntimeError, "postimage"):
            guard.verify_input(self.root, new, "diagnostic")

    def test_untracked_tracked_and_index_changes_rejected(self):
        (self.root / "untracked").write_text("extra")
        with self.assertRaisesRegex(RuntimeError, "source changes"):
            guard.check_clean(self.root)
        (self.root / "untracked").unlink()
        (self.root / "native.rs").write_text("unreviewed")
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_delta(self.root, self.source, guard.LOCKS)
        guard.git(self.root, "add", "native.rs")
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_delta(self.root, self.source, guard.LOCKS)

    def hidden_flag_probe(self, flag):
        guard.git(self.root, "update-index", flag, "native.rs")
        operations = (lambda: guard.check_clean(self.root),
                      lambda: guard.check_delta(self.root, self.source, guard.LOCKS),
                      lambda: guard.local_candidate(self.root, self.source))
        for operation in operations:
            with self.assertRaisesRegex(RuntimeError, "index flags"):
                operation()
        (self.root / "native.rs").write_bytes(b"unreviewed hidden bytes\n")
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        for operation in operations:
            with self.assertRaisesRegex(RuntimeError, "index flags"):
                operation()
        self.assertEqual((self.root / "native.rs").read_bytes(), b"unreviewed hidden bytes\n")
        self.assertNotEqual(guard.git(self.root, "ls-files", "-v", "--", "native.rs")[:1], b"H")
        self.assertEqual(guard.git(self.root, "rev-parse", "HEAD").decode().strip(), self.source)

    def test_assume_unchanged_is_rejected_without_clearing(self):
        self.hidden_flag_probe("--assume-unchanged")

    def test_skip_worktree_is_rejected_without_clearing(self):
        self.hidden_flag_probe("--skip-worktree")

    def test_raw_auxiliary_and_lock_bytes_are_checked(self):
        manifest = self.root / guard.MANIFEST
        original = manifest.read_bytes()
        manifest.write_bytes(original + b"\n")
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_clean(self.root)
        manifest.write_bytes(original)
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_clean(self.root)
        guard.check_delta(self.root, self.source, guard.LOCKS)
        guard.git(self.root, "add", "--", guard.LOCKS[0])
        with self.assertRaisesRegex(RuntimeError, "staged"):
            guard.check_delta(self.root, self.source, guard.LOCKS)

    def test_local_commit_clean_deterministic_and_only_locks(self):
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        first = guard.local_candidate(self.root, self.source)
        guard.check_clean(self.root)
        self.assertEqual(first["changed_paths"], [guard.LOCKS[0]])
        self.assertFalse(first["published"])
        guard.git(self.root, "checkout", "--detach", self.source)
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        self.assertEqual(guard.local_candidate(self.root, self.source), first)


class ObservationTests(unittest.TestCase):
    def test_native_pass_required_not_listing_skip_fail_or_crash(self):
        guard.verify_pass_cases("        PASS [0.01s] crate module::case\n", ("case",))
        for output in ("module::case", "SKIP [0.0s] crate module::case", "FAIL [0.0s] crate module::case",
                       "error[E0425]: case", "signal: 11 (SIGSEGV)", "timeout: module::case", "PASS [0.0s] crate module::case_extra"):
            with self.subTest(output=output), self.assertRaisesRegex(RuntimeError, "PASS observation"):
                guard.verify_pass_cases(output, ("case",))




class EvidenceTests(unittest.TestCase):
    def compiled(self, ignored=False):
        return json.dumps({'test-count': 1, 'rust-suites': {'crate': {
            'package-name': 'crate', 'status': 'listed', 'testcases': {
                'module::case': {'ignored': ignored, 'filter-match': {'status': 'matches'}}}}}}).encode()

    def output(self, status='PASS', summary='1 tests run: 1 passed, 0 skipped'):
        case = f'  {status} [0.1s] crate module::case\n'
        return (case + f'  Summary [0.1s] {summary}\n' + case).encode()

    def test_compiled_census_live_final_and_summary_all_reconcile(self):
        cases = proof.census(self.compiled(), 'crate', [])
        self.assertEqual(proof.reconcile_nextest(self.output(), cases)['passed'], 1)

    def test_empty_wrong_package_nonignored_filtered_and_count_census_fail(self):
        base = json.loads(self.compiled())
        variants = [{**base, 'test-count': 2}, {**base, 'rust-suites': {}}]
        wrong_package = json.loads(self.compiled()); wrong_package['rust-suites']['crate']['package-name'] = 'wrong'
        filtered = json.loads(self.compiled()); filtered['rust-suites']['crate']['testcases']['module::case']['filter-match']['status'] = 'mismatch'
        for value in [*variants, wrong_package, filtered]:
            with self.assertRaises(RuntimeError): proof.census(json.dumps(value), 'crate', [])

    def test_unreviewed_ignored_or_absent_original_ignored_fails(self):
        with self.assertRaises(RuntimeError): proof.census(self.compiled(True), 'crate', [])
        with self.assertRaises(RuntimeError): proof.census(self.compiled(), 'crate', ['crate module::case'])
        expected = proof.census(self.compiled(True), 'crate', ['crate module::case'])
        self.assertEqual(proof.reconcile_nextest(self.output('SKIP', '0 tests run: 0 passed, 1 skipped'), expected)['skipped'], 1)

    def test_missing_case_summary_failed_retry_and_bad_count_reject(self):
        expected = {'crate module::case': False}
        for output in [self.output().split(b'Summary')[0], self.output() + self.output(),
                       self.output('FAIL'), self.output().replace(b'1 passed', b'2 passed'),
                       self.output().replace(b'0 skipped', b'0 skipped, 1 failed'),
                       self.output().replace(b'PASS', b'TRY 1'),
                       self.output().replace(b'crate module::case', b'crate missing', 1),
                       self.output() + b'PASS [0.1s] crate module::case\n']:
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                proof.reconcile_nextest(output, expected)

    @staticmethod
    def libtest(name='first', filtered=0, status='ok'):
        passed, ignored = (1, 0) if status == 'ok' else (0, 1)
        return (f'running 1 test\ntest {name} ... {status}\n'
                f'test result: ok. {passed} passed; 0 failed; {ignored} ignored; 0 measured; {filtered} filtered out; finished in 0.01s\n').encode()

    def test_windows_multi_batch_disjoint_union(self):
        result = proof.parse_libtest_batches(self.libtest('one', 1) + self.libtest('two', 1))
        self.assertEqual(set(result['cases']), {'one', 'two'})
        self.assertEqual(len(result['batches']), 2)

    def test_duplicate_missing_boundary_bad_counts_and_outside_cases_fail(self):
        for data in [self.libtest() * 2, self.libtest().split(b'test result:')[0],
                     self.libtest().replace(b'1 passed', b'2 passed'), b'test outside ... ok\n' + self.libtest(),
                     self.libtest().replace(b'0 failed', b'1 failed')]:
            with self.assertRaises(RuntimeError): proof.parse_libtest_batches(data)

    def test_compiled_list_does_not_count_as_native_pass(self):
        listed = b'one: test\ntwo: test\n\n2 tests, 0 benchmarks\n'
        self.assertEqual(proof.parse_libtest_list(listed), {'one', 'two'})
        with self.assertRaises(RuntimeError): proof.parse_libtest_batches(listed)
        with self.assertRaises(RuntimeError): proof.parse_libtest_list(listed + b'one: test\n')

    def fixture_bep(self, root, shards=1, listing=False):
        target = '//codex-rs/state:state-unit-tests'
        events = []; passed = []
        for shard in range(1, shards + 1):
            folder = root / str(shard); folder.mkdir()
            log = (b'case1: test\ncase2: test\n\n2 tests, 0 benchmarks\n' if listing else
                   self.libtest(f'case{shard}', shards - 1))
            (folder / 'test.log').write_bytes(log)
            (folder / 'test.xml').write_bytes(b'<testsuite tests="1" failures="0" errors="0"><testcase name="wrapper"/></testsuite>')
            outputs = [{'name': name, 'uri': (folder / name).as_uri()} for name in ('test.log', 'test.xml')]
            passed.append(outputs[0])
            identity = {'label': target, 'configuration': {'id': 'native'}, 'run': 1, 'shard': shard, 'attempt': 1}
            events.append({'id': {'testResult': identity}, 'testResult': {'status': 'PASSED',
                           'executionInfo': {'strategy': 'local'}, 'testActionOutput': outputs}})
        events.append({'id': {'testSummary': {'label': target, 'configuration': {'id': 'native'}}},
                       'testSummary': {'overallStatus': 'PASSED', 'totalRunCount': shards,
                                       'runCount': 1, 'attemptCount': 1, 'shardCount': shards if shards > 1 else 0,
                                       'passed': passed}})
        events.append({'id': {'buildFinished': {}}, 'finished': {'exitCode': {'name': 'SUCCESS'}}, 'lastMessage': True})
        start = {'id': {'started': {}}, 'started': {'command': 'test', 'buildToolVersion': '9.3.0'},
                 'children': [x['id'] for x in events]}
        return [start, *events], target

    @staticmethod
    def encode(events):
        return ('\n'.join(json.dumps(x) for x in events) + '\n').encode()

    def test_native_bep_two_shards_counts_logs_xml_and_compiled_union(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); events, target = self.fixture_bep(root, 2)
            result = proof.reconcile_bazel(self.encode(events), 0, [target], root, root / 'copy',
                                           {target: ['case1', 'case2']}, {})
            self.assertEqual(result['targets'][target]['native_cases'], 2)
            self.assertEqual(len(result['targets'][target]['shards']), 2)

    def test_list_bep_duplicate_per_shard_lists_union_not_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); events, target = self.fixture_bep(root, 2, listing=True)
            result = proof.reconcile_bazel(self.encode(events), 0, [target], root, root / 'copy')
            self.assertEqual(result['compiled_cases'][target], ['case1', 'case2'])
            self.assertEqual(result['targets'][target]['cases'], {})

    def test_bep_missing_event_cached_retry_config_or_count_reject(self):
        for mutation in ('terminal', 'child', 'cache', 'retry', 'config', 'count', 'log', 'xml'):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); events, target = self.fixture_bep(root)
                if mutation == 'terminal': events[-1].pop('lastMessage')
                if mutation == 'child': events[0]['children'].append({'missing': {}})
                if mutation == 'cache': events[1]['testResult']['cachedLocally'] = True
                if mutation == 'retry': events[1]['id']['testResult']['attempt'] = 2
                if mutation == 'config': events[1]['id']['testResult']['configuration'] = {'id': 'other'}
                if mutation == 'count': events[-2]['testSummary']['totalRunCount'] = 2
                if mutation == 'log': events[-2]['testSummary']['passed'] = []
                if mutation == 'xml': (root / '1/test.xml').write_bytes(b'<testsuite tests="2"><testcase/></testsuite>')
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    proof.reconcile_bazel(self.encode(events), 0, [target], root, root / 'copy', {target: ['case1']}, {})

    def test_native_log_uri_escape_and_digest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'log').write_bytes(b'log'); allowed = root / 'allowed'; allowed.mkdir()
            for item, boundary in [({'uri': (root / 'log').as_uri()}, allowed),
                                   ({'uri': (root / 'log').as_uri(), 'digest': '0' * 64}, root),
                                   ({'uri': 'https://example.invalid/log'}, root)]:
                with self.assertRaises(RuntimeError): proof.local_output(item, boundary)


class AdapterTests(unittest.TestCase):
    def proxy(self):
        import subprocess
        delegate = Mock()
        process = Mock(pid=42); process.wait.return_value = 0; process.returncode = 0
        delegate.Popen.return_value = process
        delegate.CompletedProcess = subprocess.CompletedProcess
        delegate.CalledProcessError = subprocess.CalledProcessError
        delegate.PIPE = subprocess.PIPE
        spec = adapter.SPECS['acquisition']; command = adapter.command_for(spec)
        observe = Mock()
        return adapter.ExactCommandProxy(delegate, command, spec[1], observe), delegate, process, observe, command

    def test_exact_native_call_preserves_argv_cwd_stdio_and_completed_result(self):
        proxy, delegate, process, observe, command = self.proxy()
        output = object()
        result = proxy.run(command, cwd='original-cwd', stdout=output, stderr=-2, timeout=600, check=False, text=True)
        delegate.Popen.assert_called_once_with(command, cwd='original-cwd', stdout=output, stderr=-2, text=True)
        delegate.run.assert_not_called(); process.kill.assert_not_called(); process.terminate.assert_not_called()
        self.assertEqual(result.args, command); self.assertEqual(result.returncode, 0)
        self.assertIsNone(result.stdout); self.assertEqual(observe.call_args_list[0].args[0]['removed_timeout_seconds'], 600)

    def test_unknown_native_deadline_or_changed_args_reject_without_launch(self):
        for timeout, command_change in [(599, False), (600, True), (None, False)]:
            proxy, delegate, _, _, command = self.proxy()
            with self.assertRaises(RuntimeError):
                proxy.run(command + (['extra'] if command_change else []), cwd='cwd', stdout=object(), stderr=-2,
                          timeout=timeout, check=False)
            delegate.Popen.assert_not_called(); delegate.run.assert_not_called()

    def test_other_non_timeout_commands_delegate_unchanged(self):
        proxy, delegate, _, _, _ = self.proxy()
        command = ['git', 'apply', '--check', 'patch']
        proxy.run(command, cwd='original', check=True)
        delegate.run.assert_called_once_with(command, cwd='original', check=True)
        with self.assertRaises(RuntimeError): proxy.run(command, timeout=30)

    def test_first_interruption_ordinary_errors_and_observer_failures_defer_until_terminal(self):
        first = KeyboardInterrupt('first interruption')
        process = Mock(pid=17); process.wait.side_effect = [first, ValueError('query uncertain'), 0]
        observer = Mock(side_effect=OSError('journal unavailable'))
        with patch.object(adapter.time, 'sleep'), self.assertRaises(KeyboardInterrupt) as caught:
            adapter.wait_owned(process, observer)
        self.assertIs(caught.exception, first); self.assertEqual(process.wait.call_count, 3)
        process.kill.assert_not_called(); process.terminate.assert_not_called()

    def test_ordinary_wait_error_does_not_become_pass_or_restore_while_active(self):
        first = ValueError('wait error'); process = Mock(pid=19); process.wait.side_effect = [first, 0]
        with patch.object(adapter.time, 'sleep'), self.assertRaises(ValueError) as caught:
            adapter.wait_owned(process, Mock())
        self.assertIs(caught.exception, first); self.assertEqual(process.wait.call_count, 2)

    def test_exact_version_query_preserves_output_and_ordinary_exception_after_terminal(self):
        proxy, delegate, process, observe, _ = self.proxy()
        process.communicate.return_value = ('rustc version\n', None)
        self.assertEqual(proxy.check_output(['rustc', '--version', '--verbose'], cwd='cwd', text=True), 'rustc version\n')
        delegate.Popen.assert_called_with(['rustc', '--version', '--verbose'], stdout=delegate.PIPE, cwd='cwd', text=True)
        process.communicate.side_effect = [ValueError('read error'), ('terminal', None)]
        observe.side_effect = [None, OSError('observer failed')]
        with patch.object(adapter.time, 'sleep'), self.assertRaises(ValueError):
            proxy.check_output(['rustc', '--version', '--verbose'], cwd='cwd', text=True)
        self.assertEqual(process.communicate.call_count, 3)
        process.kill.assert_not_called()

    def test_original_file_argv_import_path_oracle_and_restoration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'original.py'; evidence = root / 'evidence'
            spec = adapter.SPECS['acquisition']; command = adapter.command_for(spec)
            code = f'''import json, subprocess, sys\nfrom pathlib import Path\nCOMMAND={command!r}\ndef check_result(value):\n    assert value.returncode == 0\ndef main():\n    out=Path(sys.argv[1]); out.mkdir()\n    (out/'context.json').write_text(json.dumps({{"file":__file__,"argv":sys.argv,"path0":sys.path[0]}}))\n    for unused in range(3):\n        result=subprocess.run(COMMAND,cwd=Path(__file__).parent,stdout=sys.stdout,stderr=subprocess.STDOUT,timeout=600,check=False)\n        check_result(result)\n'''
            path.write_text(code); original = path.read_bytes()
            argv, search = sys.argv, sys.path[:]
            process = Mock(pid=29); process.wait.return_value = 0
            with patch.object(adapter.subprocess, 'Popen', return_value=process):
                adapter.execute_frozen(path, evidence, guard.digest(original), spec)
            context = json.loads((evidence / 'context.json').read_bytes())
            self.assertEqual(context, {'file': str(path), 'argv': [str(path), str(evidence)], 'path0': str(root)})
            self.assertIs(sys.argv, argv); self.assertEqual(sys.path, search); self.assertEqual(path.read_bytes(), original)
            records = [json.loads(x) for x in (root / 'evidence.no-kill.jsonl').read_text().splitlines()]
            self.assertEqual(records[0]['control_sha256'], guard.digest(original))
            self.assertEqual(sum(x['event'] == 'native-finished' for x in records), 3)
            with self.assertRaisesRegex(RuntimeError, 'exact reviewed'): adapter.execute_frozen(path, root / 'other', '0' * 64, spec)


class PartialTests(unittest.TestCase):
    def instance(self, root, commands):
        value = object.__new__(runner.Qualification)
        value.evidence = root / 'live'; value.evidence.mkdir()
        value.root = root / 'checkout'; value.root.mkdir()
        value.commands = commands; value.state = {}
        value.guard = Mock(side_effect=AssertionError('must not inspect live source'))
        return value

    def test_unfinished_command_preserves_labeled_log_prefix_without_live_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); value = self.instance(root, [{'name': 'native', 'status': 'running'}])
            (value.evidence / 'logs').mkdir(); (value.evidence / 'logs/native.log').write_bytes(b'partial observation\n')
            (value.evidence / 'locks').mkdir(); (value.evidence / 'locks/Cargo.lock').write_bytes(b'not settled')
            value.collect()
            sealed = root / 'live-sealed'; receipt = json.loads((sealed / 'PARTIAL-NOT-SETTLED.json').read_bytes())
            self.assertFalse(receipt['qualification']); self.assertFalse(receipt['settled_inventory_created'])
            self.assertEqual(receipt['diagnostic_prefixes_only'][0]['bytes'], 20)
            self.assertFalse(receipt['diagnostic_prefixes_only'][0]['complete'])
            self.assertFalse((sealed / 'locks').exists()); value.guard.assert_not_called()
            with self.assertRaises(RuntimeError): value.collect()

    def test_completed_snapshot_is_separate_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); value = self.instance(root, [{'name': 'native', 'exit_code': 0}])
            source = value.evidence / 'receipt.json'; source.write_bytes(b'original')
            collection.seal(value); source.write_bytes(b'changed afterward')
            self.assertEqual((root / 'live-sealed/receipt.json').read_bytes(), b'original')
            with self.assertRaises(RuntimeError): collection.seal(value)

    def test_admission_exhaustion_does_not_launch_or_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            value = RunnerGuardTests().fixture(folder)
            value.state['started_unix'] = 0
            with patch.object(runner.subprocess, 'Popen') as process, self.assertRaises(RuntimeError):
                value.run('native', ['never-launched'])
            process.assert_not_called(); self.assertEqual(value.commands, [])


class AdditionalRunnerTests(unittest.TestCase):
    def test_post_spawn_state_write_error_still_waits_and_preserves_first_error(self):
        with tempfile.TemporaryDirectory() as folder:
            value = RunnerGuardTests().fixture(folder)
            first = OSError('first disk failure')
            value.flush.side_effect = [None, first, OSError('second disk failure')]
            value.guard.side_effect = [None, RuntimeError('later guard failure')]
            process = Mock(pid=81, returncode=0); process.wait.return_value = 0
            with patch.object(runner.subprocess, 'Popen', return_value=process), self.assertRaises(OSError) as caught:
                value.run('fixture', ['native-never-executed'])
            self.assertIs(caught.exception, first); process.wait.assert_called_once()
            process.kill.assert_not_called(); process.terminate.assert_not_called()
            self.assertEqual(value.commands[0]['status'], 'failed')

    def test_saved_metadata_replacement_is_atomic_on_write_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'; guard.save(path, {'old': True})
            before = path.read_bytes()
            with patch.object(guard.os, 'replace', side_effect=OSError('replace denied')), self.assertRaises(OSError):
                guard.save(path, {'new': True})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(x.name for x in path.parent.iterdir()), ['state.json'])

    def test_malformed_metadata_collects_only_raw_partial_not_source(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / 'live'; evidence.mkdir()
            (evidence / 'source.json').write_bytes(b'{truncated')
            (evidence / 'commands.json').write_bytes(b'[{')
            (evidence / 'acquisition-controls').mkdir()
            (evidence / 'acquisition-controls/positive.log').write_bytes(b'native partial output')
            with self.assertRaises(ValueError): runner.Qualification(evidence)
            value = runner.Qualification(evidence, recover_partial=True)
            value.guard = Mock(side_effect=AssertionError('must not inspect source'))
            value.collect(); value.guard.assert_not_called()
            sealed = evidence.with_name('live-sealed')
            raw = sealed / 'partial-prefixes'
            self.assertEqual((raw / 'source.json').read_bytes(), b'{truncated')
            self.assertEqual((raw / 'acquisition-controls/positive.log').read_bytes(), b'native partial output')
            self.assertFalse((sealed / 'sealed-inventory.json').exists())
            receipt = json.loads((sealed / 'PARTIAL-NOT-SETTLED.json').read_bytes())
            self.assertEqual(len(receipt['state']['metadata_errors']), 2)

    def test_token_query_uncertainty_or_impersonation_does_not_pass(self):
        import os
        import a32_sshsig_preflight as preflight
        for token in ({'schema': 'a32.sshsig-token-probe.v1', 'thread_impersonating': True, 'query_errors': []},
                      {'schema': 'a32.sshsig-token-probe.v1', 'thread_impersonating': False, 'query_errors': ['denied']}):
            with tempfile.TemporaryDirectory() as folder:
                value = RunnerGuardTests().fixture(folder)
                incoming = Path(folder) / 'independent'; incoming.mkdir()
                guard.save(incoming / 'token.json', token)
                env = {name: 'fixture' for name in preflight.IDENTITY_ENV.values()}
                receipt = {'schema': 'a32.sshsig-independent-preflight.v1', 'probe_sha256': preflight.PROBE_SHA256,
                           'exit_code': 0, 'token_sha256': guard.digest((incoming / 'token.json').read_bytes()),
                           'identity': {key: 'fixture' for key in preflight.IDENTITY_ENV}}
                guard.save(incoming / 'receipt.json', receipt)
                with patch.dict(os.environ, env), patch.object(runner.sys, 'platform', 'win32'), self.assertRaises(RuntimeError):
                    value.probe(incoming)
                self.assertNotIn('token_probe', value.state)


class FormatDiscoveryTests(unittest.TestCase):
    def fixture(self):
        import a32_sshsig_format_discovery as formatting
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        parent = Path(temp.name); root = parent / 'repo'; root.mkdir()
        guard.git(root, 'init', '-q'); guard.git(root, 'config', 'user.name', 'local formatter fixture')
        guard.git(root, 'config', 'user.email', 'fixture@invalid'); guard.git(root, 'config', 'core.autocrlf', 'false')
        path = 'codex-rs/hepta-operator-acceptance/src/lib.rs'
        source = root / path; source.parent.mkdir(parents=True); source.write_bytes(b'fn fixture( ){ }\n')
        for lock in guard.LOCKS:
            (root / lock).parent.mkdir(parents=True, exist_ok=True); (root / lock).write_bytes(b'original lock\n')
        guard.git(root, 'add', '.'); guard.git(root, 'commit', '-qm', 'synthetic formatter input')
        sha = guard.git(root, 'rev-parse', 'HEAD').decode().strip()
        tree = guard.git(root, 'rev-parse', 'HEAD^{tree}').decode().strip()
        evidence = parent / 'evidence'; evidence.mkdir()
        discovery = formatting.Discovery(root, evidence, sha, tree,
                    {'expected_product_tree': tree, 'files': [{'path': path}]}, lambda: None)
        return formatting, discovery, source, path

    def test_clean_format_check_does_not_generate_or_qualify(self):
        formatting, discovery, source, _ = self.fixture(); before = source.read_bytes()
        with patch.object(discovery, 'command', side_effect=[(0, b'rustfmt fixture'), (0, b'')]) as command:
            self.assertTrue(discovery.run())
        self.assertEqual(command.call_count, 2); self.assertEqual(source.read_bytes(), before)
        self.assertTrue(discovery.receipt['input_format_passed'])
        self.assertFalse(discovery.receipt['native_functional_qualification'])

    def test_genuine_mocked_formatter_bytes_preserved_but_changed_tree_always_hold(self):
        _, discovery, source, path = self.fixture()
        calls = []
        def command(name, argv):
            calls.append(name)
            if name == 'rustfmt-version': return 0, b'rustfmt fixture'
            if name == 'input-format-check': return 1, b'Diff in fixture.rs:1:\n'
            if name == 'generate-format-only': source.write_bytes(b'fn fixture() {}\n')
            return 0, b''
        with patch.object(discovery, 'command', side_effect=command): self.assertFalse(discovery.run())
        self.assertEqual(calls, ['rustfmt-version', 'input-format-check', 'generate-format-only', 'generated-format-check'])
        self.assertEqual((discovery.out / 'postimages' / path).read_bytes(), source.read_bytes())
        self.assertTrue((discovery.out / 'native-rustfmt.patch').read_bytes())
        self.assertTrue(discovery.receipt['hold']); self.assertTrue(discovery.receipt['locks_unchanged'])
        self.assertFalse(discovery.receipt['native_functional_qualification'])
        self.assertFalse(discovery.live.is_relative_to(discovery.out.parent))

    def test_non_style_check_failure_never_runs_formatter(self):
        _, discovery, source, _ = self.fixture(); before = source.read_bytes()
        with patch.object(discovery, 'command', side_effect=[(0, b'rustfmt fixture'), (1, b'invalid option')]) as command:
            with self.assertRaisesRegex(RuntimeError, 'genuine style diff'): discovery.run()
        self.assertEqual(command.call_count, 2); self.assertEqual(source.read_bytes(), before)
        self.assertTrue(discovery.receipt['hold'])

    def test_unexpected_lock_change_preserves_raw_bytes_and_rejects(self):
        _, discovery, source, _ = self.fixture()
        def command(name, argv):
            if name == 'rustfmt-version': return 0, b'rustfmt fixture'
            if name == 'input-format-check': return 1, b'Diff in fixture.rs:1:\n'
            (discovery.root / guard.LOCKS[0]).write_bytes(b'unexpected lock change')
            return 0, b''
        with patch.object(discovery, 'command', side_effect=command), self.assertRaises(RuntimeError): discovery.run()
        self.assertEqual((discovery.out / 'postimages' / guard.LOCKS[0]).read_bytes(), b'unexpected lock change')
        self.assertTrue(discovery.receipt['hold']); self.assertFalse(discovery.receipt['complete'])

    def test_unsettled_formatter_never_takes_final_source_snapshot(self):
        formatting, discovery, _, _ = self.fixture()
        def unresolved(name, argv):
            discovery.receipt['child_unsettled'] = True
            raise RuntimeError('unsettled child observation')
        with patch.object(discovery, 'command', side_effect=unresolved), patch.object(formatting, 'snapshot', wraps=formatting.snapshot) as capture:
            with self.assertRaises(RuntimeError): discovery.run()
        self.assertEqual(capture.call_count, 1)
        self.assertFalse((discovery.out / 'observed-generated-files.json').exists())
        self.assertTrue(discovery.receipt['child_unsettled'])


if __name__ == "__main__":
    unittest.main()
