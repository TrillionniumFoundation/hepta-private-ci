"""Actual nextest list then the original just test, within one outer 7200s budget.

Listing is not test acceptance. This process sets no additional timeout, sends no
signals and performs no retry. The existing hepta_ci_exec process tree controller
owns the same single outer budget as before.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

EXPECTED_NAMES = ['runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures', 'runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::q24_next_use_command_readback_refuses_actual_publication_withdrawal', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_hot_readback_preserves_sources', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_training_proof_rejects_new_source_reentry_and_incomplete_slots', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_same_call_training_keeps_four_execute_and_three_readback_frames', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_last_actual_training_failure_never_returns_or_resigns_b', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_last_training_slot_keeps_the_actual_cohort_tail', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_cancel_keeps_the_held_lane_and_consumed_channel', 'runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::current_slots::published_current_last_original_slot_rejects_actual_withdrawal', 'runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::current_slots::published_current_call_rejects_other_original_incomplete_and_reuse']
FILTER = ' | '.join('test(=' + name + ')' for name in EXPECTED_NAMES)
ORIGINAL_TEST_COMMAND = [
    'just', 'test', '--locked', '--offline', '-p', 'codex-hepta-agentd',
    '-p', 'codex-hepta-intelligence-eval', '--lib', '-E', FILTER,
    '--test-threads', '2', '--retries', '0', '--status-level', 'pass',
    '--success-output', 'final', '--failure-output', 'final',
]
LIST_COMMAND = [
    'cargo', 'nextest', 'list', '--locked', '--offline',
    '-p', 'codex-hepta-agentd', '-p', 'codex-hepta-intelligence-eval',
    '--lib', '-E', FILTER, '--message-format=json',
]
ORIGINAL_RUN_NEXTEST_BLOB = '1ed63abe84267b320cbfb0123a70aac5507f4595'


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON object key: ' + key)
        value[key] = item
    return value


def selected_cases(document, expected):
    """Validate the actual 0.9.103 TestListSummary schema, including mismatches."""
    if not isinstance(document, dict) or not isinstance(document.get('rust-suites'), dict):
        raise ValueError('native listing has no rust-suites object')
    if type(document.get('test-count')) is not int or document['test-count'] < 0:
        raise ValueError('native listing has no original total test count')
    observed = []
    listed_count = 0
    for suite_id, suite in document['rust-suites'].items():
        if not isinstance(suite, dict) or not isinstance(suite.get('testcases'), dict):
            raise ValueError('native listing has no testcase map: ' + suite_id)
        listed_count += len(suite['testcases'])
        for name, case in suite['testcases'].items():
            if not isinstance(case, dict) or type(case.get('ignored')) is not bool:
                raise ValueError('native case lacks an actual ignored flag: ' + name)
            match = case.get('filter-match')
            if not isinstance(match, dict) or match.get('status') not in ('matches', 'mismatch'):
                raise ValueError('native case has an unknown filter status: ' + name)
            if match['status'] != 'matches':
                continue
            if suite.get('status') != 'listed' or case['ignored']:
                raise ValueError('selected native case is not ordinarily runnable: ' + name)
            if (suite.get('package-name') != 'codex-hepta-agentd'
                    or suite.get('kind') != 'lib'
                    or suite.get('binary-id') != suite_id
                    or not isinstance(suite.get('binary-path'), str)):
                raise ValueError('selected native case has unexpected package/lib provenance: ' + name)
            observed.append({'name': name, 'suite_id': suite_id,
                             'package': suite['package-name'], 'kind': suite['kind'],
                             'binary_path': suite['binary-path'], 'ignored': False})
    # This is the upstream total, not the selected count; never require total==11.
    if document['test-count'] != listed_count:
        raise ValueError('listing testcase maps disagree with the original total test count')
    names = [row['name'] for row in observed]
    if Counter(names) != Counter(expected) or len(names) != len(expected):
        raise ValueError('native selected names do not equal the eleven requested cases: '
                         + repr({'expected': list(expected), 'observed': names}))
    return {'expected_count': len(expected), 'selected_count': len(observed),
            'original_total_test_count': document['test-count'], 'cases': observed,
            'exact_selected_names': True, 'listing_is_test_pass': False}


def now():
    return datetime.now(timezone.utc).isoformat()


def file_meta(path):
    with path.open('rb') as stream:
        return {'bytes': path.stat().st_size,
                'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}


def actual_list_command(repo, directory, env, save):
    """Use the unchanged repository helper's actual scoped-metadata decision.

Only these fixed graph-free arguments are supported. The metadata is cargo's
complete original stdout, never reconstructed. Ordinary fallback remains the
same nextest list command when the original helper requires resolved metadata.
All work is inside the same existing hepta_ci_exec outer budget.
"""
    path = repo / 'scripts/run-nextest.py'
    data = path.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if blob != ORIGINAL_RUN_NEXTEST_BLOB:
        raise RuntimeError('original run-nextest metadata strategy changed; requires review')
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('original_scoped_nextest_metadata', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    arguments = LIST_COMMAND[3:]
    decision = {'original_helper': {'path': str(path), **file_meta(path), 'blob': blob},
                'original_arguments': arguments,
                'use_scoped_metadata': module.use_scoped_metadata(arguments, repo / 'codex-rs')}
    if not decision['use_scoped_metadata']:
        decision['actual_list_command'] = LIST_COMMAND
        save('metadata-strategy.json', decision)
        return LIST_COMMAND
    command = ['cargo', 'metadata', '--no-deps', '--format-version=1', '--locked', '--offline']
    stdout_path = directory / 'cargo-metadata.json'
    stderr_path = directory / 'cargo-metadata.stderr.raw.log'
    launch = {'command': command, 'cwd': str(repo / 'codex-rs'), 'started_at': now(),
              'outer_budget_owner': 'same original hepta_ci_exec 7200s', 'additional_timeout': None}
    with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
        process = subprocess.Popen(command, cwd=repo / 'codex-rs', env=env, stdout=stdout, stderr=stderr)
        launch['pid'] = process.pid
        save('cargo-metadata-launch.json', launch)
        status = process.wait()
        stdout.flush(); stderr.flush()
        os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
    execution = {**launch, 'finished_at': now(), 'returncode': status,
                 'actual_process_exit_observed': True, 'controller_kill': False,
                 'stdout': file_meta(stdout_path), 'stderr': file_meta(stderr_path)}
    save('cargo-metadata-execution.json', execution)
    if status:
        raise RuntimeError('original scoped cargo metadata failed; retained raw stdout/stderr')
    metadata = json.loads(stdout_path.read_text(), object_pairs_hook=unique_object)
    workspace = Path(metadata['workspace_root'])
    if workspace.resolve(strict=True) != (repo / 'codex-rs').resolve(strict=True):
        raise RuntimeError('cargo metadata came from a different original workspace')
    workspace_config = workspace / '.config/nextest.toml'
    names = {row['name'] for row in metadata['packages'] if row['id'] in set(metadata['workspace_members'])}
    if ((workspace_config.is_file() and re.search(r'\b(?:rdeps|deps)\s*\(', workspace_config.read_text()))
            or not all(package in names for package in module.scoped_packages(arguments))):
        command = LIST_COMMAND
        decision['fallback'] = 'same original helper workspace-config/package identity check'
    else:
        command = [*LIST_COMMAND, '--cargo-metadata', str(stdout_path)]
        decision['metadata'] = {'path': str(stdout_path), **file_meta(stdout_path)}
    decision['actual_list_command'] = command
    save('metadata-strategy.json', decision)
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if command != ORIGINAL_TEST_COMMAND:
        parser.error('test command differs from the reviewed eleven exact filters and original flags')
    if len(EXPECTED_NAMES) != 11 or len(set(EXPECTED_NAMES)) != 11:
        parser.error('exactly eleven unique names required')
    repo = args.repo.resolve(strict=True)
    records = args.records.resolve(strict=True)
    if records.is_relative_to(repo) or os.geteuid() == 0:
        parser.error('requires ordinary operator and external existing records')
    target = Path(os.environ['CARGO_TARGET_DIR']).resolve(strict=True)
    if os.environ.get('RUST_MIN_STACK') != '8388608':
        parser.error('original 8 MiB stack environment changed')
    if os.environ.get('SOURCE_SHA') != args.source or os.environ.get('TESTED_SHA') != args.source:
        parser.error('listing and test source environment differ')
    directory = records / 'list-admission'
    directory.mkdir(mode=0o700, exist_ok=False)

    def save(name, value):
        with (directory / name).open('x') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')

    def source_identity():
        def git(*values):
            return subprocess.check_output(['git', '--no-optional-locks', *values], cwd=repo).decode().strip()
        return {'source': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
                'status': git('status', '--porcelain=v1', '--untracked-files=all')}

    result = {'kind': 'actual-list-and-original-test-single-budget', 'source': args.source,
              'started_at': now(), 'status': 'listing-not-started',
              'ordinary_qualification': False, 'listing_is_test_pass': False,
              'native_test_child_started': False, 'additional_timeout_or_retry': False}
    before = None
    binary_inputs = []
    returncode = 1
    try:
        before = source_identity()
        if before['source'] != args.source or before['status']:
            raise RuntimeError('listing requires the exact clean source')
        save('source-before.json', before)
        env = dict(os.environ)
        env['NEXTEST_PROFILE'] = 'local'
        list_command = actual_list_command(repo, directory, env, save)
        launch = {'command': list_command, 'cwd': str(repo / 'codex-rs'),
                  'profile': 'local', 'source': args.source, 'target': str(target),
                  'stack_bytes': 8388608, 'outer_budget_owner': 'original hepta_ci_exec 7200s',
                  'separate_timeout': None, 'started_at': now()}
        stdout_path = directory / 'nextest-list.stdout.json'
        stderr_path = directory / 'nextest-list.stderr.raw.log'
        with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
            process = subprocess.Popen(list_command, cwd=repo / 'codex-rs', env=env,
                                       stdout=stdout, stderr=stderr)
            launch['pid'] = process.pid
            save('nextest-list-launch.json', launch)
            print(json.dumps({'phase': 'actual-nextest-list', 'pid': process.pid,
                              'started_at': launch['started_at']}), flush=True)
            list_code = process.wait()
            stdout.flush(); stderr.flush()
            os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
        list_execution = {**launch, 'finished_at': now(), 'returncode': list_code,
                          'actual_process_exit_observed': True, 'controller_kill': False,
                          'stdout': file_meta(stdout_path), 'stderr': file_meta(stderr_path)}
        save('nextest-list-execution.json', list_execution)
        result['list_execution'] = list_execution
        if list_code:
            result['status'] = 'native-list-failed-before-tests'
            raise RuntimeError('actual nextest listing failed; original stdout/stderr retained')
        document = json.loads(stdout_path.read_text(), object_pairs_hook=unique_object)
        coverage = selected_cases(document, EXPECTED_NAMES)
        save('selected-name-coverage.json', coverage)
        for raw in sorted({row['binary_path'] for row in coverage['cases']}):
            binary = Path(raw).resolve(strict=True)
            if not binary.is_relative_to(target) or not binary.is_file():
                raise RuntimeError('listed binary is outside the exact owned target')
            binary_inputs.append({'path': str(binary), **file_meta(binary)})
        save('listed-binary-inputs.json', {'source': args.source, 'binaries': binary_inputs})
        if source_identity() != before:
            raise RuntimeError('source changed during actual listing')
        result.update(status='original-test-starting', listing_exact_selected_names=True)
        test_launch = {'command': command, 'cwd': str(repo), 'started_at': now(),
                       'test_threads': 2, 'retries': 0, 'stack_bytes': 8388608,
                       'outer_budget_owner': 'same original hepta_ci_exec 7200s'}
        process = subprocess.Popen(command, cwd=repo, env=os.environ.copy())
        test_launch['pid'] = process.pid
        result['native_test_child_started'] = True
        save('original-just-test-launch.json', test_launch)
        print(json.dumps({'phase': 'original-just-test', 'pid': process.pid,
                          'started_at': test_launch['started_at']}), flush=True)
        test_code = process.wait()
        test_execution = {**test_launch, 'finished_at': now(), 'returncode': test_code,
                          'actual_process_exit_observed': True, 'controller_kill': False}
        save('original-just-test-execution.json', test_execution)
        result['test_execution'] = test_execution
        for expected in binary_inputs:
            if file_meta(Path(expected['path'])) != {k: expected[k] for k in ('bytes', 'sha256')}:
                raise RuntimeError('binary changed between listing and the actual test invocation')
        returncode = test_code if test_code >= 0 else 128 - test_code
        result['status'] = 'original-test-returned-zero' if returncode == 0 else 'original-test-failed'
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        returncode = returncode or 1
        print('native list/run admission failed: ' + result['error'], flush=True)
    finally:
        try:
            after = source_identity()
            save('source-after.json', after)
            result['source_before'], result['source_after'] = before, after
            if before is not None and before != after:
                result['source_changed'] = True
                returncode = 1
        except BaseException as error:
            result['retention_error'] = type(error).__name__ + ': ' + str(error)
            returncode = 1
        result.update(finished_at=now(), exit_code=returncode)
        save('result.json', result)
        print(json.dumps({'native_list_run_result': result}, sort_keys=True), flush=True)
    return returncode


if __name__ == '__main__':
    raise SystemExit(main())
