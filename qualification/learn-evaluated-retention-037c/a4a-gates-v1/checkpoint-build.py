from pathlib import Path
import datetime
import gzip
import hashlib
import json
import re
import shutil


ROOT = Path('/tmp/hepta-learn-037c-20261112')
OUT = ROOT / 'recovery-a4a-gates-evidence-v1'
PREFIX = Path('qualification/learn-evaluated-retention-037c/a4a-gates-v1')
SOURCE = 'a4a1b5eb6cb45fc1182564e6b81026a2a2acf609'
TREE = 'e09e7fb338e5f9a37fccfd4f05a8d5c222d7c0da'
SOURCE_SCHEMA = '29f9e6135150109dd4b4072b9e8f7851e34b7ab499bfa622e16e698a88468573'
NATIVE_SCHEMA = '44c3844eb82f19ae3cce36d86fa2d919c8c1a486715b7d4d590e0cb5ecf84638'
S = ROOT / 'source-origin-fixed-a4a1b5eb-v1'
M = ROOT / 'root-maintenance-a4a1b5eb-v1'
C = ROOT / 'fullcaller-a4a1b5eb-isolated-v1'
V1 = ROOT / 'recovery-native-eleven-template-v1/after-maintenance-a4a-final-v1'
A = ROOT / 'recovery-native-eleven-a4a-audit-v1'
V2 = A / 'v2-candidate'
START = ROOT / 'root-native-eleven-a4a-v2'


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def checked(path, sha=None):
    data = path.read_bytes()
    if sha is not None:
        assert hashlib.sha256(data).hexdigest() == sha, str(path)
    return data


def read_json(path):
    return json.loads(checked(path))


source_result = read_json(S / 'source-result.json')
source_execution = read_json(S / 'source-execution.json')
maintenance = read_json(M / 'originals/result.json')
caller = read_json(C / 'originals/result.json')
caller_verify = read_json(C / 'originals/verify.json')
caller_self = read_json(C / 'originals/self-test.json')
local_tests = read_json(V2 / 'LOCAL_FINAL_MECHANISM_TESTS.json')
assert source_result['status'] == 'passed' and source_result['exit_code'] == 0
assert source_result['before'] == source_result['after']
assert source_result['after']['file_count'] == 15230
assert source_result['after']['inventory_sha256'] == SOURCE_SCHEMA
assert source_execution['source_sha'] == source_execution['tested_sha'] == SOURCE
assert source_execution['observed_passed_tests'] == 504
assert source_execution['observed_failed_tests'] == 0
assert source_execution['timed_out'] is False and source_execution['output_limit_exceeded'] is False
assert source_execution['before'] == source_execution['after']
assert maintenance['before'] == maintenance['after_format'] == maintenance['after']
assert maintenance['after']['inventory_sha256'] == NATIVE_SCHEMA
assert maintenance['after']['file_count'] == 15230 and maintenance['after']['dirty'] == ''
assert maintenance['exit_code'] == maintenance['execution']['returncode'] == maintenance['format_execution']['returncode'] == 0
assert maintenance['execution']['controller_kill'] is False
assert maintenance['postimages']['file_count'] == maintenance['postimages']['patch_bytes'] == 0
assert caller['exit_code'] == 1 and caller['status'] == 'failed'
assert caller['before'] == caller['after'] and caller['metadata_before'] == caller['metadata_after']
assert caller['before']['file_count'] == 15230 and caller['before']['inventory_sha256'] == NATIVE_SCHEMA
assert caller_verify['returncode'] == 1 and caller_verify['timed_out'] is False
assert caller_verify['output_limit_exceeded'] is False and caller_self['returncode'] == 0
assert checked(C / 'originals/source-before.json') == checked(C / 'originals/source-after.json')
assert local_tests['actual_returncode'] == 0 and local_tests['observed_tests'] == 19
assert local_tests['H_calls'] == local_tests['Cargo_or_Rust_invocations'] == 0
assert local_tests['native_qualification'] is False
assert re.search(rb'Ran 19 tests in [0-9.]+s\s+OK\s*$', checked(V2 / 'LOCAL_FINAL_MECHANISM_TESTS.raw.log'))

for directory, name, sha in [
    (S, 'source-result.json', 'fd283e2847c6dde06ffb6f0a97bfeb2ab250e92f7ff1eb89d8b4dd9471cf3294'),
    (S, 'source-execution.json', '6d7ca8638ca69aeaf89833681cd672637a09c961d234d9d354b983a903a26c50'),
    (S, 'source-test.FULL.raw.log', 'f5f4d4991e2cc4ea40ab16869e2eb849b5e2f8dc71154903d99b0a1dae307cf4'),
    (M, 'originals/result.json', 'df3c3c2346180d1cd584a4e579337720b384cecd899fa802131281154122c140'),
    (M, 'originals/just-fix.FULL.raw.log', '0c48924125fcd5f7cbd64b5fd058d72d5bea88cee7445bdbd8a1516bff4e4b93'),
    (C, 'originals/verify.log', 'd799e211e79d0b2319d70e65f6b486c7bf71fab07acc925f24b01c8ed61658ec'),
    (V1, 'REQUEST.typed.json', 'c5a0e3068c15a63caec212f6e6fabe808952e27f735359556a4f39ff01c3cd17'),
    (V2, 'REQUEST.typed.json', '1ecebf1a3ff084e20c12090b09b7707d2889973cee82c22c575155e356e740d2'),
    (V2, 'prepare-driver.py', '8c09dc4b88cb5758c9b643f33bb2589ca2232b01d1ebed1930f4351b9aa883e6'),
    (V2, 'LOCAL_FINAL_MECHANISM_TESTS.raw.log', '4ec71dbb021584e782b28a1cf5dbcc1acdc909617b17bdabcb932c0cf841272a'),
]:
    checked(directory / name, sha)

for row in read_json(S / 'FULL_READ_VERIFIED.json')['files']:
    original = checked(S / row['name'], row['original_sha256'])
    archive = checked(S / (row['name'] + '.gz'), row['gzip_sha256'])
    assert len(original) == row['original_bytes'] and len(archive) == row['gzip_bytes']
    assert gzip.decompress(archive) == original
assert gzip.decompress(checked(M / 'originals/just-fix.FULL.raw.log.gz')) == checked(M / 'originals/just-fix.FULL.raw.log')
assert meta(checked(C / 'originals/verify.log'))['sha256'] == caller_verify['log_sha256']
assert meta(checked(C / 'originals/self-test.log'))['sha256'] == caller_self['log_sha256']
workflow = read_json(C / 'originals/original-workflow.json')
assert meta(checked(C / 'originals/original-workflow.raw.log'))['sha256'] == workflow['log_sha256']
assert checked(START / 'REQUEST.typed.json') == checked(V2 / 'REQUEST.typed.json')
assert checked(START / 'prepare-driver.py') == checked(V2 / 'prepare-driver.py')
start_original = read_json(START / 'START_ACK.original.json')
ack = json.loads(start_original['content'][0]['text'])
assert ack['session_id'] == 'dpty-a4314780d949fe302af6ba42ccc8d9dbfbaed85cfdebdf6b35743cd44fe2c295'
assert ack['status']['state'] == 'running' and ack['reused'] is False

tool_blobs = {
    'hepta_ci_exec.py': 'c9434b3a4afb31f80e323d543936386a2fa738de',
    'hepta_ci_junit.py': '683626df091bdfe160a8965fdc92bf40f5783cf8',
    'hepta_cell_test_helpers.py': 'f5b702a55b44c081c6d8f5556da3a2152a33eec3',
}
for name, blob in tool_blobs.items():
    assert meta(checked(A / 'exact-source-tools/scripts' / name))['git_blob'] == blob

OUT.mkdir(exist_ok=False)
DEST = OUT / 'payload' / PREFIX
DEST.mkdir(parents=True)
rows = []


def copy_file(source, rel, category):
    data = checked(source)
    dest = DEST / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('xb') as stream:
        stream.write(data)
    assert checked(dest) == data == checked(source), str(source)
    rows.append({'repository_path': str(PREFIX / rel), 'package_relative_path': str(Path('payload') / PREFIX / rel),
                 'source_local_path': str(source), 'category': category, **meta(data)})


def group(directory, dest, names, category):
    for name in names:
        copy_file(directory / name, str(Path(dest) / name), category)


group(S, 'source504', [p.relative_to(S).as_posix() for p in sorted(S.rglob('*')) if p.is_file()
                      and not p.name.startswith('PR_') and p.name != 'RUNTIME_CHECKPOINT_REF.original.json'],
      'exact-a4a-source-gate-original-or-driver')
group(M, 'maintenance', [
    'driver.py', 'driver-adaptation.patch', 'REQUEST.typed.json', 'MANIFEST.json', 'ROOT_REQUEST_REVIEW.json',
    'START_ACK.original.json', 'PTY_INITIAL.original.json', 'PTY_AFTER_2949.original.json',
    'LOCK_READ_REQUEST.typed.json', 'LOCK_READ_START_ACK.original.json', 'LOCK_READ_FULL.original.json',
    'ASYNC_maintenance_terminal.native-original.json', 'ASYNC_maintenance_terminal_RESULT.original.json',
    'FULL_COMPILER_READ_VERIFIED.json', 'FULL_LOG_ASYNC_START.original.json',
    'originals/result.json', 'originals/just-fmt.json', 'originals/just-fix.json', 'originals/postimages.json',
    'originals/just-fix.FULL.raw.log', 'originals/just-fix.FULL.raw.log.gz',
] + [p.relative_to(M).as_posix() for p in sorted((M / 'log-read-pages').glob('fix_log*'))],
      'exact-a4a-maintenance-original-or-driver')
group(C, 'fullcaller-failed', [p.relative_to(C).as_posix() for p in sorted(C.rglob('*')) if p.is_file()],
      'exact-a4a-failed-caller-original-or-driver')
group(V1, 'native11-v1-static-rejected', [
    'CONFIG.json', 'MANIFEST.json', 'REQUEST.typed.json', 'prepare-driver.py', 'diagnostic-driver.py',
    'list_run_gate.py', 'maintenance-driver.py', 'BUNDLED_DRIVERS.json',
    'LOCAL_BINDING_REVIEW.json', 'ROOT_SCHEDULING_HOLD.json',
], 'unexecuted-v1-static-review-input')
group(V2, 'native11-v2-reviewed', [
    'CONFIG.json', 'CONFIG.patch', 'BUNDLED_DRIVERS.json', 'MANIFEST.final.json', 'REQUEST.typed.json',
    'prepare-driver.py', 'diagnostic-driver.py', 'list_run_gate.py', 'maintenance-driver.py',
    'prepare-nonembedded.patch', 'prepare-driver.py.complete.patch',
    'diagnostic-driver.py.complete.patch', 'list_run_gate.py.complete.patch',
    'LOCAL_FINAL_MECHANISM_TESTS.json', 'LOCAL_FINAL_MECHANISM_TESTS.raw.log',
], 'v2-orchestration-review-or-local-python-test')
copy_file(A / 'test_native11_v2.py', 'native11-v2-reviewed/test_native11_v2.py', 'local-python-mechanism-test-source')
group(START, 'native11-v2-root-start', [
    'ROOT_REQUEST_REVIEW.json', 'RESOURCE_REQUEST.typed.json', 'RESOURCE_START_ACK.original.json',
    'RESOURCE_READ.original.json', 'START_ACK.original.json',
], 'root-review-or-actual-start-original')
group(A / 'exact-source-tools/scripts', 'exact-a4a-tools/scripts', list(tool_blobs), 'unchanged-exact-a4a-source-tool')
copy_file(Path(__file__), 'checkpoint-build.py', 'checkpoint-local-copy-and-validation-code')


def derived(name, value):
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    path = DEST / name
    with path.open('xb') as stream:
        stream.write(data)
    rows.append({'repository_path': str(PREFIX / name), 'package_relative_path': str(Path('payload') / PREFIX / name),
                 'source_local_path': None, 'category': 'derived-checkpoint-index-not-execution-original', **meta(data)})
    return meta(data)


blocker = {
    'status': 'STATIC_REJECTED_BEFORE_EXECUTION_NEVER_STARTED', 'source': SOURCE, 'tree': TREE,
    'request': meta(checked(V1 / 'REQUEST.typed.json')),
    'reason': 'v1 actual execution command begins python3 list_run_gate.py; original JUnit collector requires actual command prefix just,test,--locked',
    'collector_path': 'scripts/hepta_ci_junit.py', 'collector_git_blob': tool_blobs['hepta_ci_junit.py'],
    'not_an_execution_failure': True, 'H_start_submitted': False, 'native_cases_run': 0,
    'regression_evidence': 'native11-v2-reviewed/LOCAL_FINAL_MECHANISM_TESTS.raw.log',
    'regression_scope': 'real unchanged collector with explicit synthetic execution/XML fixtures; no native Rust execution',
}
derived('V1_STATIC_BLOCKER.json', blocker)
derived('V2_STATIC_REVIEW.json', {
    'status': 'ROOT_REVIEWED_AND_STARTED_RESULT_NOT_COLLECTED', 'source': SOURCE, 'tree': TREE,
    'request': meta(checked(V2 / 'REQUEST.typed.json')), 'local_mechanism_tests': 19,
    'actual_local_test_exit': 0, 'native_qualification': False,
    'independent_original_ci_records': ['list-execution.json', 'diagnostic-eleven.json'],
    'collector_consumes_actual_just_record': True, 'collector_and_execute_logged_unchanged': True,
    'shared_acceptance_budget_seconds': 7200, 'helper_budget_seconds': 3600,
    'budget_rule': 'one absolute end captured before list; each phase receives only remaining time; start or finish at/after end forces overall failure even if child and collector return zero',
    'parent_added_signals_kills_or_tracing': False, 'natural_original_controller_cleanup': True,
    'timeout_cleanup_is_not_extra_acceptable_time': True,
    'original_11_names_required_in_actual_list_and_fresh_junit_once_each': True,
    'no_rerun_of_actual_clean_maintenance': True,
    'case_seconds': 60, 'stack_bytes': 8388608, 'test_threads': 2, 'retries': 0,
    'protocol_frames': 128, 'connections': 4, 'evidence_deadline_ms': 500, 'session_seconds': 300,
    'tool_pin_limit': 'native archive, bindings, nextest, rustfmt bytes explicitly pinned; selected rustc/cargo/just paths and observed versions recorded rather than falsely asserted as separately SHA-pinned binaries',
    'old_metadata_preserved': 'pre-start v2 MANIFEST.final.json and ROOT_REQUEST_REVIEW.json remain original historical snapshots; actual START_ACK is separate and does not establish test phase or outcome',
})

missing = [
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1/source-before.files.json.gz', 'reason': 'full inventory payload not copied into this local package; original result pins inventory hash/count'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1/source-after.files.json.gz', 'reason': 'full inventory payload not copied into this local package; original result pins inventory hash/count'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/source-before.files.json.gz', 'reason': 'full inventory payload not copied; maintenance driver compared exact whole bytes with source gate inventory and recorded hash'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/source-after-fmt.files.json.gz', 'reason': 'full inventory payload not copied'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/source-after.files.json.gz', 'reason': 'full inventory payload not copied'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/just-fmt.raw.log', 'bytes': 73, 'sha256': maintenance['format_execution']['log_sha256'], 'reason': 'phase result and identity retained; raw bytes not locally available and not reconstructed'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/maintenance.patch', 'bytes': 0, 'sha256': maintenance['postimages']['patch_sha256'], 'reason': 'original result records empty patch; package does not synthesize an original empty file'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/native-environment.json', 'reason': 'actual runtime environment record remains remote; submitted driver and typed request are retained locally'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/fullcaller-a4a1b5eb6cb4-v1/source-before.files.json.gz', 'reason': 'full inventory payload not copied; exact result pins same count/hash and metadata'},
    {'path': '/home/qian-qi/hepta-learn-037c-evidence/fullcaller-a4a1b5eb6cb4-v1/source-after.files.json.gz', 'reason': 'full inventory payload not copied; source-before/source-after terminal JSON originals retained'},
]
derived('LOCAL_CONTENT_GAPS.json', {'qualification': False, 'no_host_reads_performed_for_this_package': True, 'items': missing,
    'meaning': 'Missing here means not copied locally into this checkpoint; it does not assert that the durable original file is missing on the host.'})
created = datetime.datetime.now(datetime.timezone.utc).isoformat()
derived('CHECKPOINT_STATUS.json', {
    'status': 'PREPARED_FOR_GIT_CHECKPOINT_NOT_PUBLISHED', 'prepared_at': created,
    'source': SOURCE, 'tree': TREE, 'qualification': False,
    'source_gate': {'status': 'PASS', 'cases': 504, 'failed': 0, 'exit_code': 0, 'timeout': False, 'source_inputs': 15230, 'inventory_sha256': SOURCE_SCHEMA},
    'maintenance': {'status': 'CLEAN_ZERO', 'fmt_exit': 0, 'fix_exit': 0, 'postimages': 0, 'patch_bytes': 0, 'source_inputs': 15230, 'inventory_sha256': NATIVE_SCHEMA},
    'fullcaller': {'status': 'FAIL', 'self_test_exit': 0, 'verify_exit': 1, 'timeout': False, 'boundary': 'learning_original_owner_command_channel', 'unexpected_actual_paths': 7, 'source_inputs_unchanged': True},
    'native11_v1': 'STATIC_REJECTED_NEVER_STARTED',
    'native11_v2': {'status': 'ACK_RUNNING_AT_OBSERVATION_RESULT_NOT_COLLECTED', 'session_id': ack['session_id'], 'created_unix_ms': ack['status']['created_unix_ms'], 'request_key': 'learn-037c-native-a4a1b5eb6cb4-diagnostic-eleven-v2', 'list_result': 'NOT_COLLECTED', 'test_result': 'NOT_COLLECTED', 'junit': 'NOT_COLLECTED'},
    'original_publication_qualification_counts': {'complete_ordinary_adopt': 0, 'complete_ordinary_no_update': 0, 'complete_daemon_and_root_cold_recovery': 0},
    'all_pass_claim': False, 'native_acceptance_claim': False, 'cross_commit_promotion': False,
    'inventory_schema_note': 'Source gate inventory omits Git blob field; maintenance/caller inventory includes it. Different inventory hashes are not compared as equal. Original drivers compare all source rows after the documented schema conversion.',
    'scope_note': 'All observations in this checkpoint bind a4a. A later metadata-only branch head does not retroactively change a4a source/caller outcomes.',
})

rows.sort(key=lambda row: row['repository_path'])
manifest = {'schema_version': 1, 'status': 'LOCAL_FROZEN_CHECKPOINT_READY_FOR_ROOT_REVIEW',
    'created_at': created, 'source': SOURCE, 'tree': TREE, 'qualification': False,
    'repository_prefix': str(PREFIX), 'artifact_count': len(rows), 'artifact_bytes': sum(r['bytes'] for r in rows),
    'files': rows, 'git_mutations_performed': 0, 'H_calls': 0, 'Rust_or_Cargo_invocations': 0,
    'native_result_intentionally_not_frozen': True, 'local_content_gaps': 'LOCAL_CONTENT_GAPS.json'}
manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
(DEST / 'FILE_MANIFEST.json').write_bytes(manifest_bytes)
(OUT / 'FILE_MANIFEST.json').write_bytes(manifest_bytes)
for row in rows:
    assert meta(checked(OUT / row['package_relative_path'])) == {k: row[k] for k in ['bytes', 'sha256', 'git_blob']}
    if row['source_local_path']:
        assert checked(Path(row['source_local_path'])) == checked(OUT / row['package_relative_path'])
delivery = {'status': 'LOCAL_READY_NO_GIT_WRITE', 'artifact_count_in_manifest': len(rows),
    'artifact_bytes_excluding_manifest': sum(r['bytes'] for r in rows), 'manifest': meta(manifest_bytes),
    'path': str(OUT), 'repository_prefix': str(PREFIX), 'source': SOURCE,
    'original_files_changed': 0, 'all_copies_rehashed_and_sources_unchanged': True,
    'original_gzip_checks_passed': True, 'source_and_maintenance_and_caller_terminal_records_checked': True,
    'native11': 'START_ACK_ONLY_RESULT_NOT_COLLECTED', 'qualification': False}
(OUT / 'DELIVERY.json').write_text(json.dumps(delivery, indent=2, sort_keys=True) + '\n')
print(json.dumps(delivery, indent=2))
