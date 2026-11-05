#!/usr/bin/env python3
"""Prepare exact source, then run the original tests in their fixed CI Host parent.

No native test, admission check, acceptance predicate or time budget is replaced.
The hosted runner provisions the checked-in unit; native code still owns the
original eligibility checks. This script must never provision a local workstation.
The same source build first warms this job's Cargo target outside the service
quota. The original runner still builds, hashes and executes inside that quota.
The history mode instead binds the existing separate, same-job build step and
executes its whole original test once, without adding a second build deadline.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from public_host_ci_observation import (PARENT, RUNTIME_UNIT, UNIT, UNIT_SHA256,
                                        capture, validate, write_new)
import run_from_zero_native as native
import run_history_native as history
import run_public_fixture_native as architecture
import public_fixture_host_lease as lease


ROOT = Path(__file__).resolve().parents[2]
PARENT_PROPERTIES = (
    'Id', 'LoadState', 'ActiveState', 'SubState', 'FragmentPath', 'SourcePath',
    'DropInPaths', 'ControlGroup', 'Transient', 'Job',
)
# Explicit non-secret build/source inputs only. Do not copy or inspect all env.
ENVIRONMENT = (
    'PATH', 'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL',
    'CARGO_TERM_COLOR', 'RUST_TEST_THREADS', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS',
    'RUSTUP_HOME', 'RUSTUP_TOOLCHAIN', 'CI', 'PYTHONDONTWRITEBYTECODE', 'RUNNER_TEMP',
    'OPENSSL_DIR', 'OPENSSL_STATIC', 'OPENSSL_CONF', 'OPENSSL_MODULES',
    'TRNM_PQ_OPENSSL', 'TRNM_PQ_OPENSSL_SHA256', 'TRNM_PQ_OPENSSL_VERSION',
    'GITHUB_ACTIONS', 'GITHUB_WORKSPACE', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
    'GITHUB_JOB', 'GITHUB_SHA', 'GITHUB_EVENT_NAME', 'GITHUB_EVENT_PATH',
    'TRNM_CI_RECEIPT_DIR', 'TRNM_EXPECTED_SOURCE_SHA', 'TRNM_EXPECTED_CANDIDATE_SHA',
    'TRNM_EXPECTED_BASE_SHA', 'TRNM_COST_RUNNER_LABEL',
    'TRNM_ARCHITECTURE_COMPARE_DIR',
    'EVALUATION_SYNC_OBSERVATION_EVIDENCE_DIR',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_unprovisioned_parent(raw: str) -> dict[str, str]:
    """Distinguish systemd's inactive implicit slice from a provisioned owner."""
    require(0 < len(raw) <= 65536 and '\x00' not in raw,
            'PARENT_PROPERTIES_BOUNDED')
    values = {}
    for line in raw.splitlines():
        key, separator, value = line.partition('=')
        require(separator == '=' and key in PARENT_PROPERTIES and key not in values,
                'PARENT_PROPERTIES_EXACT')
        values[key] = value
    require(set(values) == set(PARENT_PROPERTIES), 'PARENT_PROPERTIES_COMPLETE')
    require(values['Id'] == UNIT and values['LoadState'] in ('loaded', 'not-found')
            and values['ActiveState'] == 'inactive' and values['SubState'] == 'dead'
            and values['Transient'] == 'no' and values['Job'] in ('', '0'),
            'PARENT_ALREADY_OWNED_OR_ACTIVE')
    require(all(values[key] == '' for key in (
        'FragmentPath', 'SourcePath', 'DropInPaths', 'ControlGroup')),
        'PARENT_ALREADY_CONFIGURED_OR_ALLOCATED')
    return values


def validate_command(command: list[str]) -> Path:
    require(len(command) == 4 and command[:3] in ([
        'python3', 'scripts/ci/run_from_zero_native.py', '--out'], [
        'python3', 'scripts/ci/run_w1_fresh_service_v1.py', '--out'], [
        'python3', history.SCRIPT, '--out'], [
        'python3', architecture.SCRIPT, '--out']), 'ORIGINAL_ARGV_REQUIRED')
    out = Path(command[3])
    require(out.is_absolute() and not out.resolve().is_relative_to(ROOT),
            'OUTPUT_MUST_BE_OUTSIDE_CHECKOUT')
    return out


def environment_arguments(environment: dict[str, str]) -> list[str]:
    return ['--setenv=' + key + '=' + environment[key]
            for key in ENVIRONMENT if key in environment]


def service_command(service: str, receipts: Path, command: list[str],
                    uid: int, gid: int, environment: dict[str, str]) -> list[str]:
    return [
        'sudo', '-n', 'systemd-run', '--unit=' + service, '--wait', '--pipe', '--collect',
        '--service-type=exec', '--expand-environment=no', '--slice=' + UNIT,
        '--uid=' + str(uid), '--gid=' + str(gid), '--working-directory=' + str(ROOT),
        '--property=KillMode=control-group', '--property=TimeoutStopSec=20s',
        '--property=Delegate=no', '--property=NoNewPrivileges=yes',
        '--property=CapabilityBoundingSet=', *environment_arguments(environment),
        sys.executable, str(Path(__file__).resolve()), '--inside', str(receipts), service,
        str(uid), str(gid), '--', *command,
    ]


def prepare_native_build(receipts: Path) -> dict:
    """Bounded build-only preparation, never a service or test acceptance."""
    result = {'schema': 'trnm-ci-original-native-build-preparation-v1',
              'source_before': None, 'source_after': None, 'process': None,
              'binary_sha256': None, 'failure_type': None, 'source_error': None,
              'completed': False, 'native_tests_executed': False,
              'service_resource_observation': False,
              'consensus_or_model_authority': False}
    try:
        result['source_before'] = native.source_identity()
        result['build_env'] = {key: os.environ.get(key) for key in (
            'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL',
            'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTUP_TOOLCHAIN',
            'OPENSSL_DIR', 'OPENSSL_STATIC', 'OPENSSL_CONF', 'OPENSSL_MODULES',
            'TRNM_PQ_OPENSSL', 'TRNM_PQ_OPENSSL_SHA256', 'TRNM_PQ_OPENSSL_VERSION')}
        result['process'] = native.run_child(
            native.native_build_command(), receipts / 'prepare-build', 900)
        require(result['process']['exit_code'] == 0
                and result['process']['timed_out'] is False,
                'EXACT_NATIVE_PREPARATION_FAILED')
        binary = native.select_binary(
            (receipts / 'prepare-build/stdout').read_text().splitlines())
        require(binary.is_file() and not binary.is_symlink(), 'REGULAR_PREPARED_BINARY')
        result['binary_path'] = str(binary)
        result['binary_sha256'] = native.digest(binary.read_bytes())
    except BaseException as error:
        # Retain incomplete preparation even for the controller's signal unwind.
        # run_child owns and reaps its process group before propagating a signal.
        result['failure_type'] = type(error).__name__
        raise
    finally:
        try:
            result['source_after'] = native.source_identity()
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
            result['source_error'] = type(error).__name__
        result['completed'] = (result['failure_type'] is None
                               and result['source_error'] is None
                               and result['binary_sha256'] is not None
                               and result['source_before'] == result['source_after'])
        write_new(receipts / 'prepare-build.json', result)
    require(result['completed'], 'NATIVE_PREPARATION_SOURCE_CHANGED')
    return result


def bind_prepared_execution(prepared: dict, output: Path) -> dict:
    """Link this invocation's build to the original runner's actual execution."""
    require(prepared.get('completed') is True, 'NATIVE_PREPARATION_INCOMPLETE')
    path = output / 'manifest.json'
    require(path.is_file() and not path.is_symlink(), 'ORIGINAL_NATIVE_MANIFEST_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(native.REPORT_LIMIT + 1)
    require(len(raw) <= native.REPORT_LIMIT, 'ORIGINAL_NATIVE_MANIFEST_BOUND')
    result = native.json_load(raw)
    require(result.get('schema') == 'trnm-from-zero-native-execution-v3',
            'ORIGINAL_NATIVE_MANIFEST_SCHEMA')
    require(prepared['source_before'] == prepared['source_after']
            == result['source_before'] == result['source_after'],
            'PREPARATION_AND_EXECUTION_SOURCE_MISMATCH')
    require(prepared['binary_sha256'] == result['binary_sha256_before']
            == result['binary_sha256_after'], 'PREPARATION_AND_EXECUTION_BINARY_MISMATCH')
    require(result.get('passed') is True and result.get('all_named_tests_passed') is True
            and result.get('source_recompiled') is True
            and [row['name'] for row in result['runs']] == list(native.TESTS),
            'ORIGINAL_NATIVE_ACCEPTANCE_REQUIRED')
    return {'schema': 'trnm-ci-original-native-build-execution-binding-v1',
            'manifest_sha256': native.digest(raw),
            'source_commit': prepared['source_before']['commit'],
            'binary_sha256': prepared['binary_sha256'],
            'original_runner_repeated_source_build': True,
            'runtime_limits_or_deadlines_changed': False}


def bind_prepared_fresh_execution(prepared: dict, output: Path) -> dict:
    """Separate exact successor; never substitute its two tests for the old five."""
    import run_w1_fresh_service_v1 as fresh
    expected = os.environ.get('TRNM_EXPECTED_SOURCE_SHA')
    require(type(expected) is str and re.fullmatch('[0-9a-f]{40}', expected) is not None,
            'FRESH_EXPECTED_SOURCE_REQUIRED')
    require(prepared.get('completed') is True, 'NATIVE_PREPARATION_INCOMPLETE')
    path = output / 'manifest.json'
    require(path.is_file() and not path.is_symlink(), 'FRESH_NATIVE_MANIFEST_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(native.REPORT_LIMIT + 1)
    require(len(raw) <= native.REPORT_LIMIT, 'FRESH_NATIVE_MANIFEST_BOUND')
    result = native.json_load(raw)
    require(result.get('schema') == fresh.SCHEMA, 'FRESH_NATIVE_MANIFEST_SCHEMA')
    require(result.get('source_expected') == expected
            and prepared['source_before']['commit'] == expected,
            'FRESH_EXPECTED_SOURCE_MISMATCH')
    require(prepared['source_before'] == prepared['source_after']
            == result['source_before'] == result['source_after'],
            'PREPARATION_AND_EXECUTION_SOURCE_MISMATCH')
    require(prepared['binary_sha256'] == result['binary_sha256_before']
            == result['binary_sha256_after']
            == native.digest((output / native.TARGET).read_bytes()),
            'PREPARATION_AND_EXECUTION_BINARY_MISMATCH')
    require(result.get('requested_window_ns') == 4_000_000_000
            and result.get('attack_workers') == 16
            and result.get('passed') is True and result.get('all_named_tests_passed') is True
            and result.get('execution_finished') is True and result.get('source_recompiled') is True
            and result.get('failures') == []
            and [row['name'] for row in result['runs']] == list(fresh.SELECTORS),
            'FRESH_NATIVE_ACCEPTANCE_REQUIRED')
    for index, row in enumerate(result['runs']):
        name = 'original' if index == 0 else 'fresh'
        require(row.get('passed') is True and row.get('report_path') == name + '/report.json'
                and row['process'].get('expected_source') == result['source_before']['commit'],
                'FRESH_EXACT_EXECUTION_BINDING')
        log = output / (name + '.log')
        require(row.get('log_sha256') == native.digest(log.read_bytes()), 'FRESH_LOG_CHANGED')
        verified = fresh.validate_execution(row['process'], log, row['name'],
                                            output / row['report_path'])
        require(verified['named_execution'] == row.get('named_execution')
                and verified['report'] == row.get('report'), 'FRESH_REPORT_BINDING')
    return {'schema': 'trnm-ci-fresh-native-build-execution-binding-v1',
            'manifest_sha256': native.digest(raw), 'source_commit': prepared['source_before']['commit'],
            'binary_sha256': prepared['binary_sha256'], 'exact_selectors': list(fresh.SELECTORS),
            'original_five_test_runner_replaced': False,
            'runtime_limits_or_deadlines_changed': False}


def prepare_command(command: list[str], output: Path, receipts: Path) -> dict:
    if command[1] == architecture.SCRIPT:
        return architecture.validate_preparation(output)
    if command[1] == history.SCRIPT:
        return history.validate_preparation(output)
    return prepare_native_build(receipts)


def bind_command(command: list[str], prepared: dict, output: Path) -> dict:
    if command[1] == architecture.SCRIPT:
        return architecture.bind_execution(prepared, output)
    if command[1] == history.SCRIPT:
        return history.bind_execution(prepared, output)
    binder = (bind_prepared_fresh_execution if command[1]
              == 'scripts/ci/run_w1_fresh_service_v1.py' else bind_prepared_execution)
    return binder(prepared, output)


def inside(receipts: Path, service: str, uid: int, gid: int, command: list[str]) -> int:
    validate_command(command)
    before = capture('inside-before-native', service)
    errors = validate(before, inside=True, uid=uid, gid=gid, cwd=str(ROOT))
    write_new(receipts / 'inside-before.json', before)
    result = {'schema': 'trnm-ci-original-public-host-child-v1', 'command_argv': command,
              'native_child_exit': None, 'host_errors': errors,
              'host_readiness_only': True, 'consensus_or_model_authority': False}
    try:
        if not errors:
            result['native_child_exit'] = subprocess.run(command, cwd=ROOT).returncode
    finally:
        after = capture('inside-after-native', service)
        write_new(receipts / 'inside-after.json', after)
        result['host_errors'] += validate(after, inside=True, uid=uid, gid=gid,
                                         cwd=str(ROOT), reference=before)
        write_new(receipts / 'child-result.json', result)
    if result['host_errors']:
        return 1
    return result['native_child_exit'] if result['native_child_exit'] is not None else 1


class HostSignal(Exception):
    def __init__(self, number):
        self.number = number


def exit_status(result: dict) -> int:
    # A late signal/failure cannot retain a previously computed successful flag.
    if result.get('passed') is True and result.get('failure') is None:
        return 0
    return result.get('systemd_run_exit') or 1


def outer(command: list[str]) -> int:
    validate_command(command)
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('CI') == 'true',
            'HOSTED_CI_ONLY_NO_LOCAL_PROVISION')
    require(Path.cwd().resolve() == ROOT and os.getuid() != 0,
            'ORIGINAL_UNPRIVILEGED_RUNNER_REQUIRED')
    with lease.parent_lock():
        return outer_owned(command)


def prepare_parent(command: list[str], output: Path, receipts: Path, result: dict,
                   service: str, run_setup) -> dict:
    fresh = (not RUNTIME_UNIT.exists() and not RUNTIME_UNIT.is_symlink()
             and not PARENT.exists() and not PARENT.is_symlink())
    if not fresh:
        # This exception is confined to the exact current-ELF fixture registry.
        # The original from-zero, fresh-service and history modes still refuse.
        require(command[1] == architecture.SCRIPT, 'PARENT_ALREADY_PROVISIONED')
        result['preparation'] = prepare_command(command, output, receipts)
        run_setup(['systemctl', 'show', UNIT,
                   '--property=' + ','.join(lease.SYSTEMD_PROPERTIES)], 'actual-systemd-parent')
        current = capture('outside-before-reused-parent-service', service)
        result['parent_lease'] = lease.validate_for_reuse(current, receipts / 'actual-systemd-parent.log')
        result['parent_reused'] = True
        write_new(receipts / 'before-service.json', current)
        return current
    lease.require_no_seal()
    run_setup(['systemctl', 'show', '--all',
               '--property=' + ','.join(PARENT_PROPERTIES), UNIT], 'parent-properties')
    properties = validate_unprovisioned_parent((receipts / 'parent-properties.log').read_text())
    write_new(receipts / 'unprovisioned-parent.json', properties)
    # Original build-only preparation stays outside service measurement. The
    # current-ELF mode only binds the already running workspace binary.
    result['preparation'] = prepare_command(command, output, receipts)
    require(not RUNTIME_UNIT.exists() and not RUNTIME_UNIT.is_symlink()
            and not PARENT.exists() and not PARENT.is_symlink(), 'PARENT_CHANGED_BEFORE_INSTALL')
    unit_source = ROOT / 'config/systemd' / UNIT
    run_setup(['sudo', '-n', 'install', '-o', 'root', '-g', 'root', '-m', '0644',
               str(unit_source), str(RUNTIME_UNIT)], 'install-reviewed-unit')
    run_setup(['sudo', '-n', 'systemctl', 'daemon-reload'], 'systemd-reload')
    run_setup(['sudo', '-n', 'systemctl', 'start', UNIT], 'start-fixed-parent')
    run_setup(['systemctl', 'show', UNIT,
               '--property=' + ','.join(lease.SYSTEMD_PROPERTIES)], 'actual-systemd-parent')
    current = capture('outside-after-provision', service)
    write_new(receipts / 'after-provision.json', current)
    require(not validate(current, inside=False, uid=os.getuid(), gid=os.getgid(), cwd=str(ROOT)),
            'ACTUAL_PARENT_VALIDATION_FAILED')
    result['parent_lease'] = lease.seal_after_provision(current, receipts, command, run_setup)
    result['parent_reused'] = False
    return current


def outer_owned(command: list[str]) -> int:
    output = validate_command(command)
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('CI') == 'true',
            'HOSTED_CI_ONLY_NO_LOCAL_PROVISION')
    require(Path.cwd().resolve() == ROOT, 'ORIGINAL_WORKING_DIRECTORY')
    uid, gid = os.getuid(), os.getgid()
    require(uid != 0, 'ORIGINAL_UNPRIVILEGED_RUNNER_REQUIRED')
    run, attempt, job = (os.environ.get(key, '') for key in (
        'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB'))
    require(run.isdecimal() and attempt.isdecimal()
            and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job), 'BOUNDED_JOB_IDENTITY')
    service = f'trnm-from-zero-{run}-{attempt}-{job}-{os.getpid()}.service'
    receipts = output.with_name(output.name + '-host')
    receipts.mkdir(parents=True, exist_ok=False)
    result = {'schema': 'trnm-ci-original-public-host-controller-v2',
              'service': service, 'command_argv': command, 'uid': uid, 'gid': gid,
              'cwd': str(ROOT), 'systemd_run_exit': None, 'failure': None,
              'cleanup': None, 'passed': False, 'host_readiness_only': True,
              'consensus_or_model_authority': False}
    owned_service = False
    provisioned = None

    def run_setup(arguments: list[str], name: str, *, must_succeed=True):
        with (receipts / (name + '.log')).open('xb') as stream:
            completed = subprocess.run(arguments, stdout=stream, stderr=subprocess.STDOUT,
                                       timeout=30)
        require(not must_succeed or completed.returncode == 0, name + '_FAILED')
        return completed.returncode

    def interrupted(number, _frame):
        raise HostSignal(number)

    previous_handlers = {number: signal.signal(number, interrupted)
                         for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        write_new(receipts / 'before-provision.json', capture('before-provision', service))
        require(Path('/run/systemd/system').is_dir()
                and Path('/sys/fs/cgroup/cgroup.controllers').is_file(), 'SYSTEMD_CGROUP_V2_REQUIRED')
        unit_source = ROOT / 'config/systemd' / UNIT
        require(hashlib.sha256(unit_source.read_bytes()).hexdigest() == UNIT_SHA256,
                'REVIEWED_UNIT_BYTES')
        provisioned = prepare_parent(command, output, receipts, result, service, run_setup)
        run_setup(['systemctl', 'show', '--property=LoadState', '--value', service],
                  'child-load-state', must_succeed=False)
        require((receipts / 'child-load-state.log').read_text().strip() == 'not-found',
                'CHILD_SERVICE_ALREADY_EXISTS')
        environment = {key: os.environ[key] for key in ENVIRONMENT if key in os.environ}
        if 'RUSTUP_HOME' not in environment:
            environment['RUSTUP_HOME'] = subprocess.check_output(
                ['rustup', 'show', 'home'], text=True, timeout=30).strip()
        owned_service = True
        with (receipts / 'systemd-run.log').open('xb') as stream:
            result['systemd_run_exit'] = subprocess.run(
                service_command(service, receipts, command, uid, gid, environment),
                stdout=stream, stderr=subprocess.STDOUT).returncode
        child = json.loads((receipts / 'child-result.json').read_text())
        require(child['command_argv'] == command and not child['host_errors'],
                'ACTUAL_CHILD_HOST_VALIDATION_FAILED')
        for name in ('inside-before.json', 'inside-after.json'):
            sample = json.loads((receipts / name).read_text())
            require(not validate(sample, inside=True, uid=uid, gid=gid,
                                 cwd=str(ROOT), reference=provisioned),
                    'PROVISIONED_CHILD_CONTEXT_CHANGED:' + name)
        result['passed'] = result['systemd_run_exit'] == 0 and child['native_child_exit'] == 0
        if result['passed']:
            result['preparation_execution_binding'] = bind_command(
                command, result['preparation'], output)
    except HostSignal as error:
        result['failure'] = 'SIGNAL_' + str(error.number)
        result['systemd_run_exit'] = 128 + error.number
        result['passed'] = False
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result['failure'] = str(error)
        result['passed'] = False
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
        # The shared fixed parent is never stopped, widened or removed here.
        # Only the unique service this invocation attempted to create is owned.
        if owned_service:
            try:
                run_setup(['systemctl', 'show', '--property=LoadState', '--value', service],
                          'child-final-load-state', must_succeed=False)
                if (receipts / 'child-final-load-state.log').read_text().strip() == 'not-found':
                    result['cleanup'] = 'already-collected'
                else:
                    run_setup(['sudo', '-n', 'systemctl', 'stop', service], 'stop-owned-child')
                    result['cleanup'] = 'owned-child-stopped'
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                result['cleanup'] = str(error)
                result['passed'] = False
        after = capture('outside-after-child', service)
        write_new(receipts / 'outside-after.json', after)
        if provisioned is not None:
            result['final_host_errors'] = validate(after, inside=False, uid=uid, gid=gid,
                                                 cwd=str(ROOT), reference=provisioned)
            if result['final_host_errors']:
                result['passed'] = False
            try:
                run_setup(['systemctl', 'show', UNIT,
                           '--property=' + ','.join(lease.SYSTEMD_PROPERTIES)],
                          'actual-systemd-parent-after')
                result['final_parent_lease'] = lease.validate_for_reuse(
                    after, receipts / 'actual-systemd-parent-after.log')
                require(result['final_parent_lease'] == result['parent_lease'],
                        'FIXTURE_PARENT_SEAL_CHANGED_DURING_SERVICE')
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                result['final_parent_lease_error'] = str(error)
                result['passed'] = False
        write_new(receipts / 'controller-result.json', result)
    print(json.dumps(result, sort_keys=True))
    return exit_status(result)


if __name__ == '__main__':
    try:
        args = sys.argv[1:]
        if args[:1] == ['--inside']:
            require(len(args) >= 7 and args[5] == '--', 'INNER_ARGV')
            code = inside(Path(args[1]), args[2], int(args[3]), int(args[4]), args[6:])
        else:
            require(args[:1] == ['--'], 'EXPLICIT_ARGV_SEPARATOR_REQUIRED')
            code = outer(args[1:])
        raise SystemExit(code)
    except (OSError, ValueError) as error:
        print(json.dumps({'passed': False, 'failure': str(error), 'host_readiness_only': True}))
        raise SystemExit(1)
