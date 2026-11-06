"""Run one frozen, complete joint source with original commands and budgets.

This external coordinator is evidence machinery, not a repository gate change.
It never checks out, edits, commits, or retrospectively assigns a test binary.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

from test_elf_capture import ExecutedBinaryCapture
from nextest_fd_runner import task as process_identity
from nextest_fd_runner import NEURAL_RUNTIME_CASE_TARGETS
from fd_gate_evidence import verify as verify_fd_capture
from live_fd_correspondence import verify as verify_live_correspondence

ROOT = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf')
SOURCE = ROOT / 'source-h3'
TARGET = ROOT / 'target'
NEXT_TOOLS = Path('/home/qian-qi/work/hepta-pq-frontier-20261105-93bfcf/tools/bin')
UV_TOOLS = ROOT / 'tools/uv-0.11.3/bin'
HERE = Path(__file__).resolve().parent
BASE = '1556a4df6e279055fd8196f81a4ca2fe0f19384a'
H4_COMMIT = '6db78eca53a5acdda0d96873d3f4cd65863426f0'
H4_TREE = 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
H4_TRACKED_COUNT = 11840
H4_TRACKED_BYTES = 183410043
ORIGINAL_GUARD_SHA = 'e55f5ca1200b2c9fc5af4158c42f460e71f3815166a962a5b892acfe9477b1d1'
COLLECTOR_SHA = '2cb676bff1657866dc39b3e35ff45644d1ce75981ec9ed3f8798509287ab5ebe'
NEXT_SHA = 'e999c122a02c3fe74a1b66d254b6419a8a665e8bf540b1d31de7933a6d3753f1'
UV_SHA = 'fa5fc652fa5ed5b44fa8e7dda507f27975c02f59643787fd8ab4bf36f1ba7438'
FD_RUNNER_SHA = '9679cc6e11762c29b4c0ee92dd7715d3fce0555a6f8e0e10ed9d0b007951381a'
RUNNER_ENV = 'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER'
ENV = dict(os.environ)
ENV.update(RUSTUP_TOOLCHAIN='1.96.0', CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2',
           CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG='0', RUST_BACKTRACE='1',
           CARGO_TARGET_DIR=str(TARGET), CARGO_TERM_COLOR='never', GIT_TERMINAL_PROMPT='0',
           GIT_NO_LAZY_FETCH='1', PYTHONDONTWRITEBYTECODE='1', TMPDIR='/tmp',
           PATH=str(UV_TOOLS)+':'+str(NEXT_TOOLS)+':'+os.environ['PATH'])
for key in ('RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH'):
    ENV.pop(key, None)
os.environ.update({key: ENV[key] for key in ('GIT_NO_LAZY_FETCH', 'GIT_TERMINAL_PROMPT', 'PYTHONDONTWRITEBYTECODE')})
sys.dont_write_bytecode = True
START = time.monotonic()
STATE = {'status':'running-unqualified', 'started_unix':time.time(), 'gates':{},
         'scope':'one desktop source-head; no hosted matrix, independent custody, WAN, full-host restore, model inference, or learning qualification'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(name, value):
    path = EVIDENCE / name
    pending = path.with_name(path.name + '.pending')
    with pending.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def git(*args):
    return subprocess.check_output(['git', '-c', 'gc.auto=0', *args], cwd=SOURCE, env=ENV, timeout=120)


def publish(phase, **fields):
    STATE.update(phase=phase, timed_coordinator_elapsed_seconds=time.monotonic()-START, **fields)
    save('pipeline-status.json', STATE)
    print(json.dumps({'phase':phase, 'status':STATE['status'], **fields}), flush=True)


def raw_guard(label):
    path = SOURCE / 'scripts/hepta_ci_exec.py'
    assert digest(path) == ORIGINAL_GUARD_SHA
    spec = importlib.util.spec_from_file_location('original_hepta_ci_exec', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = module.identity(repository=SOURCE)
    matched = module.worktree_blobs_match(repository=SOURCE)
    inventory = git('ls-tree', '-r', '-l', '-z', 'HEAD')
    count = total = 0
    missing = []
    for entry in inventory.split(b'\0'):
        if not entry:
            continue
        header, name = entry.split(b'\t', 1)
        mode, kind, oid, size = header.split()
        assert kind == b'blob'
        count += 1
        total += int(size)
        if not os.path.lexists(SOURCE / os.fsdecode(name)):
            missing.append(os.fsdecode(name))
    flags = [v for v in git('ls-files', '-v', '-z').decode().split('\0') if v]
    hidden = [v for v in flags if v[0] == 'S' or v[0].islower()]
    result = {'identity':identity, 'raw_git_blob_bytes_match':matched,
              'tracked_count':count, 'tracked_bytes':total, 'index_count':len(flags),
              'missing':missing, 'hidden':hidden, 'tree_inventory_sha256':hashlib.sha256(inventory).hexdigest(),
              'guard_sha256':digest(path), 'cargo_lock_sha256':digest(SOURCE / 'codex-rs/Cargo.lock'),
              'toolchain_file_sha256':digest(SOURCE / 'codex-rs/rust-toolchain.toml'),
              'nextest_config_sha256':digest(SOURCE / 'codex-rs/.config/nextest.toml')}
    save(label + '.json', result)
    return result


def exact_source(result):
    return (result['identity']['commit'] == ARGS.commit and result['identity']['tree'] == ARGS.tree
            and not result['identity']['dirty'] and result['raw_git_blob_bytes_match']
            and result['tracked_count'] == result['index_count'] and not result['missing'] and not result['hidden'])


def tool(command):
    p = subprocess.run(command, cwd=SOURCE, env=ENV, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (command, p.stderr)
    return p.stdout.strip()


def observed_runtime_inputs(label):
    # This is an explicitly scoped before/after observation, not an import
    # trace and not proof of the complete ignored/dynamic runtime closure.
    ignored = sorted(v for v in git('ls-files', '--others', '--ignored', '--exclude-standard', '-z').decode().split('\0') if v)
    records = []
    destination = EVIDENCE / ('observed-bytecode-' + label)
    destination.mkdir(mode=0o700)
    for path in sorted((SOURCE / 'scripts/__pycache__').glob('*.pyc')):
        before = path.stat(follow_symlinks=False)
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        after = path.stat(follow_symlinks=False)
        assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        sha = hashlib.sha256(raw).hexdigest()
        copy = destination / (sha + '.pyc')
        if not copy.exists():
            copy.write_bytes(raw)
        source = Path(importlib.util.source_from_cache(str(path)))
        records.append({'path':str(path), 'sha256':sha, 'bytes':len(raw),
                        'mtime_ns':before.st_mtime_ns, 'ctime_ns':before.st_ctime_ns,
                        'retained_copy':str(copy), 'corresponding_source':str(source),
                        'corresponding_source_sha256':digest(source) if source.is_file() else None})
    result = {'scope':'all Git-reported ignored paths; raw bytecode retention only scripts/__pycache__/*.pyc; no per-import or complete runtime-closure claim',
              'source_commit':ARGS.commit, 'source_tree':ARGS.tree,
              'ignored_paths':ignored, 'bytecode':records,
              'observed_unix':time.time(), 'interpreter':sys.executable,
              'interpreter_sha256':digest(sys.executable), 'interpreter_version':sys.version,
              'external_configuration_sha256':{p.name:digest(p) for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.json')}}
    save('runtime-inputs-' + label + '.json', result)
    return result


def gate(name, command, minimum=0, timeout_seconds=600, *, crate=None, names=None, predicate=None, offline=True, case_targets=None):
    assert time.monotonic() - START < 5400, 'original total 90-minute budget exhausted'
    env = dict(ENV, SOURCE_SHA=ARGS.commit, TESTED_SHA=ARGS.commit, BASE_SHA=BASE,
               HEPTA_CI_LANE='source-head', CARGO_NET_OFFLINE=str(offline).lower(),
               HEPTA_PQ_EFFECT_SOURCE_ROOT=str(SOURCE),
               HEPTA_PQ_EFFECT_PROCESS_EVIDENCE_DIR=str(EVIDENCE / 'effect-pq-product-process'))
    if not offline:
        env.update(CARGO_NET_RETRY='5', CARGO_HTTP_TIMEOUT='60', CARGO_HTTP_MULTIPLEXING='false')
    output = EVIDENCE / (name + '.json')
    args = [sys.executable, 'scripts/hepta_ci_exec.py', '--output', str(output), '--minimum-tests', str(minimum)]
    if timeout_seconds is not None:
        args += ['--timeout-seconds', str(timeout_seconds)]
    args += ['--', *command]
    identity = {'commit':ARGS.commit, 'tree':ARGS.tree, 'lock_sha256':digest(SOURCE / 'codex-rs/Cargo.lock'),
                'environment_file':'native-environment.json', 'environment_sha256':digest(EVIDENCE / 'native-environment.json')}
    selected = (lambda value: value in names) if names is not None else (lambda value: value.startswith(predicate['value']) if predicate['kind'] == 'prefix' else predicate['value'] in value and '::' in value)
    if case_targets is not None:
        assert name == 'neural-runtime-input' and crate is None
        assert case_targets == NEURAL_RUNTIME_CASE_TARGETS and names == set(case_targets)
        assert predicate is None
        captures = [ExecutedBinaryCapture(name + '-' + target, target,
                    lambda value, target=target: case_targets.get(value) == target,
                    identity, target=TARGET, evidence=EVIDENCE)
                    for target in sorted(set(case_targets.values()))]
    else:
        captures = [ExecutedBinaryCapture(name, crate, selected, identity,
                    target=TARGET, evidence=EVIDENCE)] if crate else []
    fd_config = None
    if captures:
        directory = EVIDENCE / ('fd-executed-binaries-' + name)
        directory.mkdir(mode=0o700)
        fd_config = EVIDENCE / (name + '.fd-capture-config.json')
        configuration = {'schema':'hepta-nextest-fd-runner-v1', 'target':str(TARGET.resolve()),
             'crate':crate, 'gate':name, 'directory':str(directory),
             'selected_names':sorted(names) if names is not None else None, 'predicate':predicate,
             'source':identity, 'coordinator':{'pid':os.getpid(), 'start_ticks':process_identity(os.getpid())[1]}}
        if case_targets is not None:
            configuration.update(schema='hepta-nextest-fd-runner-v2', expected_case_targets=case_targets)
        save(fd_config.name, configuration)
        # cargo-nextest 0.9.103 splits this value on whitespace. Both paths are
        # exact, absolute and contain no whitespace. The fd-exec wrapper keeps
        # the original test process/group and original per-test timer.
        runner = [sys.executable, str(HERE / 'nextest_fd_runner.py')]
        assert all(Path(value).is_absolute() and not re.search(r'\s', value) for value in runner)
        env[RUNNER_ENV] = ' '.join(runner)
        env['HEPTA_NEXTEST_FD_CAPTURE_CONFIG'] = str(fd_config)
    publish(name, current_command=args, current_source=identity)
    artifacts = None
    for capture in captures:
        capture.start()
    try:
        with (EVIDENCE / (name + '.wrapper.log')).open('xb') as log:
            process = subprocess.Popen(args, cwd=SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for capture in captures:
                    capture.bind(process.pid)
            finally:
                # A capture binding error must not abandon the running wrapper.
                process.wait()
            # The unchanged wrapper owns the command deadline and process-group
            # cleanup. The durable outer job retains the original 90-minute cap.
    finally:
        if captures:
            completed_captures = [capture.finish() for capture in captures]
            artifacts = completed_captures[0] if case_targets is None else {
                'records': [record for result in completed_captures for record in result['records']],
                'errors': [error for result in completed_captures for error in result['errors']],
                'target_captures': {capture.crate: result for capture, result in zip(captures, completed_captures, strict=True)},
                'capture_scope': 'two explicitly mapped target collectors; no global binary allowance or inferred short-process coverage'}
            save(name + '.live-polled-binaries.json', artifacts)
    record = json.loads(output.read_text())
    raw = (EVIDENCE / record['log_file']).read_bytes() if record.get('log_file') else b''
    assert not record.get('log_file') or hashlib.sha256(raw).hexdigest() == record['log_sha256']
    clean_text = re.sub(r'\x1b\[[0-9;]*m', '', raw.decode('utf-8', errors='replace'))
    cases = re.findall(r'^test ([A-Za-z0-9_:]+) \.\.\. (ok|ignored|FAILED)\s*$', clean_text, re.M)
    names_ok = None
    if names is not None:
        passed = [test for test, result in cases if result == 'ok']
        names_ok = len(cases) == len(names) == len(passed) and set(passed) == set(names)
    if artifacts is not None:
        live = artifacts
        declared = [int(n) for n in re.findall(r'Starting\s+\d+\s+tests?\s+across\s+(\d+)\s+binar', clean_text)]
        artifacts = verify_fd_capture(fd_config, HERE / 'nextest_fd_runner.py', cases, declared)
        artifacts['live_polling_corroboration'] = {'file':name + '.live-polled-binaries.json',
            'sha256':digest(EVIDENCE / (name + '.live-polled-binaries.json')),
            'captured_processes':len(live['records']), 'errors':live['errors'],
            'scope':'polling may miss short processes; no assignment of missed processes from other captures'}
        if live['errors']:
            artifacts['errors'].append('live collector reported an identity/capture error')
        correspondence = verify_live_correspondence(name, artifacts, live)
        artifacts['live_process_correspondence'] = correspondence
        if correspondence['errors']:
            artifacts['errors'].append('live process observation is not an exact FD case or the explicitly bound FinalUse child')
        save(name + '.fd-executed-binaries.json', artifacts)
    STATE['gates'][name] = {'receipt':output.name, 'receipt_sha256':digest(output), 'wrapper_exit':process.returncode,
        'status':record['status'], 'command_exit_code':record.get('command_exit_code'),
        'passed':record.get('observed_passed_tests'), 'failed':record.get('observed_failed_tests'),
        'timed_out':record.get('timed_out'), 'log_file':record.get('log_file'),
        'execution_family':'original-pq-policy-workflow' if name in ORIGINAL_NAMES else 'additional-original-gate',
        'command_budget_seconds':3600 if timeout_seconds is None else timeout_seconds,
        'timeout_argument_omitted_for_original_default':timeout_seconds is None,
        'started_at':record.get('started_at'),'finished_at':record.get('finished_at'),'wrapper_elapsed_seconds':record.get('elapsed_seconds'),
        'source':identity, 'observed_cases':cases, 'exact_names_passed':names_ok, 'actual_binary_evidence':artifacts}
    publish(name + '_complete')
    assert record['status'] == 'passed' and process.returncode == 0 and record.get('command_exit_code') == 0, name + ' original gate did not pass'
    if names is not None:
        assert names_ok, name + ' did not execute every exact selected case once'
    if artifacts is not None:
        expected_count = 2 if case_targets is not None else 1
        assert not artifacts['errors'] and artifacts['per_case_bijection_verified'] and len(artifacts['unique_actual_elf_sha256']) == expected_count and artifacts['runner_declared_binary_counts'] == [expected_count], name + ' lacks an exact per-case test-image binding'
        if case_targets is not None:
            assert artifacts['expected_case_targets'] == case_targets
            assert set(artifacts['actual_images_by_target']) == set(case_targets.values())
    if name == 'full-evidence-library':
        expected_ignored = json.loads((HERE / 'h4-extra-controls.json').read_text())['full_evidence_library']['expected_ignored']
        declared = re.findall(r'Starting\s+(\d+)\s+tests?\s+across\s+1\s+binar(?:y|ies)\s+\((\d+)\s+tests?\s+skipped\)', clean_text)
        assert declared == [('161','1')], 'full library selected/ignored cardinality differs from the fixed source expectation'
        actual_paths = {record['actual_executable'] for record in artifacts['records']}
        assert len(actual_paths) == 1
        actual_path = Path(next(iter(actual_paths)))
        expected_sha = artifacts['unique_actual_elf_sha256'][0]
        image_before = actual_path.stat()
        assert digest(actual_path) == expected_sha
        with (EVIDENCE / 'full-evidence-ignored-list.log').open('xb') as log:
            listing = subprocess.run([str(actual_path),'--list','--ignored','--format','terse'],cwd=SOURCE,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=20)
        image_after = actual_path.stat()
        actual_ignored = sorted(re.findall(r'^([A-Za-z0-9_:]+): test$',(EVIDENCE/'full-evidence-ignored-list.log').read_text(),re.M))
        same_image = (image_before.st_dev,image_before.st_ino,image_before.st_size,image_before.st_mtime_ns,image_before.st_ctime_ns) == (image_after.st_dev,image_after.st_ino,image_after.st_size,image_after.st_mtime_ns,image_after.st_ctime_ns)
        save('full-evidence-ignored-list.json',{'scope':'classification from already captured exact ELF; no new test execution credit','command':[str(actual_path),'--list','--ignored','--format','terse'],'exit_code':listing.returncode,'source':identity,'sha256':expected_sha,'same_image':same_image,'expected_ignored':expected_ignored,'actual_ignored':actual_ignored,'log_sha256':digest(EVIDENCE/'full-evidence-ignored-list.log')})
        assert listing.returncode == 0 and same_image and digest(actual_path) == expected_sha and actual_ignored == expected_ignored
    if name == 'effect-pq-product':
        completed = list((EVIDENCE / 'effect-pq-product-process').glob('*/completed.json'))
        assert len(completed) == 1, 'one actual ordinary process receipt is required'
        proof = json.loads(completed[0].read_text())
        assert proof['source']['qualification_binding'] is True
        assert proof['source']['commit'] == ARGS.commit and proof['source']['tree'] == ARGS.tree
        assert proof['post_count'] == proof['physical_apply_count'] == proof['used_nonces'] == 1 and proof['lookup_count'] == 2
        first, second = proof['first_process'], proof['second_process']
        assert first['source'] == second['source'] == proof['source']
        assert first['capture_method'] == 'first-live-fd-hash-copy' and first['full_hash_and_copy_this_capture'] is True
        assert first['same_held_file_object_verified'] is False
        assert second['capture_method'] == 'same-held-file-object-reuse' and second['full_hash_and_copy_this_capture'] is False
        assert second['same_held_file_object_verified'] is True
        for field in ('actual_executable', 'cargo_resolved_binary', 'retained_copy', 'sha256', 'bytes', 'device', 'inode'):
            assert first[field] == second[field], 'second generation did not retain the same held file object'
        for image in (first, second):
            assert image['origin_capture_pid'] == first['pid'] and image['origin_capture_start_ticks'] == first['start_ticks']
        assert (first['pid'], first['start_ticks']) != (second['pid'], second['start_ticks'])
        assert second['spawn_generation'] > first['spawn_generation']
        for phase in ('first_process', 'second_process'):
            image = proof[phase]
            retained = Path(image['retained_copy'])
            assert retained.is_relative_to(EVIDENCE) and retained.stat().st_size == image['bytes'] and digest(retained) == image['sha256']
            assert image['owner_and_generation_verified'] and image['opened_fd_and_process_identity_verified']
        save('effect-pq-product-daemon-verification.json', {'completed':str(completed[0]), 'sha256':digest(completed[0]), 'verified':True})


def main():
    assert re.fullmatch(r'[0-9a-f]{40}', ARGS.commit) and re.fullmatch(r'[0-9a-f]{40}', ARGS.tree)
    assert re.fullmatch(r'[a-z0-9-]+', ARGS.evidence_name)
    EVIDENCE.mkdir(mode=0o700)
    before = raw_guard('full-source-before')
    assert exact_source(before), 'full frozen source guard failed before any command'
    assert before['tracked_count'] == H4_TRACKED_COUNT and before['tracked_bytes'] == H4_TRACKED_BYTES
    assert ARGS.commit == H4_COMMIT and ARGS.tree == H4_TREE
    STATE['source_before'] = before
    global ORIGINAL_NAMES
    plan = json.loads((HERE / 'h4-native-plan.json').read_text())
    assert plan['source_frozen'] and plan['source_commit'] == ARGS.commit and plan['source_tree'] == ARGS.tree
    assert plan['execution_configuration_frozen'], 'external H4 execution configuration is not frozen'
    ORIGINAL_NAMES = {step['name'] for step in plan['steps']} | {'format'}
    STATE['budget_semantics'] = {'outer_seconds':5400,'scope':'entire actual coordinator job, including raw guards, tool identity, capture and additional gates; never a sum-of-command estimate','prerequisites':'prior isolated uv installation and toolchain provisioning retained separately; not charged as native compilation or credited as tests','original_workflow_subflow':'every original command retains its existing deadline inside the same 90-minute outer limit','additional_gates':'source135/32, compatibility6, provider10, FinalUse and full evidence have independent original wrapper receipts; no hosted-matrix/job qualification'}
    assert digest(SOURCE / plan['workflow_path']) == plan['workflow_sha256']
    assert digest(HERE / 'h4-selected-tests-guard.py') == plan['exact_guard_sha256']
    assert digest(HERE / 'test_elf_capture.py') == COLLECTOR_SHA
    assert digest(HERE / 'nextest_fd_runner.py') == FD_RUNNER_SHA
    assert not ENV.get(RUNNER_ENV), 'an undeclared inherited target runner exists'
    assert digest(NEXT_TOOLS / 'cargo-nextest') == NEXT_SHA
    preparation = json.loads((ROOT / 'evidence/h3-final-source/result.json').read_text())
    assert preparation['source'] == ARGS.commit and preparation['tree'] == ARGS.tree
    configs = [Path(path) for path in preparation['configurations']]
    STATE['configuration_before'] = {str(p):digest(p) for p in configs}
    assert STATE['configuration_before'] == preparation['configurations']
    runtime_before = observed_runtime_inputs('before')
    try:
        git('diff', '--check', BASE, 'HEAD')
        uv_version = tool(['uv', '--version'])
        assert uv_version.startswith('uv 0.11.3'), uv_version
        assert digest(UV_TOOLS/'uv') == UV_SHA
        uv_provenance = json.loads((ROOT/'evidence/uv-0.11.3-provenance/provenance.json').read_text())
        assert uv_provenance['launcher_sha256'] == UV_SHA and uv_provenance['actual_wheel_sha256'] == uv_provenance['pypi_sha256']
        assert digest(uv_provenance['retained_wheel']) == uv_provenance['pypi_sha256']
        with (EVIDENCE / 'v8-setup.log').open('xb') as log:
            subprocess.run([sys.executable, 'scripts/hepta_ci_v8.py'], cwd=SOURCE,
                env=dict(ENV, CODEX_REPO_ROOT=str(SOURCE), PYTHONPATH=str(SOURCE / 'scripts'), GITHUB_ENV=str(EVIDENCE / 'v8.env')),
                stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
        v8 = {}
        v8_file = EVIDENCE / 'v8.env'
        if v8_file.exists():
            for line in v8_file.read_text().splitlines():
                key, value = line.split('=', 1)
                assert key in ('RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH') and key not in v8
                v8[key] = {'path':value, 'sha256':digest(value), 'bytes':Path(value).stat().st_size}
                ENV[key] = value
            assert len(v8) == 2
        env_keys = ['RUSTUP_TOOLCHAIN','CARGO_INCREMENTAL','CARGO_BUILD_JOBS','CARGO_PROFILE_TEST_DEBUG','CARGO_PROFILE_DEV_DEBUG','RUST_BACKTRACE','CARGO_TARGET_DIR','CARGO_TERM_COLOR','GIT_NO_LAZY_FETCH','PYTHONDONTWRITEBYTECODE','TMPDIR','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER']
        binaries = {name:Path(shutil.which(name, path=ENV['PATH'])) for name in ['just','cargo-nextest','uv','python3']}
        for name in ['rustc','cargo']:
            binaries[name] = Path(tool(['rustup','which',name]))
        environment = {'source':before, 'environment':{key:ENV.get(key) for key in env_keys},
            'rustc':tool(['rustc','-vV']), 'cargo':tool(['cargo','--version']), 'just':tool(['just','--version']),
            'nextest':tool(['cargo','nextest','--version']), 'uv':uv_version, 'python':tool([sys.executable,'--version']),
            'platform':list(os.uname()), 'cpu_count':os.cpu_count(), 'v8':v8, 'uv_provenance':uv_provenance,
            'kernel_options':{name:(Path('/proc/sys')/name).read_text().strip() if (Path('/proc/sys')/name).exists() else None for name in ['kernel/unprivileged_userns_clone','kernel/apparmor_restrict_unprivileged_userns']},
            'kernel_scope':'observed desktop values retained unchanged; the hosted workflow sets AppArmor userns restriction to zero, so this local run does not claim the complete hosted environment',
            'tools':{name:{'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size} for name,path in binaries.items()},
            'scripts':{name:digest(HERE/name) for name in ['run_h4_native_pipeline.py','test_elf_capture.py','test_executed_binary_capture.py','nextest_fd_runner.py','test_nextest_fd_runner.py','test_fd_gate_targets.py','fd_gate_evidence.py','live_fd_correspondence.py','test_live_fd_correspondence.py','h4-native-plan.json','h4-selected-tests-guard.py','h4-extra-controls.json']},
            'new_h4_execution_configuration':{'environment_variable':RUNNER_ENV, 'value':sys.executable+' '+str(HERE/'nextest_fd_runner.py'), 'config_variable':'HEPTA_NEXTEST_FD_CAPTURE_CONFIG', 'per_gate_configs':'*.fd-capture-config.json', 'runner_sha256':FD_RUNNER_SHA, 'source':'official cargo-nextest 0.9.103 host-target runner interface independently reviewed', 'scope':'new explicit H4 configuration; only neural-runtime-input has an exact two-target map; original gates remain single-target; no execution of the hosted matrix', 'v2_case_targets':NEURAL_RUNTIME_CASE_TARGETS, 'per_test_seconds':60, 'retry_count':0, 'capture_overhead_charged_to_original_test_deadline':True},
            'live_parent_correspondence':plan['live_parent_correspondence'],
            'cache_scope':'reused dedicated target including H1/H2/H3 caches; no separate prebuild; every H4 test requires its current fd-exec image; no prior-run result or H3 missing parent relationship is credited to H4',
            'original_job_budget_seconds':5400, 'workflow':plan['workflow_path'], 'workflow_sha256':plan['workflow_sha256']}
        save('native-environment.json', environment)
        assert 'host: x86_64-unknown-linux-gnu' in environment['rustc']
        publish('collector-controls')
        with (EVIDENCE / 'collector-controls.log').open('xb') as log:
            controls = subprocess.run([sys.executable,str(HERE/'test_executed_binary_capture.py')], cwd=SOURCE, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=20)
        save('collector-controls.json', {'exit_code':controls.returncode, 'sha256':digest(EVIDENCE/'collector-controls.log'), 'collector_sha256':COLLECTOR_SHA, 'scope':'three synthetic collector controls; no Rust product credit'})
        assert controls.returncode == 0, 'collector controls failed before Cargo'
        publish('fd-runner-controls')
        with (EVIDENCE / 'fd-runner-controls.log').open('xb') as log:
            controls = subprocess.run([sys.executable,str(HERE/'test_nextest_fd_runner.py')], cwd=SOURCE, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=20)
        save('fd-runner-controls.json', {'exit_code':controls.returncode, 'sha256':digest(EVIDENCE/'fd-runner-controls.log'), 'runner_sha256':FD_RUNNER_SHA, 'scope':'three synthetic deterministic fd-exec controls; no Rust product credit'})
        assert controls.returncode == 0, 'fd-exec runner controls failed before Cargo'
        publish('fd-target-controls')
        with (EVIDENCE / 'fd-target-controls.log').open('xb') as log:
            controls = subprocess.run([sys.executable,str(HERE/'test_fd_gate_targets.py')], cwd=SOURCE, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=20)
        save('fd-target-controls.json', {'exit_code':controls.returncode, 'sha256':digest(EVIDENCE/'fd-target-controls.log'), 'runner_sha256':FD_RUNNER_SHA, 'scope':'four synthetic exact-target and record-bijection controls; no product/native execution credit'})
        assert controls.returncode == 0, 'exact-target controls failed before Cargo'
        publish('live-parent-correspondence-controls')
        with (EVIDENCE / 'live-parent-correspondence-controls.log').open('xb') as log:
            controls = subprocess.run([sys.executable,str(HERE/'test_live_fd_correspondence.py')], cwd=SOURCE, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=20)
        save('live-parent-correspondence-controls.json', {'exit_code':controls.returncode, 'sha256':digest(EVIDENCE/'live-parent-correspondence-controls.log'), 'verifier_sha256':digest(HERE/'live_fd_correspondence.py'), 'scope':'three synthetic helper allowlist and identity rejection controls; no Rust case or old-H3 parent attribution'})
        assert controls.returncode == 0, 'live-parent correspondence controls failed before Cargo'
        dependencies = plan['steps'][0]
        assert dependencies['name'] == 'dependencies'
        gate('dependencies', dependencies['command'], timeout_seconds=dependencies['timeout_seconds'], offline=False)
        for name, pattern, minimum in [('execution-source-controls','test_hepta_smollm_execution_source_v*.py',135),('diverse-source-controls','test_hepta_neural_*diverse_v3.py',32)]:
            gate(name, ['python3','-m','unittest','discover','-s','scripts','-p',pattern,'-v'], minimum, None)
        for step in plan['steps'][1:]:
            if step['name'] == 'fix':
                continue
            gate(step['name'], step['command'], step['minimum'], step['timeout_seconds'], crate=step['crate'], names=set(step['expected_names']), case_targets=step.get('expected_case_targets'))
        with (EVIDENCE / 'selected-tests-guard.log').open('xb') as log:
            subprocess.run([sys.executable,str(HERE/'h4-selected-tests-guard.py'),str(EVIDENCE)], cwd=SOURCE, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=20, check=True)
        flags = ['--no-capture','--retries','0','--test-threads=1']
        compat = set(json.loads((HERE/'h4-extra-controls.json').read_text())['original_six_effect_controls'])
        gate('original-six-effect-controls',['just','test','--locked','-p','codex-hepta-agentd','--lib','-E',' | '.join('test(='+name+')' for name in sorted(compat)),*flags],6,600,crate='codex_hepta_agentd',names=compat)
        gate('provider-effect-existing-and-pq',['just','test','--locked','-p','codex-model-provider','--lib','-E','test(provider_effect)',*flags],10,600,crate='codex_model_provider',predicate={'kind':'prefix','value':'provider_effect::'})
        gate('final-use-profile-controls',['just','test','--locked','-p','codex-hepta-contracts','--lib','-E','test(final_use)',*flags],1,600,crate='codex_hepta_contracts',predicate={'kind':'contains','value':'final_use'})
        extra = json.loads((HERE/'h4-extra-controls.json').read_text())['full_evidence_library']
        gate('full-evidence-library',extra['command'],extra['minimum'],extra['timeout_seconds'],crate='codex_hepta_evidence',names=set(extra['expected_names']))
        fix = next(step for step in plan['steps'] if step['name']=='fix')
        gate('fix',fix['command'],0,fix['timeout_seconds'])
        gate('format',['just','fmt','--base',BASE],0,300)
        publish('completed-gates',status='passed-one-source-desktop-gates-only',finished_unix=time.time())
    finally:
        after = raw_guard('full-source-after')
        runtime_after = observed_runtime_inputs('after')
        save('runtime-inputs-delta.json', {'before':'runtime-inputs-before.json', 'after':'runtime-inputs-after.json', 'new_ignored_paths':sorted(set(runtime_after['ignored_paths'])-set(runtime_before['ignored_paths'])), 'removed_ignored_paths':sorted(set(runtime_before['ignored_paths'])-set(runtime_after['ignored_paths'])), 'external_configuration_unchanged':runtime_after['external_configuration_sha256']==runtime_before['external_configuration_sha256'], 'scope':'scoped observations, not an import trace or complete dynamic runtime closure'})
        after_configs = {str(p):digest(p) for p in configs}
        save('configuration-after.json', {'before':STATE['configuration_before'],'after':after_configs,'unchanged':after_configs==STATE['configuration_before']})
        STATE['source_after'] = after
        STATE['configuration_unchanged'] = after_configs == STATE['configuration_before']
        publish('final-source-recorded')
        assert exact_source(after) and after == before, 'full tracked source changed during execution'
        assert STATE['configuration_unchanged'], 'shared or worktree configuration changed'
        assert runtime_after['external_configuration_sha256'] == runtime_before['external_configuration_sha256'], 'external runner/coordinator configuration changed'
        assert time.monotonic()-START < 5400, 'actual coordinator including final guards exceeded the original 90-minute outer limit'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--tree',required=True)
    parser.add_argument('--evidence-name',required=True)
    ARGS = parser.parse_args()
    EVIDENCE = ROOT / 'evidence' / ARGS.evidence_name
    try:
        main()
    except BaseException as error:
        if EVIDENCE.exists():
            publish('failed',status='failed',error=repr(error),finished_unix=time.time())
        raise
