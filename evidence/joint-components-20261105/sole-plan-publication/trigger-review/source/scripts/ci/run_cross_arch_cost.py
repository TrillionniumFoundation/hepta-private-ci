#!/usr/bin/env python3
"""Execute bounded native release costs; retain commands, raw output and failures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import time
import tomllib

from ci_observation import ROOT, digest, receipt_root, source
from check_cross_arch_cost import (ARCHITECTURES, CAMPAIGNS, SUITES, benchmark_arguments,
                                   elf_machine, suite_contract, COST_IDENTITY_TIMEOUT_SECONDS,
                                   COST_BUILD_TIMEOUT_SECONDS, COST_CAMPAIGN_TIMEOUT_SECONDS,
                                   COST_TERMINATION_GRACE_SECONDS)


def build_environment_overrides(environment: dict[str, str]) -> dict[str, str]:
    """Both Cargo spellings can select a compiler/wrapper or change codegen.

    A separate `rustc -vV` probe does not observe the compiler Cargo actually
    invokes when one of its configuration environment variables is supplied.
    Keep cache, registry and job-count settings available to the original owner.
    """
    names = {'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER',
             'RUSTC_WORKSPACE_WRAPPER', 'RUSTC', 'RUSTC_BOOTSTRAP',
             'CARGO_BUILD_RUSTFLAGS', 'CARGO_BUILD_RUSTC',
             'CARGO_BUILD_RUSTC_WRAPPER', 'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER',
             'CARGO_INCREMENTAL', 'CARGO_BUILD_INCREMENTAL', 'CARGO_BUILD_TARGET'}
    return {key: value for key, value in environment.items() if value and
            (key in names or key.startswith('CARGO_PROFILE_RELEASE_') or
             key.startswith('CARGO_TARGET_') and key != 'CARGO_TARGET_DIR')}


def cargo_configuration_snapshot(root: Path, environment: dict[str, str]) -> dict:
    """Hash bounded Cargo configuration inputs without publishing credentials.

    Cargo probes the invocation directory, every ancestor and CARGO_HOME, with
    both legacy `config` and `config.toml` spellings. Inspect both spellings even
    when one would currently shadow the other. Included files and unreviewed
    configuration sections are refused instead of silently changing the default
    release build. Cache/source/network settings remain usable with the lockfile.
    This is a build-contract observation, not host or supply-chain attestation.
    """
    root = root.resolve(strict=True)
    home = Path(environment.get('HOME', str(Path.home())))
    # Cargo's home resolver treats an empty CARGO_HOME as unset. HOME itself
    # may be empty/relative on Unix; filesystem lookup remains relative to the
    # actual Cargo invocation directory in either case.
    cargo_home = Path(environment.get('CARGO_HOME') or str(home / '.cargo'))
    if not cargo_home.is_absolute():
        cargo_home = root / cargo_home
    directories = list(dict.fromkeys([path / '.cargo' for path in [root, *root.parents]] +
                                    [cargo_home]))
    neutral_sections = {'alias', 'cache', 'cargo-new', 'credential-alias', 'doc',
                        'future-incompat-report', 'http', 'net', 'registries',
                        'registry', 'source', 'term'}
    files, violations = [], []
    for directory in directories:
        for name in ('config', 'config.toml'):
            path = directory / name
            entry = {'path': str(path), 'state': 'absent'}
            files.append(entry)
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            except FileNotFoundError:
                # A dangling symlink is an input, not an absent configuration.
                if path.is_symlink():
                    entry['state'] = 'unreadable'
                    violations.append({'path': str(path), 'reason': 'linked configuration'})
                continue
            except OSError:
                entry['state'] = 'unreadable'
                violations.append({'path': str(path), 'reason': 'unreadable or linked configuration'})
                continue
            try:
                with os.fdopen(descriptor, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError('configuration must be a regular file')
                    raw = stream.read(1024 * 1024 + 1)
                    after = os.fstat(stream.fileno())
                    if len(raw) > 1024 * 1024 or before.st_size != len(raw):
                        raise ValueError('configuration exceeds bounded complete read')
                    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                        raise ValueError('configuration changed during read')
                entry.update(state='regular', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                             resolved_path=str(path.resolve(strict=True)),
                             device=after.st_dev, inode=after.st_ino)
                value = tomllib.loads(raw.decode('utf-8'))
                for section in value:
                    if section == 'build':
                        table = value[section]
                        if type(table) is not dict:
                            violations.append({'path': str(path), 'reason': 'invalid build table'})
                            continue
                        for key in table:
                            if key not in {'jobs', 'target-dir', 'build-dir'}:
                                violations.append({'path': str(path), 'reason': 'build.' + key})
                    elif section not in neutral_sections:
                        violations.append({'path': str(path), 'reason': section})
            except (OSError, ValueError, UnicodeError, RuntimeError) as error:
                entry['state'] = 'invalid'
                # TOML decode errors may echo credential-bearing input. Retain
                # only the exception class and fixed boundary diagnostic.
                violations.append({'path': str(path),
                                   'reason': 'invalid configuration: ' + type(error).__name__})
    return {'schema': 'trnm-cost-cargo-configuration-v1', 'files': files,
            'violations': violations, 'configuration_semantics_attested': False}


def require_cargo_configuration(snapshot: dict) -> None:
    if snapshot['violations']:
        raise ValueError('release Cargo configuration changes the build contract; inspect retained key diagnostics')


def capture(command: list[str], output: Path, stem: str, *, timeout: float,
            cwd: Path = ROOT) -> dict:
    """Keep stdout and stderr even for a nonzero exit, signal or bounded timeout."""
    started = time.monotonic_ns()
    result = {'command': command, 'cwd': str(cwd), 'exit_code': None,
              'timed_out': False, 'timeout_seconds': timeout,
              'stdout': stem + '.stdout', 'stderr': stem + '.stderr'}
    with (output / result['stdout']).open('xb') as stdout, (output / result['stderr']).open('xb') as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
        except OSError as error:
            result['launch_error'] = str(error)
        else:
            try:
                result['exit_code'] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                result['timed_out'] = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=COST_TERMINATION_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                result['exit_code'] = 124
    result['elapsed_ns'] = time.monotonic_ns() - started
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=sorted(ARCHITECTURES), required=True)
    parser.add_argument('--suite', choices=SUITES, default='reused')
    parser.add_argument('--zero-version', type=int, choices=(1, 2), default=2,
                        help='explicit zero-locality execution schema; raw output must match this version')
    parser.add_argument('--local', action='store_true',
                        help='explicit local native preflight; cannot satisfy hosted artifact comparison')
    args = parser.parse_args()
    contract = suite_contract(args.suite, zero_version=args.zero_version)
    example = contract['example']
    output = receipt_root(contract['directory'])
    spec = ARCHITECTURES[args.arch]
    observations: list[dict] = []
    report = {'schema': contract['execution_schema'], 'result': 'FAIL',
              'execution_context': 'local-native-preflight' if args.local else 'github-hosted',
              'architecture': args.arch, 'runner_label': os.environ.get('TRNM_COST_RUNNER_LABEL'),
              'observations': observations, 'campaigns': [], 'build_profile': 'release',
              'compiler_channel': '1.95.0', 'target': spec['target'],
              'public_network_ready': False, 'independent_hardware_qualified': False,
              'resource_fairness_qualified': False, 'work_profile_qualified': False,
              'production_activation': False}
    report['runner_context'] = {key: os.environ.get(key) for key in
        ['GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_REPOSITORY',
         'GITHUB_EVENT_NAME', 'RUNNER_ARCH', 'RUNNER_OS', 'RUNNER_NAME', 'ImageOS', 'ImageVersion']}
    report['uname'] = dict(zip(['system', 'node', 'release', 'version', 'machine', 'processor'], platform.uname()))
    report['source_before'] = None
    configuration = {'schema': 'trnm-cost-build-configuration-receipt-v1',
                     'before': None, 'after': None, 'unchanged': False,
                     'default_release_configuration_checked': False}

    def checked(command: list[str], stem: str, timeout: int = COST_IDENTITY_TIMEOUT_SECONDS) -> dict:
        observed = capture(command, output, stem, timeout=timeout, cwd=ROOT)
        observations.append(observed)
        if observed['exit_code'] != 0 or observed['timed_out']:
            raise RuntimeError(f'{stem} failed; inspect retained stdout/stderr and command status')
        return observed

    try:
        report['source_before'] = source()
        if report['source_before']['source_state'] != 'committed-clean':
            raise ValueError('cost campaign requires actual committed source bytes')
        if report['uname']['machine'] != spec['machine'] or report['uname']['system'] != 'Linux':
            raise ValueError('requested architecture must actually execute on that native Linux host')
        if not args.local and report['runner_label'] != spec['runner']:
            raise ValueError('unexpected explicit hosted runner label')
        if not args.local and os.environ.get('RUNNER_ARCH') != spec['runner_arch']:
            raise ValueError('hosted runner architecture contradicts observed uname')
        if not args.local and (os.environ.get('GITHUB_ACTIONS') != 'true' or
                not os.environ.get('GITHUB_RUN_ID', '').isdigit() or
                not os.environ.get('GITHUB_RUN_ATTEMPT', '').isdigit()):
            raise ValueError('hosted observations require the actual workflow run context; use --local for preflight')
        overrides = build_environment_overrides(dict(os.environ))
        report['build_environment_overrides'] = overrides
        if overrides:
            raise ValueError('release compiler/target overrides would change the campaign build contract')
        configuration['before'] = cargo_configuration_snapshot(ROOT, dict(os.environ))
        require_cargo_configuration(configuration['before'])
        checked(['uname', '-a'], 'uname')
        checked(['rustc', '+1.95.0', '-vV'], 'rustc')
        checked(['cargo', '+1.95.0', '--version'], 'cargo')
        compiler = (output / 'rustc.stdout').read_text()
        if '\nrelease: 1.95.0\n' not in compiler or '\nhost: ' + spec['target'] + '\n' not in compiler:
            raise ValueError('actual native rustc identity differs from the pinned target/compiler')
        shutil.copyfile('/proc/cpuinfo', output / 'cpuinfo.txt')
        checked(['cargo', '+1.95.0', 'build', '--locked', '--release', '--manifest-path',
                 'trillionnium/Cargo.toml', '--target', spec['target'], '-p',
                 'trnm-crypto-primitives', '--example', example], 'build', COST_BUILD_TIMEOUT_SECONDS)
        binary = Path(os.environ['CARGO_TARGET_DIR']) / spec['target'] / 'release/examples' / example
        report['binary_elf_machine'] = elf_machine(binary)
        if report['binary_elf_machine'] != spec['elf_machine']:
            raise ValueError('compiled executable architecture differs from the actual host')
        report['binary_sha256_before'] = digest(binary)
        shutil.copyfile(binary, output / example)
        failed = False
        for index, campaign in enumerate(CAMPAIGNS):
            observed = capture([str(binary), *benchmark_arguments(campaign)], output,
                               f'campaign-{index}', timeout=COST_CAMPAIGN_TIMEOUT_SECONDS,
                               cwd=ROOT)
            observations.append(observed)
            row = {'configuration': campaign, 'observation': observed, 'result': 'FAIL'}
            try:
                if observed['exit_code'] != 0 or observed['timed_out']:
                    raise ValueError('native campaign failed or timed out')
                data = json.loads((output / observed['stdout']).read_text())
                row['validated'] = contract['validate_raw_report'](data, campaign)
                row['result'] = 'PASS'
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                row['error'] = str(error)
                failed = True
            report['campaigns'].append(row)
        report['binary_sha256_after'] = digest(binary)
        if report['binary_sha256_before'] != report['binary_sha256_after']:
            raise ValueError('measured binary changed during execution')
        if failed:
            raise ValueError('one or more native campaigns failed correctness/retention checks')
        report['result'] = 'PASS'
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        if configuration['before'] is not None:
            try:
                configuration['after'] = cargo_configuration_snapshot(ROOT, dict(os.environ))
                require_cargo_configuration(configuration['after'])
                configuration['unchanged'] = configuration['before'] == configuration['after']
                configuration['default_release_configuration_checked'] = configuration['unchanged']
                if not configuration['unchanged']:
                    raise ValueError('Cargo configuration changed during execution')
            except (OSError, ValueError) as error:
                configuration['error'] = str(error)
                report['result'] = 'FAIL'
        # Keep every existing execution/raw schema and historical input inventory.
        # The supplementary receipt has its own namespace and is retained/hash
        # inventoried. Its presence never retroactively certifies old artifacts.
        (output / 'build-configuration-v1.json').write_text(
            json.dumps(configuration, indent=2, sort_keys=True) + '\n')
        try:
            report['source_after'] = source()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report['source_after'] = {'error': str(error)}
        if report['source_before'] != report['source_after']:
            report['result'] = 'FAIL'
            report['source_changed'] = True
        else:
            report['source_changed'] = False
        inputs = contract['inputs']
        report['input_sha256'] = {name: digest(ROOT / name) for name in inputs if (ROOT / name).is_file()}
        report['artifact_sha256'] = {p.relative_to(output).as_posix(): digest(p)
                                     for p in sorted(output.rglob('*')) if p.is_file()}
        (output / 'manifest.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'result': report['result'], 'receipt': str(output)}, sort_keys=True))
    return 0 if report['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
