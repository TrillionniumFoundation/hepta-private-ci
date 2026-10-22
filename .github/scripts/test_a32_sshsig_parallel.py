"""Portable synthetic DAG/settlement tests; never native qualification."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import a32_sshsig_bazel as bazel
import a32_sshsig_parallel as parallel
import a32_sshsig_guard as guard
import a32_sshsig_qualification as runner
import test_a32_sshsig_qualification as fixtures

ROOT = Path(__file__).resolve().parents[2]
ORACLES = Path(os.environ.get('A32_ORACLE_FIXTURE_ROOT', ROOT))
ENV = {'SOURCE_SHA': 'source', 'GITHUB_RUN_ID': '3', 'GITHUB_RUN_ATTEMPT': '1',
       'GITHUB_REF_NAME': 'diagnostic/test', 'GITHUB_REPOSITORY': 'owner/repo'}


def seal(folder):
    for name in ('snapshot-receipt.json', 'sealed-inventory.json'):
        (folder / name).unlink(missing_ok=True)
    rows = [{'path': path, 'prefix_bytes': row['bytes'], 'source_bytes_after': row['bytes'],
             'sha256': row['sha256']} for path, row in guard.inventory(folder).items()]
    guard.save(folder / 'snapshot-receipt.json', {'incomplete_commands': [], 'immutable_prefix_snapshots': rows})
    guard.save(folder / 'sealed-inventory.json', guard.inventory(folder))


def bazel_fixture(folder, platform):
    record = {'schema': 'a32.sshsig-fixed-bazel.v1', 'platform': platform, **bazel.ASSETS[platform],
              'version': bazel.VERSION, 'version_observed': 'bazel 9.3.0',
              'binary_path': '/synthetic/job/bazel-bin/bazel', 'home_rc': [{'synthetic': True}],
              'release_metadata_sha256': bazel.RELEASE_METADATA_SHA256,
              'binary_rechecked_after_version': True, 'bazelisk_used': False, 'caches_enabled': False}
    record['url'] = 'https://github.com/bazelbuild/bazel/releases/download/9.3.0/' + record['name']
    guard.save(folder / 'bazel-installation.json', record)
    (folder / 'logs').mkdir(exist_ok=True)
    (folder / 'logs/install-bazel-version.log').write_text('bazel 9.3.0\n')


def resolver_fixture(folder, candidate=None, input_tree='input-tree'):
    folder.mkdir(parents=True)
    state = {'lane': 'resolver-linux', 'input_tree': input_tree, 'input_verified': True,
             'runner_os': 'Linux', 'runner_arch': 'X64', 'final_source_clean': True, 'published': False, 'full_project_qualified': False,
             'resolver_completed': True, 'native_completed': False, 'pre_resolution_format_passed': True,
             'steps': {'resolve': {'outcome': 'success'}},
             'candidate': candidate or {'commit': 'candidate', 'tree': 'candidate-tree', 'changed_paths': list(guard.LOCKS)},
             'source_manifest_sha256': 'manifest'}
    state['identity'] = parallel.expected_identity(state); state['final_head'] = state['candidate']['commit']
    commands = ['harness-tests', 'rustsec-oracle', 'rustsec-policy', 'cargo-resolve', 'cargo-locked-metadata',
                'cargo-resolve-repeat', 'cargo-deny-full-policy', 'bazel-lock-update', 'bazel-lock-check',
                'bazel-lock-repeat', 'bazel-lock-recheck', 'version-cargo-deny', 'install-dotslash-version', 'install-bazel-version']
    commands += ['version-' + name for name in ('python', 'rustc', 'cargo', 'nextest', 'just', 'uv', 'bazel', 'dotslash')]
    for path, prefix, data in zip(guard.LOCKS, ('Cargo.lock', 'MODULE.bazel.lock'), (fixtures.AFTER, b'{}\n')):
        for relative in ('locks/' + path, 'observed-current-locks/' + path, prefix + '.first', prefix + '.second'):
            target = folder / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    guard.save(folder / 'locks/manifest.json', {'identity': state['identity'], 'candidate': state['candidate'],
               'files': guard.inventory(folder / 'locks'), 'resolver_gates_passed': True})
    state['lock_manifest_sha256'] = guard.digest((folder / 'locks/manifest.json').read_bytes())
    bazel_fixture(folder, 'linux')
    guard.save(folder / 'source-manifest.json', {'synthetic': True})
    state['source_manifest_sha256'] = guard.digest((folder / 'source-manifest.json').read_bytes())
    guard.save(folder / 'source.json', state)
    guard.save(folder / 'commands.json', [{'name': name, 'exit_code': 0, 'status': 'passed'} for name in commands])
    seal(folder)
    return state


class PrerequisiteTests(unittest.TestCase):
    def test_missing_tool_holds_before_any_launch_or_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = fixtures.RunnerGuardTests().fixture(temporary); value.run = Mock(); value.state['lane'] = 'linux'
            with patch.object(parallel.sys, 'platform', 'linux'), patch.object(parallel.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'HOLD.*no install'):
                    parallel.prerequisites(value)
            value.run.assert_not_called()
            self.assertFalse(parallel.read_json(Path(temporary), 'prerequisites.json')['installation_attempted'])

    def test_existing_tools_only_receive_query_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = fixtures.RunnerGuardTests().fixture(temporary); value.run = Mock(); value.state['lane'] = 'linux'
            with patch.object(parallel.sys, 'platform', 'linux'), patch.object(parallel.shutil, 'which', side_effect=lambda name: '/tools/' + name):
                parallel.prerequisites(value)
            self.assertEqual([call.args[1][1:] for call in value.run.call_args_list],
                             [['--version']] * len(parallel.PREREQUISITES) + [['--modversion', 'libcap']])


class SealAndDagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.env = patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.state = resolver_fixture(self.root / 'resolver-linux')
        guard.save(self.root / guard.MANIFEST, {'synthetic': True})
        self.needs = {name: {'result': 'success'} for name in ('resolver-linux', 'native-linux', 'native-windows')}
        self.needs['resolver-linux']['outputs'] = {'lock-manifest-sha256': self.state['lock_manifest_sha256'],
                                                  'candidate-tree': self.state['candidate']['tree']}

    def test_resolver_only_settled_output_admits_without_native_claim(self):
        self.assertEqual(parallel.resolver(self.root / 'resolver-linux'), self.state)
        with patch.object(parallel, 'native', return_value={'counts': {'synthetic': 1}}) as native:
            result = parallel.aggregate(self.root, self.root, self.needs)
        self.assertEqual([call.args[2] for call in native.call_args_list], ['linux', 'windows', 'windows-owner'])
        self.assertFalse(result['resolver_native_qualified']); self.assertFalse(result['product_qualified'])
        self.assertTrue(result['required_diagnostic_lanes_completed'])

    def test_failed_skipped_cancelled_or_missing_job_never_passes(self):
        for status in ('failure', 'skipped', 'cancelled'):
            for name in self.needs:
                needs = copy.deepcopy(self.needs); needs[name]['result'] = status
                with self.subTest(name=name, status=status), self.assertRaisesRegex(RuntimeError, 'required job'):
                    parallel.aggregate(self.root, self.root, needs)
        with self.assertRaisesRegex(RuntimeError, 'required job'):
            parallel.aggregate(self.root, self.root, {})

    def test_failure_receipt_is_exclusive_nonqualified_and_preserves_first_error(self):
        output = self.root / 'aggregate/aggregate.json'
        with patch.object(parallel, 'verify_input', side_effect=RuntimeError('first source admission error')):
            with self.assertRaisesRegex(RuntimeError, 'first source admission error'):
                parallel.aggregate_to_file(self.root, self.root, output, self.needs)
            receipt = parallel.read_json(output.parent, 'aggregate-failure.json')
            self.assertFalse(receipt['required_diagnostic_lanes_completed'])
            original = (output.parent / 'aggregate-failure.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'first source admission error') as raised:
                parallel.aggregate_to_file(self.root, self.root, output, self.needs)
            self.assertIn('could not be written', raised.exception.__notes__[0])
            self.assertEqual((output.parent / 'aggregate-failure.json').read_bytes(), original)

    def test_external_candidate_or_manifest_binding_cannot_be_swapped(self):
        for key in ('lock-manifest-sha256', 'candidate-tree'):
            needs = copy.deepcopy(self.needs); needs['resolver-linux']['outputs'][key] = 'wrong'
            with self.assertRaisesRegex(RuntimeError, 'output binding'):
                parallel.aggregate(self.root, self.root, needs)

    def test_current_reviewed_manifest_is_not_replaced_by_matching_lane_receipts(self):
        (self.root / guard.MANIFEST).write_bytes(b'changed reviewed input')
        with self.assertRaisesRegex(RuntimeError, 'current reviewed'):
            parallel.aggregate(self.root, self.root, self.needs)

    def test_missing_native_lane_is_not_pass_despite_successful_job_metadata(self):
        with self.assertRaisesRegex(RuntimeError, 'missing/non-directory'):
            parallel.aggregate(self.root, self.root, self.needs)

    def test_partial_or_active_child_receipt_is_never_lock_readiness(self):
        folder = self.root / 'resolver-linux'
        (folder / 'PARTIAL-NOT-SETTLED.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'partial evidence'):
            parallel.resolver(folder)
        (folder / 'PARTIAL-NOT-SETTLED.json').unlink()
        (folder / 'acquisition-controls.no-kill.jsonl').write_text('{"event":"native-admitted"}\n'); seal(folder)
        with self.assertRaisesRegex(RuntimeError, 'not settled'):
            parallel.resolver(folder)

    def test_snapshot_coverage_and_byte_lengths_are_cross_bound(self):
        folder = self.root / 'resolver-linux'; original = parallel.read_json(folder, 'snapshot-receipt.json')
        for rows in ([], original['immutable_prefix_snapshots'] * 2,
                     [{**row, 'prefix_bytes': row['prefix_bytes'] + 1} for row in original['immutable_prefix_snapshots']]):
            guard.save(folder / 'snapshot-receipt.json', {**original, 'immutable_prefix_snapshots': rows})
            guard.save(folder / 'sealed-inventory.json', guard.inventory(folder, ('sealed-inventory.json',)))
            with self.assertRaisesRegex(RuntimeError, 'snapshot|writer'):
                parallel.resolver(folder)

    def test_resealed_failed_resolve_native_claim_wrong_attempt_and_lock_repeat_reject(self):
        folder = self.root / 'resolver-linux'
        for mutate in (lambda state: state.update(native_completed=True),
                       lambda state: state.update(steps={'resolve': {'outcome': 'failure'}}),
                       lambda state: state['identity'].update(run_attempt='2')):
            state = copy.deepcopy(self.state); mutate(state); guard.save(folder / 'source.json', state); seal(folder)
            with self.assertRaises(RuntimeError): parallel.resolver(folder)
        guard.save(folder / 'source.json', self.state)
        (folder / 'Cargo.lock.second').write_bytes(b'changed'); seal(folder)
        with self.assertRaisesRegex(RuntimeError, 'repeat/final'):
            parallel.resolver(folder)

    def test_native_cannot_run_in_resolver_or_without_consumed_locks(self):
        value = fixtures.RunnerGuardTests().fixture(self.root); value.versions = Mock()
        for lane, verified in (('resolver-linux', True), ('linux', False)):
            value.state.update(candidate={}, lane=lane, same_run_locks_verified=verified)
            with patch.object(runner.sys, 'platform', 'linux'), self.assertRaisesRegex(RuntimeError, 'resolver|consume'):
                value.native()
        value.versions.assert_not_called()

    def test_candidate_head_release_and_fresh_linux_consume_with_actual_git(self):
        repo = self.root / 'repo'; repo.mkdir(); guard.git(repo, 'init')
        for name, value in (('user.name', 'test'), ('user.email', 'test@invalid'), ('core.autocrlf', 'false')):
            guard.git(repo, 'config', name, value)
        for name, data in zip(guard.LOCKS, (fixtures.BEFORE, b'{}\n')):
            target = repo / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        guard.git(repo, 'add', '.'); guard.git(repo, 'commit', '-m', 'synthetic input')
        source = guard.git(repo, 'rev-parse', 'HEAD').decode().strip(); tree = guard.git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip()
        (repo / guard.LOCKS[0]).write_bytes(fixtures.AFTER); candidate = guard.local_candidate(repo, source)
        with patch.dict(os.environ, {'SOURCE_SHA': source}):
            state = resolver_fixture(self.root / 'actual-seal', candidate, tree)
            self.assertEqual(parallel.release_locks(repo, self.root / 'actual-seal'), state)
            guard.git(repo, 'checkout', '--detach', source)
            with self.assertRaisesRegex(RuntimeError, 'not the settled'):
                parallel.release_locks(repo, self.root / 'actual-seal')
            evidence = self.root / 'linux'; (evidence / 'input/codex-rs').mkdir(parents=True)
            (evidence / 'input/codex-rs/Cargo.lock').write_bytes(fixtures.BEFORE)
            value = fixtures.RunnerGuardTests().fixture(evidence); value.root = repo
            value.state.update(lane='linux', input_tree=tree)
            value.guard = runner.Qualification.guard.__get__(value)
            with patch.dict(os.environ, {'EXPECTED_LOCK_MANIFEST_SHA256': state['lock_manifest_sha256'],
                                        'EXPECTED_CANDIDATE_TREE': candidate['tree']}), patch.object(runner.sys, 'platform', 'linux'):
                value.consume(self.root / 'actual-seal/locks')
            self.assertEqual(value.state['candidate'], candidate)
            self.assertTrue(value.state['same_run_locks_verified'])


class ArchivedBazelTests(unittest.TestCase):
    def test_real_parser_rechecks_archived_shards_logs_xml_and_count_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); fixture = fixtures.EvidenceTests()
            for kind, listing in (('bazel-list', True), ('bazel-tests', False)):
                original = root / ('original-' + kind); original.mkdir()
                events, target = fixture.fixture_bep(original, 2, listing)
                data = fixture.encode(events); (root / (kind + '.bep.jsonl')).write_bytes(data)
                result = fixtures.proof.reconcile_bazel(data, 0, [target], original, root / kind,
                       None if listing else {target: ['case1', 'case2']}, {})
                guard.save(root / ('bazel-compiled-census.json' if listing else 'bazel-counts.json'), result)
            discovered = parallel.archived_bazel(root, 'bazel-list', [target])
            self.assertEqual(parallel.archived_bazel(root, 'bazel-tests', [target], discovered['compiled_cases'], {}), result)
            summaries = [event for event in events if 'testSummary' in event['id']]
            original_passed = summaries[0]['testSummary']['passed']
            summaries[0]['testSummary']['passed'] = []
            result['targets'][target]['summary']['passed'] = []
            (root / 'bazel-tests.bep.jsonl').write_bytes(fixture.encode(events))
            guard.save(root / 'bazel-counts.json', result)
            with self.assertRaisesRegex(RuntimeError, 'output references'):
                parallel.archived_bazel(root, 'bazel-tests', [target], discovered['compiled_cases'], {})
            summaries[0]['testSummary']['passed'] = original_passed
            result['targets'][target]['summary']['passed'] = original_passed
            (root / 'bazel-tests.bep.jsonl').write_bytes(fixture.encode(events))
            guard.save(root / 'bazel-counts.json', result)
            log = next((root / 'bazel-tests').rglob('test.log')); log.write_bytes(b'listing is not a pass')
            with self.assertRaisesRegex(RuntimeError, 'hash or XML'):
                parallel.archived_bazel(root, 'bazel-tests', [target], discovered['compiled_cases'], {})


def native_fixture(folder, lane, resolved, manifest, resolver_folder):
    folder.mkdir(); logs = folder / 'logs'; logs.mkdir()
    state = copy.deepcopy(resolved); state.update(lane=lane, runner_os='Linux' if lane == 'linux' else 'Windows', native_completed=True, product_qualified=False,
          same_run_locks_verified=True, steps={'native': {'outcome': 'success'}}, linux_prerequisites_queried=lane == 'linux',
          scope='synthetic full scoped owner observations', open_gates=['independent evidence review'])
    state.pop('resolver_completed')
    data = (resolver_folder / 'locks/manifest.json').read_bytes(); (folder / 'consumed-lock-manifest.json').write_bytes(data)
    for lock in guard.LOCKS:
        target = folder / 'observed-current-locks' / lock; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((resolver_folder / 'locks' / lock).read_bytes())
    if lane != 'linux':
        token = {'schema': 'a32.sshsig-token-probe.v1', 'thread_impersonating': False, 'query_errors': [],
                 'owner_capable_sid': 'synthetic-enabled-owner', 'process': {}}
        guard.save(folder / 'token.json', token)
        state['token_probe'] = {'sha256': guard.digest((folder / 'token.json').read_bytes()), 'owner_capable': True, 'process': {}}
    platform = 'linux' if lane == 'linux' else 'windows'
    state['configured_targets'] = manifest['bazel_targets'][platform]
    guard.save(folder / 'source-manifest.json', manifest)
    state['source_manifest_sha256'] = guard.digest((folder / 'source-manifest.json').read_bytes())
    bazel_fixture(folder, 'linux' if lane == 'linux' else 'win32')
    commands, packages = parallel.required_commands(lane)
    commands.add('install-bazel-version')
    for package in packages:
        cases = ['module::case']; required = []
        if package == 'codex-hepta-memory': cases = ['module::' + name for name in guard.MEMORY_CASES]
        if lane != 'linux' and package == guard.PACKAGES[-1]:
            required = ['durable::windows::output::tests::read_only_private_directory_exercises_native_sync_helper_error_propagation']
            if lane == 'windows-owner': required += ['durable::windows::custody_tests::' + name for name in (
                'wrong_owner_rejects_even_with_a_current_user_only_dacl', 'owner_change_after_open_rejects_the_same_retained_descriptor',
                'final_symlink_rejects_even_when_its_target_is_private_and_valid')]
            cases += required
        listing = {'test-count': len(cases), 'rust-suites': {package: {'package-name': package, 'status': 'listed',
                   'testcases': {case: {'ignored': False, 'filter-match': {'status': 'matches'}} for case in cases}}}}
        data = json.dumps(listing).encode(); (logs / (package + '-compiled-census.log')).write_bytes(data)
        lines = ''.join('PASS [0.1s] ' + package + ' ' + case + '\n' for case in cases)
        output = (lines + f'Summary [0.1s] {len(cases)} tests run: {len(cases)} passed, 0 skipped\n' + lines).encode()
        (logs / (package + '-tests.log')).write_bytes(output)
        counts = parallel.reconcile_nextest(output, parallel.census(data, package, []))
        if required: counts['required_native_cases'] = required
        guard.save(folder / (package + '-counts.json'), counts)
    finish = {'id': {'buildFinished': {}}, 'finished': {'exitCode': {'name': 'SUCCESS'}}, 'lastMessage': True}
    start = {'id': {'started': {}}, 'started': {'command': 'build', 'buildToolVersion': '9.3.0'}, 'children': [finish['id']]}
    (folder / 'analysis.bep.jsonl').write_bytes(fixtures.EvidenceTests.encode([start, finish]))
    if lane != 'windows-owner':
        fixture = fixtures.EvidenceTests()
        for kind, listing in (('bazel-list', True), ('bazel-tests', False)):
            original = folder / ('original-' + kind); original.mkdir()
            events, target = fixture.fixture_bep(original, 2, listing); data = fixture.encode(events)
            (folder / (kind + '.bep.jsonl')).write_bytes(data)
            result = fixtures.proof.reconcile_bazel(data, 0, [target], original, folder / kind,
                     None if listing else {target: ['case1', 'case2']}, {})
            guard.save(folder / ('bazel-compiled-census.json' if listing else 'bazel-counts.json'), result)
    guard.save(folder / 'source.json', state)
    guard.save(folder / 'commands.json', [{'name': name, 'exit_code': 0, 'status': 'passed'} for name in sorted(commands)])
    seal(folder)


class NativeAggregateTests(unittest.TestCase):
    def test_all_three_real_reconciliation_paths_and_missing_count_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, ENV):
            root = Path(temporary); resolved = resolver_fixture(root / 'resolver-linux')
            target = '//codex-rs/state:state-unit-tests'
            manifest = {'bazel_targets': {platform: [target] for platform in ('linux', 'windows')},
                        'ignored_tests': {'linux': {}, 'windows': {}}, 'bazel_ignored_tests': {'linux': {}, 'windows': {}}}
            # These are synthetic bytes, not native evidence. Actual frozen control functions have their own six-log test below.
            guard.save(root / guard.MANIFEST, manifest)
            guard.save(root / 'resolver-linux/source-manifest.json', manifest)
            resolved['source_manifest_sha256'] = guard.digest((root / 'resolver-linux/source-manifest.json').read_bytes())
            guard.save(root / 'resolver-linux/source.json', resolved); seal(root / 'resolver-linux')
            for lane in parallel.LANES[1:]: native_fixture(root / lane, lane, resolved, manifest, root / 'resolver-linux')
            needs = {name: {'result': 'success'} for name in ('resolver-linux', 'native-linux', 'native-windows')}
            needs['resolver-linux']['outputs'] = {'lock-manifest-sha256': resolved['lock_manifest_sha256'], 'candidate-tree': resolved['candidate']['tree']}
            with patch.object(parallel, 'control_receipts') as controls:
                result = parallel.aggregate(root, root, needs)
            controls.assert_called_once()
            self.assertEqual(set(result['lanes']), {'linux', 'windows', 'windows-owner'})
            counts = root / 'linux/codex-state-counts.json'; counts.unlink(); seal(root / 'linux')
            with self.assertRaises(FileNotFoundError): parallel.aggregate(root, root, needs)


class FrozenOracleTests(unittest.TestCase):
    def test_actual_frozen_oracles_check_both_positive_and_all_four_mutants(self):
        manifest = json.loads((ROOT / guard.MANIFEST).read_bytes()); candidate = {'tree': 'tree', 'commit': 'commit'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for family, names in (('acquisition', ('positive', 'unchecked-create', 'path-check-open')),
                                  ('recovery', ('positive', 'shared-source', 'skip-snapshot'))):
                path = ORACLES / parallel.SPECS[family][0]
                spec = importlib.util.spec_from_file_location('actual_' + family, path)
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                folder = root / (family + '-controls'); folder.mkdir(); records = []
                for name in names:
                    statuses = ({module.CREATION: 'PASS', module.SUBSTITUTION: 'PASS'} if family == 'acquisition'
                                else {module.PIN: 'PASS', module.SNAPSHOT: 'PASS'})
                    if name != 'positive':
                        failed = (module.CREATION if name == 'unchecked-create' else module.SUBSTITUTION) if family == 'acquisition' else (module.PIN if name == 'shared-source' else module.SNAPSHOT)
                        statuses[failed] = 'FAIL'
                    package = parallel.SPECS[family][2]
                    lines = [f'{status} [0.1s] {package} {case}' for case, status in statuses.items()]
                    lines += ['Summary [0.1s] 2 tests run: ' + ('2 passed' if name == 'positive' else '1 passed, 1 failed') + ', 0 skipped']
                    if family == 'acquisition':
                        lines += ['PRIVATE_STATE_ACQUISITION creation denied=true created=' + ('true' if name == 'unchecked-create' else 'false'),
                                  'PRIVATE_STATE_ACQUISITION substitution ' + ('swapped=true denied=false redirected=true' if name == 'path-check-open' else 'swapped=true denied=true redirected=false')]
                    else:
                        lines += ['WINDOWS_RECOVERY source_pin ' + ('write_denied=false replace_denied=false' if name == 'shared-source' else 'write_denied=true replace_denied=true'),
                                  'WINDOWS_RECOVERY metadata changed=true rejected=' + ('false' if name == 'skip-snapshot' else 'true'),
                                  'assertion left right; a retained handle does not excuse metadata drift']
                    text = '\n'.join(lines) + '\n'; code = 0 if name == 'positive' else 1
                    (folder / (name + '.log')).write_text(text)
                    records.append({'lane': name, 'exit_code': code, **module.check_result(name, code, text)})
                guard.save(folder / 'manifest.json', {'restored': True, 'source_tree': 'tree', 'source_head': 'commit',
                           'qualified': True, 'command': module.COMMAND, 'lanes': records})
            parallel.control_receipts(ORACLES, root, manifest, candidate)
            (root / 'recovery-controls/shared-source.log').write_text('setup denied, no tests ran')
            with self.assertRaises(RuntimeError): parallel.control_receipts(ORACLES, root, manifest, candidate)


class WorkflowDagTests(unittest.TestCase):
    def test_resolver_release_precedes_parallel_consumers_and_aggregate_requires_all(self):
        text = (ROOT / '.github/workflows/a32-sshsig-custody-qualification.yml').read_text()
        resolver, rest = text.split('  native-linux:', 1)
        self.assertNotIn('qualification.py native ', resolver)
        self.assertLess(resolver.index('id: collect'), resolver.index('id: ready'))
        self.assertLess(resolver.index('id: ready'), resolver.index('Retain same-run genuine locks'))
        self.assertIn('needs: [resolver-linux, native-linux, native-windows]', rest)
        self.assertEqual(rest.count('    needs: resolver-linux'), 2)
        self.assertNotIn('apt-get', text); self.assertNotIn('setup-bazel@', text); self.assertNotIn('bazelisk-version:', text)
        self.assertNotIn('dpkg ', text)
        self.assertIn('QUALIFICATION_LANE: resolver-linux', resolver)


if __name__ == '__main__':
    unittest.main()
