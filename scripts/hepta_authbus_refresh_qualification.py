"""Exact-branch AuthBus refresh diagnostic. No source edits or security setup."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

BASE = '66f0ba01bb444a245001d7d1fd21121fc8c01206'
BRANCH = 'refs/heads/dot/authbus-revocation-qualification-20261006'
PRODUCT = 'codex-rs/hepta-agentd/src/automation_effect_host.rs'
ORIGINAL_BLOB = 'b4573c8760e8550984aef084759e52bbd82726e0'
REVIEWED_BLOB = '7484825cdf90224bcd771695b9d9e692cdb26be7'
DIAGNOSTICS = ('.github/workflows/authbus-refresh-qualification.yml', 'scripts/hepta_authbus_refresh_qualification.py')
REQUIRED = 'automation_effect_host::tests::host_dispatches_exact_wire_payload_once'
PACKAGE = 'codex-hepta-agentd'
LIMIT = 16 * 1024**2


def git(*args, env=None):
    return subprocess.check_output(['git', '--no-replace-objects', *args], env=env, text=True).strip()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def remaining():
    seconds = int(float(os.environ['AUTHBUS_DEADLINE']) - time.time())
    if seconds < 30:
        raise ValueError('80-minute anchored diagnostic budget exhausted; remaining stages NOT RUN')
    return seconds


def identity():
    import hepta_ci_exec
    if os.environ.get('GITHUB_EVENT_NAME') != 'push' or os.environ.get('GITHUB_REF') != BRANCH:
        raise ValueError('Only the exact reviewed branch push is allowed')
    record = hepta_ci_exec.identity()
    head = record['commit']
    if record['dirty'] or head != os.environ['SOURCE_SHA'] or head != os.environ['TESTED_SHA']:
        raise ValueError('Source identity or clean-worktree check failed')
    if os.environ.get('HEPTA_CI_LANE') != 'source-head':
        raise ValueError('Source-head lane required')
    if record.get('parents') != [BASE]:
        raise ValueError('Single reviewed base parent required for this new branch')
    git('merge-base', '--is-ancestor', BASE, head)
    if git('rev-parse', f'{BASE}:{PRODUCT}') != ORIGINAL_BLOB or git('rev-parse', f'{head}:{PRODUCT}') != REVIEWED_BLOB:
        raise ValueError('Product blob differs from reviewed one-file change')
    if set(git('diff', '--name-only', BASE, head).splitlines()) != {PRODUCT, *DIAGNOSTICS}:
        raise ValueError('Unexpected source or diagnostic change')
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
        git('read-tree', head, env=env)
        git('update-index', '--force-remove', '--', *DIAGNOSTICS, env=env)
        git('update-index', '--add', '--cacheinfo', f'100644,{ORIGINAL_BLOB},{PRODUCT}', env=env)
        restored = git('write-tree', env=env)
    if restored != git('rev-parse', f'{BASE}^{{tree}}'):
        raise ValueError('Restored source projection does not equal exact reviewed base')
    return {'head': head, 'tree': record['tree'], 'base': BASE, 'product_blob': REVIEWED_BLOB,
            'diagnostic_blobs': {p: git('rev-parse', f'{head}:{p}') for p in DIAGNOSTICS}}


def read_json(path):
    if path.stat().st_size > LIMIT:
        raise ValueError('JSON evidence bound exceeded')
    return json.loads(path.read_text())


def discovery_names(data):
    suites = data.get('rust-suites', {})
    if len(suites) != 1:
        raise ValueError('Exactly the Agentd library suite must be discovered')
    suite = next(iter(suites.values()))
    if suite.get('package-name') != PACKAGE or suite.get('kind') != 'lib' or suite.get('status') != 'listed':
        raise ValueError('Unexpected discovery target or status')
    cases = suite['testcases']
    if data.get('test-count') != len(cases) or not cases:
        raise ValueError('Discovery count mismatch or empty suite')
    for case in cases.values():
        expected_match = {'status': 'mismatch', 'reason': 'ignored'} if case.get('ignored') else {'status': 'matches'}
        if case.get('filter-match') != expected_match:
            raise ValueError('Full library discovery unexpectedly filtered tests')
    runnable = sorted(name for name, case in cases.items() if not case['ignored'])
    ignored = sorted(name for name, case in cases.items() if case['ignored'])
    if REQUIRED not in runnable:
        raise ValueError('Required real product regression absent or ignored')
    return {'runnable': runnable, 'ignored': ignored, 'discovered': len(cases)}


def verify_junit(path, expected):
    raw = path.read_bytes()
    if len(raw) > LIMIT:
        raise ValueError('JUnit evidence bound exceeded')
    root = ET.fromstring(raw)
    cases = list(root.iter('testcase'))
    executed = [c for c in cases if not any(child.tag == 'skipped' for child in c)]
    names = [c.get('name') for c in executed]
    failures = [c.get('name') for c in executed if any(child.tag in ('failure', 'error', 'rerunFailure', 'rerunError') for child in c)]
    if len(names) != len(set(names)) or sorted(names) != sorted(expected):
        raise ValueError('Executed JUnit names/count differ from exact selected discovery')
    if failures:
        raise ValueError(f'Native failures: {failures}')
    if REQUIRED not in names:
        raise ValueError('Required product regression did not execute')
    return {'executed': len(names), 'passed': len(names), 'names': sorted(names),
            'reported_skipped': [c.get('name') for c in cases if c not in executed], 'sha256': hashlib.sha256(raw).hexdigest()}


def metadata(directory):
    policy = runpy.run_path('scripts/run-nextest.py', run_name='authbus_nextest_policy')
    workspace = Path.cwd() / 'codex-rs'
    if not policy['use_scoped_metadata'](['--locked', '--lib', '-p', PACKAGE], workspace):
        raise ValueError('Repository metadata policy requires broader resolution; do not bypass it')
    with (directory / 'cargo-metadata.json').open('x') as output:
        subprocess.run(['cargo', 'metadata', '--no-deps', '--format-version=1', '--locked', '--manifest-path', str(workspace / 'Cargo.toml')], stdout=output, check=True, timeout=remaining())
    data = read_json(directory / 'cargo-metadata.json')
    if data['resolve'] is not None or Path(data['workspace_root']).resolve() != workspace.resolve():
        raise ValueError('Metadata is not the fresh exact no-deps workspace')
    if PACKAGE not in {p['name'] for p in data['packages'] if p['id'] in data['workspace_members']}:
        raise ValueError('Agentd package missing')


def discovery(directory):
    with (directory / 'discovery.json').open('x') as output:
        subprocess.run(['cargo', 'nextest', 'list', '--locked', '--lib', '-p', PACKAGE,
                        '--cargo-metadata', str(directory / 'cargo-metadata.json'), '--message-format', 'json'],
                       cwd='codex-rs', stdout=output, check=True, timeout=remaining())
    save(directory / 'discovered-names.json', discovery_names(read_json(directory / 'discovery.json')))


def recorded_run(path, command):
    import hepta_ci_exec
    cancellation = hepta_ci_exec.CommandCancellation()
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, cancellation.request)
        return hepta_ci_exec.run(path, command, minimum_tests=0, timeout_seconds=remaining(), cancellation=cancellation)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def commands(directory):
    overlay = directory / 'junit-overlay.toml'
    shared = ['just', 'test', '--tool-config-file', f'authbus-refresh:{overlay}', '--cargo-metadata', str(directory / 'cargo-metadata.json'), '--locked', '--retries', '0', '--lib', '-p', PACKAGE]
    return [
        ('format', ['rustfmt', '--edition', '2024', '--check', PRODUCT]),
        ('metadata', [sys.executable, DIAGNOSTICS[1], 'metadata']),
        ('discovery', [sys.executable, DIAGNOSTICS[1], 'discovery']),
        ('focused', shared + ['--', REQUIRED, '--exact']),
        ('full-library', shared),
        ('strict-lint', ['just', 'clippy', '--locked', '--all-targets', '-p', PACKAGE, '--no-deps', '--', '-D', 'warnings']),
    ]


def run(directory):
    if shutil.disk_usage(directory).free < 8 * 1024**3:
        raise ValueError('Less than 8 GiB free before build; native qualification incomplete')
    # Reporting-only lower-priority overlay; no deadline/retry/test-thread overrides.
    (directory / 'junit-overlay.toml').write_text('[profile.local.junit]\npath = ' + json.dumps(str(directory / 'nextest-junit.xml')) + '\n')
    records = [{'name': n, 'command': c, 'status': 'not-run'} for n, c in commands(directory)]
    save(directory / 'stages.json', records)
    failed = False
    ready = set()
    for rec in records:
        name = rec['name']
        if name == 'discovery' and 'metadata' not in ready or name in ('focused', 'full-library') and 'discovery' not in ready:
            rec['error'] = 'Required preparation did not pass; stage NOT RUN'
            failed = True
            save(directory / 'stages.json', records)
            continue
        try:
            if name in ('focused', 'full-library'):
                (directory / 'nextest-junit.xml').unlink(missing_ok=True)
            code = recorded_run(directory / f'{name}.json', rec['command'])
            rec['exit_code'] = code
            native = read_json(directory / f'{name}.json')
            if native.get('interrupted_signal') is not None:
                rec['status'] = 'interrupted'
                save(directory / 'stages.json', records)
                return code or 2
            rec['status'] = 'passed' if code == 0 else 'failed'
            if native.get('output_limit_exceeded'):
                raise ValueError('Native output exceeded bound; evidence incomplete')
            if name in ('focused', 'full-library'):
                expected = [REQUIRED] if name == 'focused' else read_json(directory / 'discovered-names.json')['runnable']
                report = directory / 'nextest-junit.xml'
                shutil.copyfile(report, directory / f'{name}.junit.xml')
                rec['junit'] = verify_junit(report, expected)
            if code == 0:
                ready.add(name)
            failed |= code != 0
        except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
            rec.update(status='incomplete', error=str(error))
            failed = True
        save(directory / 'stages.json', records)
    return int(failed)


def stage(directory):
    destination = directory / 'upload'
    if destination.is_symlink():
        raise ValueError('Artifact destination must not be a symlink')
    destination.mkdir(exist_ok=True)
    if any(child.is_symlink() for child in destination.iterdir()):
        raise ValueError('Artifact destination contains a symlink')
    total = 0
    inventory = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise ValueError(f'Symlink evidence rejected: {path.name}')
        if not path.is_file() or path.suffix not in ('.json', '.xml', '.log', '.txt'):
            continue
        size = path.stat().st_size
        if size > LIMIT or total + size > 64 * 1024**2:
            raise ValueError(f'Artifact bound exceeded: {path.name}; no silent truncation')
        shutil.copyfile(path, destination / path.name)
        total += size
        inventory.append({'name': path.name, 'bytes': size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    save(destination / 'inventory.json', inventory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('before', 'after', 'metadata', 'discovery', 'run', 'stage', 'budget'))
    args = parser.parse_args()
    directory = Path(os.environ['AUTHBUS_EVIDENCE']).resolve()
    root = Path(git('rev-parse', '--show-toplevel')).resolve()
    if directory.is_relative_to(root):
        raise ValueError('Evidence must be outside source')
    directory.mkdir(parents=True, exist_ok=True)
    if args.phase == 'stage':
        stage(directory)
    elif args.phase == 'budget':
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'minutes={max(1, remaining() // 60)}\n')
    elif args.phase in ('before', 'after'):
        observed = identity()
        save(directory / f'source-{args.phase}.json', observed)
        if args.phase == 'after' and observed != read_json(directory / 'source-before.json'):
            raise ValueError('Source changed during execution')
    else:
        identity()
        if args.phase == 'metadata':
            metadata(directory)
        elif args.phase == 'discovery':
            discovery(directory)
        else:
            return run(directory)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
