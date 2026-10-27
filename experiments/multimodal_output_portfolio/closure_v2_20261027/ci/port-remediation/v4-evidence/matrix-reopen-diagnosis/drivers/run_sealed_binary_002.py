#!/usr/bin/env python3
"""Diagnose restored mode loss using the unchanged real CI executable in memory."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

ROOT = Path('/workspace/scratch/95988d8d3ab1')
REPO = ROOT / 'hepta-private-ci'
REMOTE = ROOT / 'ndu-port-remote-3a779a6'
OUT = Path(__file__).parent / 'execution-002'
ZIP = REMOTE / 'raw/ndu-port-tests-matrix-40503203294-1.zip'
ZIP_SHA = 'ac5260d4cb487988c470b3cf4dfd4ac5817f84a424c64b26628be76e7074fbf5'
BIN_SHA = '12e53b85e42fbb8e42658a987523425bd1dc3ada4d545d1f1ac0ba3710859448'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def tree(root):
    return {str(p.relative_to(root)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(root.rglob('*')) if p.is_file()}


def now():
    return datetime.now(timezone.utc).isoformat()


OUT.mkdir(exist_ok=False)
record = {'schema': 'hepta.matrix-reopen.permission-diagnosis.v1', 'started_at': now(),
          'scope': 'Diagnostic reuse of the unchanged v2 CI executable. No new-source qualification, new build or policy change.',
          'driver_sha256': sha(Path(__file__)), 'commands': [], 'arms': []}
shutil.copyfile(__file__, OUT / 'executed-source.py')
assert sha(ZIP) == ZIP_SHA
record['original_zip'] = {'path': str(ZIP), 'sha256': ZIP_SHA, 'bytes': ZIP.stat().st_size}
old_record = json.loads((REMOTE / 'old-matrix-small/RESULT.json').read_text())
old_fixture = REMOTE / 'old-matrix-small/fixture'
assert tree(old_fixture) == old_record['fixture_files']
record['pristine_fixture'] = old_record['fixture_files']
meta = REMOTE / 'producer/metadata.json'
binaries = REMOTE / 'matrix-small/reopen_old_version_fixture-binaries.json'
for name, path in [('cargo-metadata.json', meta), ('binaries-metadata.json', binaries)]:
    shutil.copyfile(path, OUT / name)
    record[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
listing = json.loads(binaries.read_text())
binary = listing['rust-binaries']['codex-hepta-matrix-sdk::store_version_migration']
relative_binary = Path(binary['binary-path']).relative_to(listing['rust-build-meta']['target-directory'])
target = OUT / 'relocated-target'
link = target / relative_binary
link.parent.mkdir(parents=True)
fd = os.memfd_create('hepta-unchanged-ci-matrix-019', os.MFD_ALLOW_SEALING)
try:
    digest = hashlib.sha256()
    size = 0
    with zipfile.ZipFile(ZIP) as archive:
        with archive.open('binaries/' + BIN_SHA) as source:
            for data in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(data)
                size += len(data)
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
    assert digest.hexdigest() == BIN_SHA
    os.fchmod(fd, 0o555)
    # Linux UAPI values checked in /usr/include/linux/fcntl.h.
    seals = 0x0008 | 0x0004 | 0x0002 | 0x0001
    fcntl.fcntl(fd, 1033, seals)
    assert fcntl.fcntl(fd, 1034) == seals
    mempath = Path('/proc') / os.readlink('/proc/self') / 'fd' / str(fd)
    assert sha(mempath) == BIN_SHA
    link.symlink_to(mempath)
    record['actual_binary'] = {'sha256': BIN_SHA, 'bytes': size, 'memfd_seals': seals,
                               'relocated_path': str(link), 'stored_on_disk': False}
    environment = dict(os.environ,
        PATH=os.pathsep.join([str(ROOT / 'ndu-rust196-format-tools/installed/bin'),
             str(ROOT / 'ndu-dependency-remediation/yaml-migration/bin'),
             str(ROOT / 'continuation_format_tools_20261027'), os.environ['PATH']]),
        PYTHONDONTWRITEBYTECODE='1', CARGO_NET_OFFLINE='true', CARGO_TERM_COLOR='never')
    reuse = ['--cargo-metadata', str(OUT / 'cargo-metadata.json'),
             '--binaries-metadata', str(OUT / 'binaries-metadata.json'),
             '--workspace-remap', str(REPO / 'codex-rs'), '--target-dir-remap', str(target)]
    def run(label, command, env):
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        with (OUT / (label + '.log')).open('wb') as output, (OUT / (label + '.stderr.log')).open('wb') as errors:
            result = subprocess.run(command, cwd=REPO / 'codex-rs', env=env,
                                    stdout=output, stderr=errors)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        item = {'label': label, 'command': command, 'exit_code': result.returncode,
                'seconds': time.monotonic() - started, 'log_sha256': sha(OUT / (label + '.log')),
                'user_seconds': after.ru_utime - before.ru_utime,
                'system_seconds': after.ru_stime - before.ru_stime}
        record['commands'].append(item)
        (OUT / 'RESULT.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(item), flush=True)
        return result.returncode
    status = run('test-inventory', [str(ROOT / 'ndu-dependency-remediation/yaml-migration/bin/cargo-nextest'),
                   'nextest', 'list', *reuse, '--message-format', 'json'], environment)
    if status:
        raise RuntimeError('Unchanged binary inventory failed; no testcase is eligible')
    test_list = json.loads((OUT / 'test-inventory.log').read_text())
    suites = test_list['rust-suites']
    names = {name for suite in suites.values() for name in suite['testcases']}
    assert names == {'encrypted_state_identity_session_and_queues_survive_restart',
                     'prepare_old_version_fixture', 'reopen_old_version_fixture'}
    (OUT / 'FROZEN_INPUTS.json').write_text(json.dumps(record, indent=2) + '\n')
    for label, mode in [('downloaded-mode-0644', 0o644), ('restored-mode-0600', 0o600)]:
        arm = OUT / label
        working = arm / 'pristine-fixture'
        shutil.copytree(old_fixture, working)
        sessions = list(working.rglob('session.json'))
        assert len(sessions) == 1
        sessions[0].chmod(mode)
        assert tree(working) == record['pristine_fixture']
        paths = {str(p.relative_to(working)): {'mode': stat.S_IMODE(p.stat().st_mode),
                 'links': p.stat().st_nlink} for p in working.rglob('*') if p.is_file()}
        store = arm / 'nextest-store'
        config = arm / 'nextest-store.toml'
        config.write_text('[store]\ndir = ' + json.dumps(str(store)) + '\n[profile.default.junit]\npath = "junit.xml"\n')
        arm_info = {'label': label, 'before_files': tree(working), 'before_permissions': paths,
                    'session_mode': mode, 'config_sha256': sha(config)}
        record['arms'].append(arm_info)
        (OUT / 'RESULT.json').write_text(json.dumps(record, indent=2) + '\n')
        trace = arm / 'network-syscalls.log'
        command = ['/usr/bin/strace', '-f', '-ttt', '-e', 'trace=network', '-o', str(trace),
                   str(ROOT / 'continuation_format_tools_20261027/just'), '--justfile', str(REPO / 'justfile'),
                   'test', *reuse, '--tool-config-file', 'hepta-diagnosis:' + str(config),
                   '--profile', 'default', '--run-ignored', 'only', '-E', 'test(=reopen_old_version_fixture)',
                   '--retries', '0', '--test-threads', '1', '--no-tests', 'fail']
        code = run(label, command, dict(environment, HEPTA_MATRIX_MIGRATION_FIXTURE=str(working)))
        arm_info.update(exit_code=code, after_files=tree(working), network_trace_sha256=sha(trace))
        junit = store / 'default/junit.xml'
        if junit.exists():
            arm_info['junit_sha256'] = sha(junit)
            xml = ET.parse(junit).getroot()
            arm_info['junit_cases'] = [{'name': case.get('name'), 'class': case.get('classname'),
                    'failed': case.find('failure') is not None, 'skipped': case.find('skipped') is not None}
                    for case in xml.iter('testcase')]
        assert sha(mempath) == BIN_SHA
        assert tree(old_fixture) == record['pristine_fixture']
        (OUT / 'RESULT.json').write_text(json.dumps(record, indent=2) + '\n')
    record['status'] = 'diagnostic_completed'
except Exception as error:
    record.update(status='diagnostic_failed_before_completion', error_type=type(error).__name__, error=str(error))
    print(json.dumps({'status': record['status'], 'error_type': type(error).__name__, 'error': str(error)}), flush=True)
    raise
finally:
    record.update(finished_at=now(), binary_dropped_after_diagnostic=True)
    os.close(fd)
    (OUT / 'RESULT.json').write_text(json.dumps(record, indent=2) + '\n')
