"""One exact full-source admission, clean maintenance, actual list and eleven cases.

No ordinary/Root qualification. Reuse the exact owned target, or create its
absent path under the existing owned parent. All
failing logs and source postimages remain in new, create-only evidence paths.
"""
import ast
import base64
import datetime
import gzip
import hashlib
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import traceback
import urllib.parse
import xml.etree.ElementTree as ET

CONFIG = json.loads('{"admission_frozen":true,"maintenance_mode":"consume-external-clean-terminal","parent":"e403c45570ad313851ca71392625e5572882405f","prior_maintenance":{"expected_exit_code":0,"result":{"bytes":2870,"path":"/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/result.json","sha256":"df3c3c2346180d1cd584a4e579337720b384cecd899fa802131281154122c140"},"source":"a4a1b5eb6cb45fc1182564e6b81026a2a2acf609","tree":"e09e7fb338e5f9a37fccfd4f05a8d5c222d7c0da"},"qa_fast_forward":{"base":"374aa919931e8ee5446b4ccdc49e651b7848cc5d","base_tree":"981c4675a6579dfd9748046d3d01a2268f11c36f","files":[{"after":{"blob":"0b645be03768d2c8dcd15e9b94bf75e64fa6c5ea","bytes":13482,"sha256":"973c2287d6c8a447c65f4b87a4e0921defb9338a9d62680daa693407e6f46266"},"base":{"blob":"4da0873c757803beb46256d84e27e63b12991347","bytes":12997,"sha256":"5a3a115cd814464248a0b00229d79c5bf65b85f8812fae3689a5134863ffd071"},"case_count":8,"component":"B","path":"qa/b4-no-bypass/test_original_evaluation_panel_source_closure.py"},{"after":{"blob":"efbf08c9dc423254d933669e414301689ab8e352","bytes":12700,"sha256":"4afd8ee94af50d88f0e1e0d02cee80e3aa430bf1b5309602016aa545a167b8d1"},"base":{"blob":"a65614c5bb04d3d22b007213a94c20f318bf73b4","bytes":12634,"sha256":"e61cb68bafc1b9e2d80f60e8c1800dd4e4dec5d10e5b9ee367da98ad31b45cf4"},"case_count":6,"component":"B","path":"qa/b4-no-bypass/test_original_qualification_owner_source_closure.py"},{"after":{"blob":"927b7de74c4a84faf3037d40a86c383cf0ac223e","bytes":13541,"sha256":"0ed97611cefb69835f6fb6e573a751a169f810fa9c2c9873cf7cabb7d21df96e"},"base":{"blob":"ba65f8cebf39277681b28812ea0a34c42c37ea8e","bytes":12582,"sha256":"1b9f8b9c9bfdc004521f7007efaf228a7fcb8819059679dd040ac060786af578"},"case_count":15,"component":"C","path":"qa/b4-no-bypass/test_original_learning_owner_source_closure.py"},{"after":{"blob":"4203887e7a6b43f6cf8fbbfbe27f46e689e15c46","bytes":11022,"sha256":"f09e819bbd565dd83dbcaa725df6e5dc9017d3d60ffb7fca19ae57de907ce218"},"base":{"blob":"6fc51eed804792d4f009697f76f2d3c20a5c9827","bytes":10167,"sha256":"d06d8d50b02fdb1ae5f5913348e6d9337c0e02515f7ad1e64dbdb1bed03e8039"},"case_count":6,"component":"C","path":"qa/b4-no-bypass/test_original_model_selection_source_closure.py"}]},"records_suffix":"diagnostic-eleven-v1","repo":"/home/qian-qi/hepta-learn-source-20261112-037c-a4a1b5eb","request_key":"learn-037c-native-a4a1b5eb6cb4-diagnostic-eleven-v1","required_names":["runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures","runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::q24_next_use_command_readback_refuses_actual_publication_withdrawal","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_hot_readback_preserves_sources","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_training_proof_rejects_new_source_reentry_and_incomplete_slots","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_same_call_training_keeps_four_execute_and_three_readback_frames","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_last_actual_training_failure_never_returns_or_resigns_b","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_last_training_slot_keeps_the_actual_cohort_tail","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_cancel_keeps_the_held_lane_and_consumed_channel","runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::current_slots::published_current_last_original_slot_rejects_actual_withdrawal","runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::current_slots::published_current_call_rejects_other_original_incomplete_and_reuse"],"root_parent_count":33,"source":"a4a1b5eb6cb45fc1182564e6b81026a2a2acf609","source_admission_mode":"prepared-newcheckout","source_gate":{"execution":{"bytes":1483,"path":"/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1/source-closure.json","sha256":"6d7ca8638ca69aeaf89833681cd672637a09c961d234d9d354b983a903a26c50"},"expected_cases":504,"repo":"/home/qian-qi/hepta-learn-source-20261112-037c-a4a1b5eb","result":{"bytes":1156,"path":"/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1/result.json","sha256":"fd283e2847c6dde06ffb6f0a97bfeb2ab250e92f7ff1eb89d8b4dd9471cf3294"}},"tree":"e09e7fb338e5f9a37fccfd4f05a8d5c222d7c0da","workflow_blob":"0f4dffca6dcf24c197b9211e56af1cf80eb640da"}')
BUNDLED_DRIVERS = json.loads('{"diagnostic":{"blob":"4135a0a186f1f747cf1108f4f479d17ba4c8c19e","bytes":17354,"gzip_base64":"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","sha256":"a8700807334b313f660f00796f4bf3b0d19f9a7d63c67c0f2ff3bba6e58bef51"},"list_run_gate":{"blob":"17f6bb22fe1ee0f8835e428af01bd2b45e29f5ee","bytes":17935,"gzip_base64":"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","sha256":"7e10a0c2e126d11ccfbb1658aefebf7ffa7df5cec115e723eb982ca8d0cc2e89"},"maintenance":{"blob":"436049145abae26d751988fbfd74a6d5e780b06c","bytes":12668,"gzip_base64":"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","sha256":"6003482e759a36b7d7ed82814071b894900b450653241679762898fddf9d98ca"}}')
REPO = Path(CONFIG['repo'])
CALLER = Path('/home/qian-qi/hepta-learn-caller-20261112-037c-726af8f4')
ROOT = Path('/home/qian-qi/hepta-learn-037c-evidence')
TARGET = Path('/data/hepta-learn-037c-20261112/target-cold-4ab-v1')
BASE = CONFIG['prior_maintenance']['source']
BASE_TREE = CONFIG['prior_maintenance']['tree']
BASE_INVENTORY = None  # Historical 14995 inventory never applies to this complete source.
LOCK = '98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69'
source, tree, request_key = CONFIG['source'], CONFIG['tree'], CONFIG['request_key']
RECORDS = ROOT / ('native-prepare-' + source[:12] + '-' + CONFIG['records_suffix'])
MAINTENANCE = (Path(CONFIG['prior_maintenance']['result']['path']).parent if CONFIG['maintenance_mode'] == 'consume-external-clean-terminal' else ROOT / ('maintenance-' + source[:12] + '-' + CONFIG['records_suffix']))
NATIVE = ROOT / ('native-' + source[:12] + '-' + CONFIG['records_suffix'])
if CONFIG.get('admission_frozen') is not True:
    raise SystemExit('NOT_SUBMITTED preview: actual passing source and natural terminal bindings are required')
RECORDS.mkdir(mode=0o700, exist_ok=False)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(name, value):
    with (RECORDS / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def git(*args, cwd=REPO):
    return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=cwd)


def identity(cwd=REPO):
    sparse = Path(git('rev-parse', '--git-path', 'info/sparse-checkout', cwd=cwd).decode().strip())
    if not sparse.is_absolute():
        sparse = cwd / sparse
    return {'commit': git('rev-parse', 'HEAD', cwd=cwd).decode().strip(),
            'tree': git('rev-parse', 'HEAD^{tree}', cwd=cwd).decode().strip(),
            'status': git('status', '--porcelain=v1', '--untracked-files=all', cwd=cwd).decode(),
            'diff_sha256': hashlib.sha256(git('diff', '--binary', 'HEAD', '--', cwd=cwd)).hexdigest(),
            'cargo_lock_sha256': sha(cwd / 'codex-rs/Cargo.lock'),
            'sparse_path': str(sparse.resolve()), 'sparse_sha256': sha(sparse) if sparse.is_file() else None}


def inventory():
    rows = []
    names = git('ls-files', '-z') + git('ls-files', '--others', '--exclude-standard', '-z')
    for raw in sorted(set(names.split(b'\0')) - {b''}):
        rel = os.fsdecode(raw)
        path = REPO / rel
        if not path.exists() and not path.is_symlink():
            rows.append({'path': rel, 'missing': True})
            continue
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        mode = '120000' if path.is_symlink() else ('100755' if path.stat().st_mode & 0o111 else '100644')
        rows.append({'path': rel, 'mode': mode, **meta(data)})
    encoded = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    return rows, encoded


def snapshot(label):
    rows, encoded = inventory()
    with gzip.open(RECORDS / (label + '.files.json.gz'), 'xb') as stream:
        stream.write(encoded)
    observed = {**identity(), 'files': len(rows), 'inventory_sha256': hashlib.sha256(encoded).hexdigest()}
    save(label + '.json', observed)
    return observed, rows, encoded


def retain_changes(label):
    patch = git('diff', '--binary', 'HEAD', '--')
    (RECORDS / (label + '.patch')).write_bytes(patch)
    names = git('diff', '--name-only', '--no-renames', '-z', 'HEAD', '--')
    names += git('ls-files', '--others', '--exclude-standard', '-z')
    rows = []
    for raw in sorted(set(names.split(b'\0')) - {b''}):
        rel = os.fsdecode(raw)
        path = REPO / rel
        if not path.exists() or path.is_symlink():
            rows.append({'path': rel, 'missing': not path.exists(), 'symlink': path.is_symlink()})
            continue
        data = path.read_bytes()
        destination = RECORDS / (label + '-postimages') / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(data)
        rows.append({'path': rel, **meta(data)})
    value = {'patch': meta(patch), 'files': rows}
    save(label + '-postimages.json', value)
    return value


def execute(label, command, cwd, env):
    started = now()
    path = RECORDS / (label + '.raw.log')
    digest, size = hashlib.sha256(), 0
    with path.open('xb', buffering=0) as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        save(label + '-launch.json', {'command': command, 'cwd': str(cwd), 'pid': process.pid,
             'started_at': started, 'controller_timeout_or_kill': False})
        print(json.dumps({'phase': label, 'pid': process.pid, 'started_at': started}), flush=True)
        while True:
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            stream.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        returncode = process.wait()
        process.stdout.close()
        os.fsync(stream.fileno())
    observed = {'command': command, 'cwd': str(cwd), 'started_at': started, 'finished_at': now(),
                'returncode': returncode, 'actual_process_exit_observed': True, 'controller_kill': False,
                'log_file': path.name, 'log_bytes': size, 'log_sha256': digest.hexdigest()}
    save(label + '.json', observed)
    return observed


def pinned_original(spec, label):
    path = Path(spec['path'])
    assert path.is_absolute() and path.is_relative_to(ROOT), label
    data = path.read_bytes()
    assert len(data) == spec['bytes'] and hashlib.sha256(data).hexdigest() == spec['sha256'], label
    with (RECORDS / (label + '.original.json')).open('xb') as stream:
        stream.write(data)
    return path, json.loads(data)


def source_gate_admission():
    path, gate = pinned_original(CONFIG['source_gate']['result'], 'source-gate-result')
    execution_path, execution = pinned_original(CONFIG['source_gate']['execution'], 'source-gate-execution')
    assert gate['source'] == source and gate['tree'] == tree
    assert gate['status'] == 'passed' and gate['exit_code'] == 0
    assert gate['before'] == gate['after'] and gate['after']['dirty'] == ''
    assert gate['after']['commit'] == source and gate['after']['tree'] == tree
    assert gate['execution']['returncode'] == 0 and gate['execution']['actual_process_exit_observed']
    assert gate['execution']['outer_controller_kill'] is False
    assert execution['source_sha'] == execution['tested_sha'] == source
    assert execution['status'] == 'passed' and execution['exit_code'] == execution['command_exit_code'] == execution['returncode'] == 0
    assert execution['before'] == execution['after'] and execution['after']['dirty'] is False
    assert execution['after']['commit'] == source and execution['after']['tree'] == tree
    assert execution['timed_out'] is False and execution['output_limit_exceeded'] is False
    assert execution['minimum_tests'] == 1 and execution['observed_failed_tests'] == 0
    assert execution['observed_passed_tests'] == CONFIG['source_gate']['expected_cases']
    assert execution['command'] == ['python3', '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass', '-p', '*source_closure.py', '-v']
    assert execution['lane'] == 'source-head'
    assert Path(execution['working_directory']) == Path(CONFIG['source_gate']['repo'])
    log = execution_path.parent / execution['log_file']
    assert log.is_relative_to(execution_path.parent)
    assert log.stat().st_size == execution['log_bytes'] and sha(log) == execution['log_sha256']
    compressed = path.parent / 'source-after.files.json.gz'
    data = gzip.decompress(compressed.read_bytes())
    assert hashlib.sha256(data).hexdigest() == gate['after']['inventory_sha256']
    rows = json.loads(data)
    assert len(rows) == gate['after']['file_count'] and not any(row.get('missing') for row in rows)
    assert rows == sorted(rows, key=lambda row: os.fsencode(row['path']))
    assert len({row['path'] for row in rows}) == len(rows)
    assert data == json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    assert all(set(row) == {'path', 'mode', 'bytes', 'sha256'} for row in rows)
    save('source-gate-admission.json', {'result': CONFIG['source_gate']['result'],
         'execution': CONFIG['source_gate']['execution'], 'observed': gate['after'],
         'source_closure_cases': execution['observed_passed_tests'],
         'source_closure_log_sha256': execution['log_sha256'],
         'source_inventory_schema': 'path/mode/bytes/sha256; no Git blob',
         'native_inventory_schema': 'path/mode/bytes/sha256/blob; compared explicitly below'})
    return gate, data


def prior_maintenance_admission():
    path, previous = pinned_original(CONFIG['prior_maintenance']['result'], 'prior-maintenance-result')
    assert previous['source_sha'] == CONFIG['prior_maintenance']['source']
    assert previous['source_tree'] == CONFIG['prior_maintenance']['tree']
    # This earlier natural terminal releases the shared target. It grants no
    # native admission: the new source still executes its own clean fmt/fix below.
    expected_exit = CONFIG['prior_maintenance']['expected_exit_code']
    assert expected_exit in (0, 101)
    assert previous['status'] == ('passed' if expected_exit == 0 else 'failed')
    assert previous['exit_code'] == previous['execution']['returncode'] == expected_exit
    assert previous['execution']['actual_process_exit_observed'] and previous['execution']['controller_kill'] is False
    assert previous['before'] == previous['after'] and previous['after']['dirty'] == ''
    assert previous['postimages']['file_count'] == previous['postimages']['patch_bytes'] == 0
    assert json.loads((path.parent / 'postimages.json').read_text())['files'] == []
    assert (path.parent / 'maintenance.patch').read_bytes() == b''
    log = path.parent / previous['execution']['log_file']
    assert log.is_relative_to(path.parent)
    assert log.stat().st_size == previous['execution']['log_bytes'] and sha(log) == previous['execution']['log_sha256']
    data = gzip.decompress((path.parent / 'source-after.files.json.gz').read_bytes())
    assert hashlib.sha256(data).hexdigest() == previous['after']['inventory_sha256']
    assert len(json.loads(data)) == previous['after']['file_count']
    return previous, data


def verify_full_index_and_bytes(rows, commit, label='source'):
    assert not any(row.get('missing') for row in rows)
    index = {}
    for raw in git('ls-files', '--stage', '-z').split(b'\0'):
        if not raw:
            continue
        fields, name = raw.split(b'\t', 1)
        mode, blob, stage = fields.decode().split()
        assert stage == '0' and os.fsdecode(name) not in index
        index[os.fsdecode(name)] = (mode, blob)
    objects = {}
    for raw in git('ls-tree', '-r', '-z', '--full-tree', commit).split(b'\0'):
        if not raw:
            continue
        fields, name = raw.split(b'\t', 1)
        mode, kind, blob = fields.decode().split()
        assert kind == 'blob' and os.fsdecode(name) not in objects
        objects[os.fsdecode(name)] = (mode, blob)
    actual = {row['path']: (row['mode'], row['blob']) for row in rows}
    assert len(actual) == len(rows) and actual == index == objects, 'full source/index/tree disagreement'
    save(label + '-full-tree-index-admission.json', {'commit': commit, 'file_count': len(rows),
         'every_actual_mode_and_blob_equals_full_index_and_tree': True,
         'missing_files': 0, 'untracked_inputs': 0, 'sparse_inputs_accepted': False})


def admit_exact_checkout(before, rows, encoded, previous, previous_bytes, gate, gate_bytes, origin):
    mode = CONFIG['source_admission_mode']
    assert mode in ('prepared-newcheckout', 'reuse-qa-only-fast-forward')
    if mode == 'prepared-newcheckout':
        assert before['commit'] == source and before['tree'] == tree and before['status'] == ''
        assert git('rev-parse', source + '^{tree}').decode().strip() == tree
        assert git('rev-list', '--parents', '-n', '1', source).decode().strip().split() == [source, CONFIG['parent']]
        save('checkout-admission.json', {'mode': mode, 'source_writes': False,
             'fetch': False, 'checkout': False, 'new_full_worktree': str(REPO)})
    else:
        # This branch is only the reviewed four-QA direct child, never a product fix.
        base = CONFIG['qa_fast_forward']['base']
        base_tree = CONFIG['qa_fast_forward']['base_tree']
        files = CONFIG['qa_fast_forward']['files']
        assert len(files) == 4 and len({row['path'] for row in files}) == 4
        assert all(row['path'].startswith('qa/b4-no-bypass/') and row['path'].endswith('_source_closure.py') for row in files)
        assert before['commit'] == base and before['tree'] == base_tree and before['status'] == ''
        assert CONFIG['parent'] == base and previous['source_sha'] == base and previous['source_tree'] == base_tree
        assert previous['exit_code'] == 0, 'QA-only fast-forward requires an actually successful prior compiler'
        assert before['inventory_sha256'] == previous['after']['inventory_sha256'] and encoded == previous_bytes
        verify_full_index_and_bytes(rows, base, label='prior-source')
        by_path = {row['path']: row for row in rows}
        for item in files:
            assert by_path[item['path']] == {'path': item['path'], 'mode': '100644', **item['base']}, item['path']
        fetched = execute('fetch-exact-qa-child', ['git', 'fetch', 'origin', source], REPO, os.environ.copy())
        assert fetched['returncode'] == 0
        assert git('rev-parse', source + '^{tree}').decode().strip() == tree
        assert git('rev-list', '--parents', '-n', '1', source).decode().strip().split() == [source, base]
        changed = git('diff', '--name-status', '--no-renames', '-z', base, source).split(b'\0')
        assert changed[-1] == b'' and len(changed[:-1]) == 8
        pairs = list(zip(changed[:-1:2], changed[1:-1:2]))
        assert sorted((status.decode(), os.fsdecode(path)) for status, path in pairs) == sorted(('M', item['path']) for item in files)
        assert git('rev-parse', base + ':codex-rs') == git('rev-parse', source + ':codex-rs')
        assert git('rev-parse', base + ':CALLERS.toml') == git('rev-parse', source + ':CALLERS.toml')
        for item in files:
            assert meta(git('show', source + ':' + item['path'])) == item['after'], item['path']
            by_path[item['path']] = {'path': item['path'], 'mode': '100644', **item['after']}
        expected = json.dumps([by_path[row['path']] for row in rows], sort_keys=True, separators=(',', ':')).encode()
        save('qa-fast-forward-admission.json', {'base': before, 'child': source, 'tree': tree,
             'files': files, 'full_expected_native_inventory_sha256': hashlib.sha256(expected).hexdigest(),
             'codex_rs_tree_unchanged': True, 'CALLERS_unchanged': True,
             'reset_clean_restore_used': False, 'prior_actual_clean_maintenance': CONFIG['prior_maintenance']['result']})
        checked = execute('checkout-exact-qa-child', ['git', 'checkout', '--detach', source], REPO, os.environ.copy())
        assert checked['returncode'] == 0
    observed, current_rows, current_bytes = snapshot('exact-source')
    assert observed['commit'] == source and observed['tree'] == tree and observed['status'] == ''
    assert observed['cargo_lock_sha256'] == LOCK
    assert observed['sparse_path'] == before['sparse_path'] and observed['sparse_sha256'] == before['sparse_sha256']
    assert git('remote', 'get-url', '--all', 'origin').decode().splitlines() == origin
    if mode == 'reuse-qa-only-fast-forward':
        assert current_bytes == expected, 'checked-out QA child differs from the exact four reviewed postimages'
    without_blob = [{key: value for key, value in row.items() if key != 'blob'} for row in current_rows]
    actual_gate_bytes = json.dumps(without_blob, sort_keys=True, separators=(',', ':')).encode()
    assert actual_gate_bytes == gate_bytes
    assert len(current_rows) == gate['after']['file_count']
    assert hashlib.sha256(actual_gate_bytes).hexdigest() == gate['after']['inventory_sha256']
    verify_full_index_and_bytes(current_rows, source)
    return observed, current_rows, current_bytes


result = {'source': source, 'tree': tree, 'base': BASE, 'request_key': request_key,
          'diagnostic_only': True, 'ordinary_qualification': 0, 'root_qualification': 0,
          'formal_focused_qualification': False, 'started_at': now(), 'status': 'preflight'}
save('intent.json', {'config': CONFIG, 'drivers': {name: {k: v for k, v in item.items() if k != 'gzip_base64'}
     for name, item in BUNDLED_DRIVERS.items()}, 'uid': os.getuid(), 'gid': os.getgid(),
     'rendered_wrapper_sha256_from_frozen_launcher': sys.argv[1] if len(sys.argv) == 2 else None})
caller_before = None
source_ready = None
source_bytes = None
exit_code = 1
try:
    assert os.getuid() != 0
    assert len(source) == len(tree) == 40 and all(ch in '0123456789abcdef' for ch in source + tree)
    assert len(CONFIG['required_names']) == len(set(CONFIG['required_names'])) == 11
    assert not NATIVE.exists()
    assert CONFIG['maintenance_mode'] in ('in-pipeline', 'consume-external-clean-terminal')
    assert (MAINTENANCE.is_dir() if CONFIG['maintenance_mode'] == 'consume-external-clean-terminal' else not MAINTENANCE.exists())
    gate, gate_bytes = source_gate_admission()
    previous, previous_bytes = prior_maintenance_admission()
    before, before_rows, before_bytes = snapshot('prior-source')
    assert before['status'] == '' and not any(row.get('missing') for row in before_rows)
    assert before['cargo_lock_sha256'] == LOCK and before['diff_sha256'] == hashlib.sha256(b'').hexdigest()
    caller_before = identity(CALLER)
    assert caller_before['status'] == '' and caller_before['commit'] == '726af8f4a345a2ffb148b971f3fa16c71436862d'
    assert before['sparse_path'] != caller_before['sparse_path']
    save('caller-before.json', caller_before)
    environment_path = ROOT / 'maintenance-4ab34bbd3ca8-v3/native-environment.json'
    assert sha(environment_path) == '682e2ad2b1dceeb0b643b8c10df1101bb5e27f1e1608d633d190134dbfc390cf'
    original_environment = json.loads(environment_path.read_text())
    env = dict(os.environ)
    for key, value in original_environment['environment'].items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env.update(SOURCE_SHA=source, TESTED_SHA=source, HEPTA_CI_LANE='source-head',
               CODEX_REPO_ROOT=str(REPO), PYTHONPATH=str(REPO / 'scripts'))
    assert env['RUSTUP_TOOLCHAIN'] == '1.96.0' and env['CARGO_BUILD_JOBS'] == '2'
    assert env['CARGO_PROFILE_DEV_DEBUG'] == env['CARGO_PROFILE_TEST_DEBUG'] == '0'
    assert env['CARGO_NET_OFFLINE'] == 'true' and env['CARGO_TARGET_DIR'] == str(TARGET)
    inputs = []
    for expected in original_environment['native_inputs']:
        path = Path(expected['path'])
        assert path.stat().st_size == expected['bytes'] and sha(path) == expected['sha256'], str(path)
        inputs.append(expected)
    helper_path = ROOT / 'native-cc22a69972d0-focused-v1/helpers/manifest.json'
    assert sha(helper_path) == 'ca437cea08311d1ba5fdc237ff3e9c89261b78783c8a0f6eb06c98d02673072c'
    helper = json.loads(helper_path.read_text())
    assert helper['complete'] and helper['exit_code'] == 0
    retained_helpers = []
    for name, expected in helper['artifacts'].items():
        path = Path(expected['executable'])
        assert path.stat().st_size == expected['bytes'] and sha(path) == expected['sha256'], name
        retained_helpers.append({'name': name, 'path': str(path), 'bytes': expected['bytes'], 'sha256': expected['sha256']})
    # Observe before deciding: the prior conjunction does not prove why admission failed.
    try:
        prior_target = TARGET.lstat()
    except FileNotFoundError:
        prior_target = None
    target_before = {'path': str(TARGET), 'exists': prior_target is not None}
    if prior_target is not None:
        target_before.update(device=prior_target.st_dev, inode=prior_target.st_ino,
                             uid=prior_target.st_uid, mode=prior_target.st_mode,
                             symlink=stat.S_ISLNK(prior_target.st_mode),
                             directory=stat.S_ISDIR(prior_target.st_mode))
    save('target-before.json', target_before)
    for ancestor in reversed(TARGET.parents):
        observed_parent = ancestor.lstat()
        assert stat.S_ISDIR(observed_parent.st_mode) and not stat.S_ISLNK(observed_parent.st_mode), str(ancestor)
    parent_stat = TARGET.parent.lstat()
    assert parent_stat.st_uid == os.getuid(), 'target parent is not the original operator-owned task parent'
    if prior_target is not None:
        assert stat.S_ISDIR(prior_target.st_mode) and not stat.S_ISLNK(prior_target.st_mode)
        assert prior_target.st_uid == os.getuid(), 'existing target owner differs; do not adopt or overwrite'
    concurrent = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            comm = (proc / 'comm').read_text().strip()
            if comm not in {'cargo', 'rustc', 'rustdoc', 'rustfmt', 'cargo-clippy', 'clippy-driver', 'just', 'cargo-nextest', 'sccache'} and not comm.startswith('codex_hepta'):
                continue
            row = {'pid': int(proc.name), 'comm': comm, 'uid': proc.stat().st_uid}
            for name in ('exe', 'cwd'):
                try:
                    row[name] = os.readlink(proc / name)
                except OSError as error:
                    row[name + '_error'] = type(error).__name__
            concurrent.append(row)
        except (FileNotFoundError, PermissionError):
            continue
    own_roots = (str(REPO), str(TARGET), '/home/qian-qi/hepta-learn-common-20261112-037c')
    own_source_prefix = '/home/qian-qi/hepta-learn-source-20261112-037c-'
    assert not any(any(row.get('cwd', '') == root or row.get('cwd', '').startswith(root + '/') for root in own_roots)
                   or row.get('cwd', '').startswith(own_source_prefix)
                   or row.get('exe', '').startswith(str(TARGET) + '/') for row in concurrent), 'active tooling in own source or target'
    target_created = False
    if prior_target is None:
        # Exactly one missing task-owned directory; never clean, replace, chmod or chown an existing target.
        current_parent = TARGET.parent.lstat()
        assert current_parent.st_dev == parent_stat.st_dev and current_parent.st_ino == parent_stat.st_ino
        assert current_parent.st_uid == os.getuid() and stat.S_ISDIR(current_parent.st_mode)
        TARGET.mkdir(mode=0o700, exist_ok=False)
        target_created = True
    target_stat = TARGET.lstat()
    assert stat.S_ISDIR(target_stat.st_mode) and not stat.S_ISLNK(target_stat.st_mode)
    assert target_stat.st_uid == os.getuid()
    if prior_target is not None:
        assert target_stat.st_dev == prior_target.st_dev and target_stat.st_ino == prior_target.st_ino
    target_nonempty = any(TARGET.iterdir())
    if target_created:
        assert not target_nonempty, 'new cold target must actually be empty'
    save('target-admission.json', {'before': target_before, 'created': target_created,
         'empty_on_admission': not target_nonempty, 'device': target_stat.st_dev,
         'inode': target_stat.st_ino, 'uid': target_stat.st_uid,
         'existing_data_removed': False, 'existing_metadata_modified': False})
    save('environment-admission.json', {'previous_environment_sha256': sha(environment_path),
         'environment': {key: env.get(key) for key in original_environment['environment']},
         'native_inputs': inputs, 'retained_helpers': retained_helpers,
         'target': {'path': str(TARGET), 'device': target_stat.st_dev, 'inode': target_stat.st_ino,
                    'uid': target_stat.st_uid, 'reused_existing_cache': not target_created and target_nonempty,
                     'created': target_created, 'empty_on_admission': not target_nonempty},
         'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
         'concurrent_rust_processes': concurrent, 'other_processes_touched': False,
         'available_disk_bytes': os.statvfs(TARGET).f_bavail * os.statvfs(TARGET).f_frsize,
         'memory': [line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:', 'MemAvailable:'))]})
    rustfmt = subprocess.check_output(['/home/qian-qi/.cargo/bin/rustup', 'which', '--toolchain', '1.96.0', 'rustfmt'], env=env).decode().strip()
    assert sha(Path(rustfmt)) == '342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c'
    tools = {}
    for name in ('rustc', 'cargo', 'rustfmt'):
        path = Path(subprocess.check_output(['/home/qian-qi/.cargo/bin/rustup', 'which', '--toolchain', '1.96.0', name], env=env).decode().strip())
        tools[name] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
    just = Path(shutil.which('just', path=env['PATH']))
    tools['just'] = {'path': str(just), 'bytes': just.stat().st_size, 'sha256': sha(just)}
    save('tool-inputs.json', tools)
    origin = git('remote', 'get-url', '--all', 'origin').decode().splitlines()
    assert len(origin) == 1
    origin_bytes = origin[0].encode()
    if origin[0].startswith('git@github.com:'):
        repository = origin[0].split(':', 1)[1]
    else:
        parsed = urllib.parse.urlsplit(origin[0])
        assert parsed.hostname == 'github.com' and parsed.scheme in ('https', 'ssh')
        repository = parsed.path.lstrip('/')
    assert repository.removesuffix('.git') == 'TrillionniumFoundation/hepta-private-ci'
    save('origin-admission.json', {'repository': 'TrillionniumFoundation/hepta-private-ci', 'origin_sha256': hashlib.sha256(origin_bytes).hexdigest(), 'configuration_changed': False})
    source_ready, new_rows, source_bytes = admit_exact_checkout(
        before, before_rows, before_bytes, previous, previous_bytes, gate, gate_bytes, origin)
    assert identity(CALLER) == caller_before
    for rel in ('docs/modules/MODULES.json', 'qualification/neuron-v13-generation/proposal_worker.py'):
        assert (REPO / rel).read_bytes() == git('show', source + ':' + rel), rel
    assert sha(REPO / 'AGENTS.md') == 'c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480'
    assert not (REPO / 'codex-rs/AGENTS.md').exists() and not list((REPO / 'codex-rs/hepta-agentd').rglob('AGENTS.md'))
    workflow = (REPO / '.github/workflows/hepta-daemon-learning-native.yml').read_bytes()
    assert meta(workflow)['blob'] == CONFIG['workflow_blob']
    marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
    original = textwrap.dedent(workflow.decode().split(marker, 1)[1].split('          PY\n', 1)[0])
    declarations = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(original).body
                    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('parents', 'packages')}
    assert len(declarations['parents']) == len(set(declarations['parents'])) == CONFIG['root_parent_count'] == 33
    nextest = (REPO / 'codex-rs/.config/nextest.toml').read_bytes()
    assert meta(nextest)['blob'] == '0904c42a41594d3ae4dc6f196e64f35f0b85bd2c'
    assert 'slow-timeout = { period = "30s", terminate-after = 2 }' in nextest.decode()
    result.update(status='source-ready', source_ready=source_ready)
    save('source-ready.json', result)
    print(json.dumps({'phase': 'exact-source-ready', 'identity': source_ready}), flush=True)
    if CONFIG['maintenance_mode'] == 'in-pipeline':
        fmt = execute('just-fmt', ['just', 'fmt'], REPO / 'codex-rs', env)
        fmt_after, _, fmt_bytes = snapshot('fmt-source-after')
        fmt_images = retain_changes('fmt')
        assert fmt['returncode'] == 0 and fmt_bytes == source_bytes and fmt_after == source_ready and not fmt_images['files'] and fmt_images['patch']['bytes'] == 0, 'format failed or changed source; retained originals'
    else:
        # Consume the original natural fmt/fix terminal; do not run either again.
        assert CONFIG['source_admission_mode'] == 'prepared-newcheckout'
        assert previous['source_sha'] == source and previous['source_tree'] == tree and previous['exit_code'] == 0
        assert previous['before'] == previous['after_format'] == previous['after']
        assert previous_bytes == source_bytes
        fmt = previous['format_execution']
        assert fmt['command'] == ['just', 'fmt'] and fmt['returncode'] == 0
        assert fmt['actual_process_exit_observed'] and fmt['controller_kill'] is False
        fmt_log = MAINTENANCE / fmt['log_file']
        assert fmt_log.is_relative_to(MAINTENANCE)
        assert fmt_log.stat().st_size == fmt['log_bytes'] and sha(fmt_log) == fmt['log_sha256']
        save('external-format-terminal.json', {'original': fmt, 'source_bytes_equal': True,
             'original_result': CONFIG['prior_maintenance']['result'], 'format_rerun': False})
    driver_paths = {}
    for name, item in BUNDLED_DRIVERS.items():
        data = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
        assert meta(data) == {key: item[key] for key in ('bytes', 'sha256', 'blob')}
        path = RECORDS / (name + '.py')
        with path.open('xb') as stream:
            stream.write(data)
        driver_paths[name] = path
    if CONFIG['maintenance_mode'] == 'in-pipeline':
        maintenance_command = ['/usr/bin/python3', str(driver_paths['maintenance']), '--mode', 'fix', '--source', source, '--tree', tree, '--records', str(MAINTENANCE), '--request-key', request_key]
        fixed = execute('maintenance-process', maintenance_command, REPO, env)
        maintained = json.loads((MAINTENANCE / 'result.json').read_text())
        save('maintenance-terminal.json', {'process': fixed, 'result_sha256': sha(MAINTENANCE / 'result.json'), 'result': maintained})
    else:
        maintained = previous
        fixed = maintained['execution']
        assert fixed['command'] == ['just', 'fix', '-p', 'codex-hepta-agentd', '--locked', '--offline']
        assert sha(MAINTENANCE / 'result.json') == CONFIG['prior_maintenance']['result']['sha256']
        save('maintenance-terminal.json', {'original_execution': fixed,
             'result_sha256': sha(MAINTENANCE / 'result.json'), 'result': maintained,
             'maintenance_rerun': False, 'source_bytes_equal': True})
    assert fixed['returncode'] == 0 and maintained['status'] == 'passed' and maintained['exit_code'] == 0
    assert maintained['source_sha'] == source and maintained['source_tree'] == tree
    assert maintained['execution']['returncode'] == 0 and maintained['execution']['actual_process_exit_observed'] and not maintained['execution']['controller_kill']
    assert maintained['before'] == maintained['after'] and maintained['after']['dirty'] == ''
    assert maintained['after']['inventory_sha256'] == source_ready['inventory_sha256'] and maintained['after']['cargo_lock_sha256'] == LOCK
    assert maintained['postimages']['file_count'] == 0 and maintained['postimages']['patch_bytes'] == 0
    assert json.loads((MAINTENANCE / 'postimages.json').read_text())['files'] == [] and (MAINTENANCE / 'maintenance.patch').read_bytes() == b''
    assert sha(MAINTENANCE / 'just-fix.raw.log') == maintained['execution']['log_sha256']
    assert gzip.decompress((MAINTENANCE / 'source-after.files.json.gz').read_bytes()) == source_bytes
    maintained_environment = json.loads((MAINTENANCE / 'native-environment.json').read_text())
    assert maintained_environment['environment'] == {key: env.get(key) for key in maintained_environment['environment']}
    assert maintained_environment['native_inputs'] == inputs
    native_preflight, _, native_preflight_bytes = snapshot('native-preflight')
    assert native_preflight == source_ready and native_preflight_bytes == source_bytes
    assert TARGET.stat().st_ino == target_stat.st_ino and TARGET.stat().st_dev == target_stat.st_dev
    for expected in inputs:
        assert sha(Path(expected['path'])) == expected['sha256']
    native_env = env.copy()
    native_env['RUST_MIN_STACK'] = '8388608'
    command = ['/usr/bin/python3', str(driver_paths['diagnostic']), '--repo', str(REPO), '--records', str(NATIVE), '--source', source, '--suite', 'diagnostic-eleven']
    save('native-admission.json', {'source': source_ready, 'maintenance_result_sha256': sha(MAINTENANCE / 'result.json'),
         'command': command, 'stack_bytes': 8388608, 'test_threads': 2, 'retries': 0,
         'nextest_per_case_seconds': 60, 'helper_outer_seconds': 3600, 'test_outer_seconds': 7200,
         'required_names': CONFIG['required_names'], 'diagnostic_only': True, 'ordinary_and_root': 'NOT_RUN'})
    tested = execute('native-process', command, REPO, native_env)
    driver_result_path = NATIVE / 'driver-result.json'
    if driver_result_path.is_file():
        driver_result = json.loads(driver_result_path.read_text())
        save('native-terminal.json', {'driver_result_sha256': sha(driver_result_path), 'driver_result': driver_result})
        expected_native_identity = {key: source_ready[key] for key in ('commit', 'tree', 'status', 'files', 'inventory_sha256')}
        assert driver_result['source_sha'] == source
        assert driver_result['source_before'] == driver_result['source_after'] == expected_native_identity
        if tested['returncode'] == 0:
            assert driver_result['status'] == 'passed' and driver_result['failures'] == []
    list_result_path = NATIVE / 'list-admission/result.json'
    list_coverage_path = NATIVE / 'list-admission/selected-name-coverage.json'
    list_admission = {'available': list_result_path.is_file() and list_coverage_path.is_file(), 'exact': False}
    if list_admission['available']:
        list_result = json.loads(list_result_path.read_text())
        list_coverage = json.loads(list_coverage_path.read_text())
        list_admission.update(result_sha256=sha(list_result_path), coverage_sha256=sha(list_coverage_path),
                              result=list_result, coverage=list_coverage)
        listed = [row['name'] for row in list_coverage['cases']]
        list_admission['exact'] = (len(listed) == len(set(listed)) == 11
                                   and sorted(listed) == sorted(CONFIG['required_names'])
                                   and list_coverage['exact_selected_names'] is True
                                   and list_result.get('native_test_child_started') is True
                                   and list_result.get('exit_code') == 0
                                   and list_result.get('status') == 'original-test-returned-zero'
                                   and list_result['list_execution']['returncode'] == 0
                                   and list_result['test_execution']['returncode'] == 0
                                   and list_result['source_before'] == list_result['source_after'])
    save('eleven-list-admission.json', list_admission)
    report = NATIVE / 'diagnostic-eleven.xml'
    checks = []
    coverage = {'available': report.is_file(), 'exact_pass_coverage': False, 'diagnostic_only': True}
    if report.is_file():
        nodes = list(ET.parse(report).getroot().iter('testcase'))
        for name in CONFIG['required_names']:
            matched = [node for node in nodes if node.attrib.get('name') == name]
            passed = len(matched) == 1 and not any(child.tag in ('error', 'failure', 'skipped', 'flakyFailure', 'flakyError', 'rerunFailure', 'rerunError') for node in matched for child in node)
            checks.append({'name': name, 'observed_count': len(matched), 'passed': passed, 'attributes': [dict(node.attrib) for node in matched]})
        coverage.update(junit=str(report), junit_sha256=sha(report), expected_count=11, observed_count=len(nodes), checks=checks,
                        exact_pass_coverage=len(nodes) == 11 and all(check['passed'] for check in checks))
    save('eleven-named-case-coverage.json', coverage)
    exit_code = 0 if tested['returncode'] == 0 and driver_result_path.is_file() and list_admission['exact'] and coverage['exact_pass_coverage'] else 1
    result.update(status='diagnostic-passed' if exit_code == 0 else 'diagnostic-failed', native_process=tested, named_case_coverage=coverage)
except BaseException as error:
    result.update(status='failed', error=repr(error),
                  native_result_file_observed=(NATIVE / 'driver-result.json').is_file(),
                  native_launch_record_observed=(RECORDS / 'native-process-launch.json').is_file())
    traceback.print_exc()
finally:
    try:
        final, _, final_bytes = snapshot('source-after')
        result['source_after'] = final
        result['postimages'] = retain_changes('final')
        if source_ready is not None and (final != source_ready or final_bytes != source_bytes):
            result.update(status='failed', source_changed=True)
            exit_code = 1
        if caller_before is not None:
            caller_after = identity(CALLER)
            save('caller-after.json', caller_after)
            if caller_after != caller_before:
                result.update(status='failed', caller_changed=True)
                exit_code = 1
    except BaseException as error:
        result.update(status='failed', retention_error=repr(error))
        exit_code = 1
    result.update(finished_at=now(), exit_code=exit_code)
    save('result.json', result)
    print(json.dumps({'diagnostic_pipeline_result': result}, sort_keys=True), flush=True)
raise SystemExit(exit_code)
