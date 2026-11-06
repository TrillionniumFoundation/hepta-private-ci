#!/usr/bin/env python3
"""Build once, then retain the original 4105-block test in its fixed CI Host.

Preparation is outside native measurement. Execution runs the whole unchanged
test, including block generation, in one Host service. This adapter checks the
existing native outcome; it supplies neither a State oracle nor qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
from check_required_native_test import validate as validate_named_test
from public_host_ci_observation import write_new
from replay_pinned_native import json_load, require
from verify_ci_source import verify as verify_source

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = 'scripts/ci/run_history_native.py'
TARGET = 'ancestry_long_sync'
SOURCE = 'trillionnium/crates/trnm-pon-node/tests/' + TARGET + '.rs'
SELECTOR = 'actual_v3_long_chain_public_full_sync_reopen_and_corrupt_index_refusal'
PREPARATION_SCHEMA = 'trnm-ci-history-build-preparation-v1'
EXECUTION_SCHEMA = 'trnm-ci-history-native-execution-v1'
SUMMARY_SCHEMA = 'native-ancestry-long-sync-observation-v1'
JSON_LIMIT = 1024 * 1024
LOG_LIMIT = 32 * 1024 * 1024
BINARY_LIMIT = 512 * 1024 * 1024
FALSE_FLAGS = ('public_network_ready', 'hardness_accepted', 'independent_accepted',
               'production_activation')
BUILD_ENVIRONMENT = (
    'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL',
    'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTUP_TOOLCHAIN',
    'OPENSSL_DIR', 'OPENSSL_STATIC', 'OPENSSL_CONF', 'OPENSSL_MODULES',
    'TRNM_PQ_OPENSSL', 'TRNM_PQ_OPENSSL_SHA256', 'TRNM_PQ_OPENSSL_VERSION',
)


def file_observation(path: Path, limit: int, *, retain: bool = False) -> tuple[dict, bytes]:
    """Bounded regular-file observations, including replacement during hashing."""
    require(path.is_absolute() and path.resolve(strict=True) == path,
            'HISTORY_CANONICAL_FILE_REQUIRED')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit,
                'HISTORY_REGULAR_FILE_BOUND')
        fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_mode,
                                     value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        require(fingerprint(path.lstat()) == fingerprint(before), 'HISTORY_FILE_CHANGED')
        digest, chunks, remaining = hashlib.sha256(), [], before.st_size
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            require(bool(chunk), 'HISTORY_FILE_TRUNCATED')
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
            remaining -= len(chunk)
        require(not stream.read(1) and fingerprint(os.fstat(stream.fileno())) == fingerprint(before)
                and fingerprint(path.lstat()) == fingerprint(before), 'HISTORY_FILE_CHANGED')
    return ({'path': str(path), 'sha256': digest.hexdigest(), 'size_bytes': before.st_size,
             'device': before.st_dev, 'inode': before.st_ino,
             'mtime_ns': before.st_mtime_ns, 'ctime_ns': before.st_ctime_ns}, b''.join(chunks))


def load_object(path: Path) -> tuple[dict, dict]:
    observation, raw = file_observation(path, JSON_LIMIT, retain=True)
    value = json_load(raw)
    require(type(value) is dict, 'HISTORY_JSON_OBJECT_REQUIRED')
    return value, observation


def output_path(out: Path) -> Path:
    require(out.is_absolute() and out.resolve() == out and not out.is_relative_to(ROOT),
            'OUTPUT_MUST_BE_CANONICAL_OUTSIDE_CHECKOUT')
    receipts = Path(os.environ.get('TRNM_CI_RECEIPT_DIR', ''))
    require(receipts.is_absolute() and receipts.resolve(strict=True) == receipts
            and receipts.is_dir() and out == receipts / 'history-native',
            'HISTORY_CURRENT_RECEIPT_DIRECTORY_REQUIRED')
    return out


def job_identity() -> dict:
    result = {name: os.environ.get(name, '') for name in (
        'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')}
    require(result['GITHUB_RUN_ID'].isdecimal() and result['GITHUB_RUN_ATTEMPT'].isdecimal()
            and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', result['GITHUB_JOB']) is not None,
            'HISTORY_CURRENT_JOB_REQUIRED')
    return result


def source_identity() -> dict:
    """Recheck the workflow's event-bound receipt; never choose bare HEAD as expected."""
    expected = os.environ.get('TRNM_EXPECTED_SOURCE_SHA')
    require(type(expected) is str and re.fullmatch('[0-9a-f]{40}', expected) is not None,
            'HISTORY_EXPECTED_SOURCE_REQUIRED')
    receipt, _ = load_object(Path(os.environ['TRNM_CI_RECEIPT_DIR']) / 'source.json')
    require(receipt.get('schema') == 'trnm-ci-source-v1'
            and receipt.get('tested_commit') == expected
            and receipt.get('tracked_worktree_verified') is True
            and receipt.get('tests_executed_by_identity_check') is False,
            'HISTORY_WORKFLOW_SOURCE_RECEIPT_REQUIRED')
    actual = verify_source(receipt.get('kind'), receipt.get('candidate'),
                           receipt.get('base'), receipt.get('prospective_merge'), root=ROOT)
    require(actual == receipt, 'HISTORY_WORKFLOW_SOURCE_MISMATCH')
    test, _ = file_observation(ROOT / SOURCE, JSON_LIMIT)
    return {'commit': expected, 'tree': actual['tested_tree'],
            'tracked_source_identity': actual, 'test_sha256': test['sha256']}


def build_command() -> list[str]:
    # This is the existing history build. No from-zero 900-second bound is added.
    return ['cargo', '+1.95.0', 'test', '--release', '--locked', '--manifest-path',
            'trillionnium/Cargo.toml', '-p', 'trnm-pon-node', '--test', TARGET,
            '--no-run', '--message-format=json']


def select_binary(raw: bytes) -> Path:
    paths = []
    finished = False
    for line in raw.decode('utf-8').splitlines():
        if not line.startswith('{'):
            continue
        row = json_load(line)
        require(type(row) is dict, 'HISTORY_BUILD_JSON_OBJECT')
        require(not finished, 'HISTORY_BUILD_RECORD_AFTER_FINISH')
        if row.get('reason') == 'build-finished':
            require(row.get('success') is True, 'HISTORY_SUCCESSFUL_BUILD_FINISH_REQUIRED')
            finished = True
        elif row.get('reason') == 'compiler-artifact':
            target, profile = row.get('target'), row.get('profile')
            require(type(target) is dict and type(profile) is dict, 'HISTORY_BUILD_ARTIFACT_OBJECT')
            if target.get('name') != TARGET:
                continue
            require(target.get('src_path') == str(ROOT / SOURCE)
                    and target.get('kind') == ['test'] and target.get('crate_types') == ['bin']
                    and target.get('test') is True
                    and row.get('manifest_path') == str(ROOT / 'trillionnium/crates/trnm-pon-node/Cargo.toml'),
                    'HISTORY_BUILD_TARGET_SOURCE')
            require(profile.get('test') is True and profile.get('opt_level') == '3',
                    'HISTORY_RELEASE_TEST_PROFILE_REQUIRED')
            require(type(row.get('executable')) is str and type(row.get('filenames')) is list
                    and row['executable'] in row['filenames'], 'HISTORY_BUILD_EXECUTABLE_BINDING')
            paths.append(Path(row['executable']))
    require(finished, 'HISTORY_SUCCESSFUL_BUILD_FINISH_REQUIRED')
    require(len(paths) == 1, 'HISTORY_EXACT_NEW_BINARY_REQUIRED')
    file_observation(paths[0], BINARY_LIMIT)
    require(os.access(paths[0], os.X_OK), 'HISTORY_EXECUTABLE_REQUIRED')
    return paths[0]


def run_process(command: list[str], log: Path, *, environment: dict | None = None,
                stderr: Path | None = None) -> dict:
    """No new execution timeout; the original workflow/native owners keep theirs."""
    result = {'command': command, 'started': False, 'pid': None, 'exit_code': None,
              'failure': None, 'cleanup_errors': []}
    child = None
    error_stream = None
    try:
        with log.open('xb') as stream:
            if stderr is not None:
                error_stream = stderr.open('xb')
            child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream,
                                     stderr=error_stream if stderr is not None else subprocess.STDOUT,
                                     start_new_session=True)
            result.update(started=True, pid=child.pid)
            result['exit_code'] = child.wait()
    except BaseException as error:
        result['failure'] = type(error).__name__ + ':' + str(error)
        if child is not None:
            # Only this newly started process group is owned. Unknown exit stays null.
            try:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
            except BaseException as cleanup:
                result['cleanup_errors'].append(type(cleanup).__name__ + ':' + str(cleanup))
            try:
                result['exit_code'] = child.wait(timeout=5)
            except BaseException as cleanup:
                result['cleanup_errors'].append(type(cleanup).__name__ + ':' + str(cleanup))
                result['exit_code'] = child.returncode
    finally:
        if error_stream is not None:
            try:
                error_stream.close()
            except BaseException as error:
                failure = type(error).__name__ + ':' + str(error)
                if result['failure'] is None:
                    result['failure'] = failure
                else:
                    result['cleanup_errors'].append(failure)
    return result


def process_succeeded(process: dict, command: list[str]) -> bool:
    return (process.get('command') == command and process.get('started') is True
            and type(process.get('pid')) is int and process['pid'] > 0
            and type(process.get('exit_code')) is int and process['exit_code'] == 0
            and process.get('failure') is None and process.get('cleanup_errors') == [])


def prepare(out: Path) -> dict:
    out = output_path(out)
    out.mkdir(exist_ok=False)
    result = {'schema': PREPARATION_SCHEMA, 'target': TARGET, 'selector': SELECTOR,
              'job': None, 'source_before': None, 'source_after': None, 'process': None,
              'binary': None, 'build_log': None, 'failures': [], 'completed': False,
              'build_env': {key: os.environ.get(key) for key in BUILD_ENVIRONMENT},
              'native_tests_executed': False, 'service_resource_observation': False}
    try:
        result['job'] = job_identity()
        result['source_before'] = source_identity()
        result['process'] = run_process(build_command(), out / 'build.jsonl',
                                        stderr=out / 'build.stderr')
        require(process_succeeded(result['process'], build_command()), 'HISTORY_SOURCE_BUILD_FAILED')
        result['build_log'], raw = file_observation(out / 'build.jsonl', LOG_LIMIT, retain=True)
        binary = select_binary(raw)
        result['binary'], _ = file_observation(binary, BINARY_LIMIT)
    except BaseException as error:
        result['failures'].append(type(error).__name__ + ':' + str(error))
    finally:
        try:
            result['source_after'] = source_identity()
            require(result['source_before'] == result['source_after'], 'HISTORY_BUILD_SOURCE_CHANGED')
        except BaseException as error:
            result['failures'].append(type(error).__name__ + ':' + str(error))
        result['completed'] = not result['failures'] and result['binary'] is not None
        write_new(out / 'preparation.json', result)
    return result


def validate_preparation(out: Path, current_source: dict | None = None) -> dict:
    out = output_path(out)
    result, _ = load_object(out / 'preparation.json')
    require(result.get('schema') == PREPARATION_SCHEMA and result.get('target') == TARGET
            and result.get('selector') == SELECTOR and result.get('completed') is True
            and result.get('failures') == [] and result.get('native_tests_executed') is False
            and result.get('service_resource_observation') is False,
            'HISTORY_COMPLETE_PREPARATION_REQUIRED')
    require(result.get('job') == job_identity(), 'HISTORY_PREPARATION_JOB_CHANGED')
    require(result.get('build_env') == {key: os.environ.get(key) for key in BUILD_ENVIRONMENT},
            'HISTORY_PREPARATION_BUILD_ENV_CHANGED')
    source = source_identity() if current_source is None else current_source
    require(result.get('source_before') == result.get('source_after') == source,
            'HISTORY_PREPARATION_SOURCE_CHANGED')
    require(process_succeeded(result.get('process') or {}, build_command()),
            'HISTORY_SOURCE_BUILD_FAILED')
    log, raw = file_observation(out / 'build.jsonl', LOG_LIMIT, retain=True)
    require(log == result.get('build_log'), 'HISTORY_BUILD_LOG_CHANGED')
    binary, _ = file_observation(select_binary(raw), BINARY_LIMIT)
    require(binary == result.get('binary'), 'HISTORY_PREPARED_BINARY_CHANGED')
    return result


def native_command(out: Path, binary: Path) -> list[str]:
    return ['/usr/bin/time', '-v', '-o', str(out / 'history-resources.txt'),
            str(binary), SELECTOR, '--exact', '--ignored', '--show-output']


def validate_summary(summary: dict) -> None:
    # The unchanged native test owns full State, partial activation and reopen assertions.
    require(summary.get('schema') == SUMMARY_SCHEMA and summary.get('passed') is True,
            'HISTORY_NATIVE_COMPLETION_REQUIRED')
    require(type(summary.get('blocks')) is int and type(summary.get('confirmed_packets')) is int
            and summary['blocks'] == summary['confirmed_packets'] == 4105,
            'HISTORY_COMPLETE_4105_REQUIRED')
    require(type(summary.get('renewals')) is int and summary['renewals'] == 4
            and summary.get('corrupt_active_index_reopen_refused') is True,
            'HISTORY_RENEWAL_AND_CORRUPTION_REQUIRED')
    require(all(summary.get(key) is False for key in FALSE_FLAGS), 'HISTORY_SCOPE_PROMOTION')


def execution(out: Path) -> dict:
    out = output_path(out)
    # Create-only entry prevents a second attempt borrowing any previous native output.
    write_new(out / 'execution-start.json', {'schema': EXECUTION_SCHEMA, 'completed': False})
    result = {'schema': EXECUTION_SCHEMA, 'target': TARGET, 'selector': SELECTOR,
              'job': None, 'preparation_sha256': None, 'source_before': None, 'source_after': None,
              'binary_before': None, 'binary_after': None, 'process': None,
              'log': None, 'resources': None, 'summary_file': None, 'summary': None,
              'named_execution': None, 'failures': [], 'passed': False,
              'compilation_in_native_measurement': False, 'whole_test_command_preserved': True,
              'native_execution_authenticated': False, **{key: False for key in FALSE_FLAGS}}
    binary = None
    try:
        result['job'] = job_identity()
        result['source_before'] = source_identity()
        prepared = validate_preparation(out, result['source_before'])
        result['preparation_sha256'] = load_object(out / 'preparation.json')[1]['sha256']
        binary = Path(prepared['binary']['path'])
        result['binary_before'], _ = file_observation(binary, BINARY_LIMIT)
        require(not (out / 'long-history').exists(), 'HISTORY_OUTPUT_ALREADY_EXISTS')
        environment = dict(os.environ)
        environment['TRNM_INDEX_EVIDENCE_DIRECTORY'] = str(out / 'long-history')
        result['process'] = run_process(native_command(out, binary), out / 'history.log',
                                        environment=environment)
        require(process_succeeded(result['process'], native_command(out, binary)),
                'HISTORY_NATIVE_PROCESS_REQUIRED')
    except BaseException as error:
        result['failures'].append(type(error).__name__ + ':' + str(error))
    finally:
        # Each observation survives failure in another; no missing exit, report or identity is PASS.
        def observe(action):
            try:
                action()
            except BaseException as error:
                result['failures'].append(type(error).__name__ + ':' + str(error))

        def source_after():
            result['source_after'] = source_identity()
            require(result['source_before'] == result['source_after'], 'HISTORY_EXECUTION_SOURCE_CHANGED')

        def binary_after():
            if binary is not None:
                result['binary_after'], _ = file_observation(binary, BINARY_LIMIT)
                require(result['binary_before'] == result['binary_after'], 'HISTORY_EXECUTION_BINARY_CHANGED')

        def read_log():
            result['log'], raw = file_observation(out / 'history.log', LOG_LIMIT, retain=True)
            result['named_execution'] = validate_named_test(raw.decode('utf-8').splitlines(), SELECTOR)

        def read_resources():
            result['resources'], _ = file_observation(out / 'history-resources.txt', JSON_LIMIT)

        def read_summary():
            result['summary'], result['summary_file'] = load_object(out / 'long-history/summary.json')
            validate_summary(result['summary'])

        for observation in (source_after, binary_after, read_log, read_resources, read_summary):
            observe(observation)
        result['passed'] = not result['failures'] and result['process'] is not None
        write_new(out / 'manifest.json', result)
    return result


def bind_execution(prepared: dict, out: Path) -> dict:
    """Re-read the actual outcome after Host observation; never trust a flag alone."""
    require(validate_preparation(out) == prepared, 'HISTORY_PREPARATION_CHANGED')
    result, manifest = load_object(out / 'manifest.json')
    require(result.get('schema') == EXECUTION_SCHEMA and result.get('target') == TARGET
            and result.get('selector') == SELECTOR and result.get('job') == job_identity()
            and result.get('passed') is True and result.get('failures') == []
            and result.get('compilation_in_native_measurement') is False
            and result.get('whole_test_command_preserved') is True
            and result.get('native_execution_authenticated') is False
            and all(result.get(key) is False for key in FALSE_FLAGS),
            'HISTORY_EXACT_EXECUTION_REQUIRED')
    require(result.get('preparation_sha256') == load_object(out / 'preparation.json')[1]['sha256']
            and prepared['source_before'] == result.get('source_before') == result.get('source_after')
            and prepared['binary'] == result.get('binary_before') == result.get('binary_after'),
            'HISTORY_BUILD_EXECUTION_BINDING')
    require(process_succeeded(result.get('process') or {},
                              native_command(out, Path(prepared['binary']['path']))),
            'HISTORY_NATIVE_PROCESS_REQUIRED')
    log, raw = file_observation(out / 'history.log', LOG_LIMIT, retain=True)
    require(log == result.get('log')
            and validate_named_test(raw.decode('utf-8').splitlines(), SELECTOR)
            == result.get('named_execution'), 'HISTORY_NATIVE_LOG_CHANGED')
    resources, _ = file_observation(out / 'history-resources.txt', JSON_LIMIT)
    summary, summary_file = load_object(out / 'long-history/summary.json')
    validate_summary(summary)
    require(resources == result.get('resources') and summary_file == result.get('summary_file')
            and summary == result.get('summary'), 'HISTORY_NATIVE_REPORT_CHANGED')
    return {'schema': 'trnm-ci-history-build-execution-binding-v1',
            'manifest_sha256': manifest['sha256'], 'source_commit': prepared['source_before']['commit'],
            'binary_sha256': prepared['binary']['sha256'], 'exact_selector': SELECTOR,
            'compilation_in_native_measurement': False, 'runtime_limits_or_deadlines_changed': False}


class HistorySignal(Exception):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()

    def interrupted(number, _frame):
        raise HistorySignal(str(number))

    previous = {number: signal.signal(number, interrupted)
                for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = prepare(args.out) if args.prepare else execution(args.out)
        print(json.dumps({'schema': result['schema'], 'passed': result.get('completed', result.get('passed')),
                          'failures': result['failures'], 'target': TARGET, 'selector': SELECTOR}, sort_keys=True))
        return 0 if result.get('completed', result.get('passed')) is True else 1
    except (OSError, ValueError, KeyError, TypeError, HistorySignal) as error:
        print(json.dumps({'passed': False, 'failure': type(error).__name__ + ':' + str(error)}))
        return 1
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    raise SystemExit(main())
