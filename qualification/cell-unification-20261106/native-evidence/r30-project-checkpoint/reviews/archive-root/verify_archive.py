import hashlib
import json
import os
import pathlib
import tarfile


ROOT = pathlib.Path('native-validation-results/r30-archive-closed')
ARCHIVE = ROOT / 'checkpoint-r30-closed.tar.gz'
PREFIX = 'native-source53-project-r30'
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'


def pin(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }


def safe(name):
    path = pathlib.PurePosixPath(name)
    assert name and not path.is_absolute() and '\\' not in name and '\0' not in name
    assert all(part not in ('', '.', '..') for part in name.split('/'))
    return path


archive_raw = ARCHIVE.read_bytes()
assert pin(archive_raw) == {
    'bytes': 1761785,
    'sha256': '14abba7cfb44b96d6a13c926335a38eb8be55c786a865c3887b3908b48f2ddce',
    'git_blob': '7bcac57e66f262e36a159e6530d7c178ccac51f7',
}
with tarfile.open(ARCHIVE, 'r:gz') as tar:
    members = tar.getmembers()
    assert len(members) == len({member.name for member in members}) == 303
    contents = {}
    modes = {}
    for member in members:
        safe(member.name)
        assert member.isfile() and not member.issym() and not member.islnk()
        raw = tar.extractfile(member).read()
        assert len(raw) == member.size
        contents[member.name] = raw
        modes[member.name] = member.mode

index = json.loads(contents['INDEX.json'])
listed = {row['path']: row for row in index['files']}
assert len(listed) == len(index['files']) == 302
assert set(listed) == set(contents) - {'INDEX.json'}
for name, row in listed.items():
    assert pin(contents[name]) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    assert modes[name] == row['mode']
assert index['source_commit'] == COMMIT and index['source_tree'] == TREE
assert index['source_count'] == 197 and index['original_outer_exit'] == 0
assert index['original_gate_result'] == 'PASS' and index['readback_errors'] == []
assert index['counts'] == {'PASS': 1345, 'FAIL': 0, 'TIMEOUT': 0}
assert index['reported_skipped'] == 2 and index['diagnostic_only'] is True
assert index['behavior_repair_claimed'] is False
assert index['workspace_qualification'] == 'NOT_ESTABLISHED_BY_THIS_PROJECT_EXPORT'

source_raw = contents['input/native-candidate-r30-source.json']
assert source_raw == pathlib.Path('source53-apply-preparation/derived/native-candidate-r30-source.json').read_bytes()
source = json.loads(source_raw)
files = {row['path']: row for row in source['changed_files']}
assert len(files) == len(source['changed_files']) == 197
assert source['source_commit'] == COMMIT and source['source_tree'] == TREE
assert {name for name in contents if name.startswith('source/')} == {'source/' + name for name in files}
for name, row in files.items():
    raw = contents['source/' + name]
    assert pin(raw) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    assert ('100755' if modes['source/' + name] & 0o111 else '100644') == row['mode']
old_root = pathlib.Path('native-validation-results/r29-archive-closed/original')
old_manifest = json.loads((old_root / 'input/native-candidate-r28-source.json').read_bytes())
old = {row['path']: row for row in old_manifest['changed_files']}
assert len(old) == 195 and all(files[name] == row for name, row in old.items())
for name in old:
    assert contents['source/' + name] == (old_root / 'source' / name).read_bytes()
extra = set(files) - set(old)
assert extra == {
    'codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs',
    'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs',
}
apply_root = pathlib.Path('native-validation-results/source53-apply-v2-closed/evidence/native-source53-apply/input/after')
for name in extra:
    assert contents['source/' + name] == (apply_root / name).read_bytes()
for name, digest in {
    'codex-rs/Cargo.lock': '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c',
    'MODULE.bazel.lock': 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb',
}.items():
    assert hashlib.sha256(contents['locks/' + name]).hexdigest() == digest

closed_root = pathlib.Path('native-validation-results/r30-closed-input/evidence')
closed = {path.name: path.read_bytes() for path in closed_root.iterdir() if path.is_file()}
assert len(closed) == 20
for name, raw in closed.items():
    assert contents['evidence/' + name] == raw
root_review = json.loads(pathlib.Path('source53-r30-root-review/COMPLETE-READBACK.json').read_bytes())
assert root_review['counts'] == index['counts'] and root_review['exact_baseline_ID_set'] is True
assert contents['evidence/' + PREFIX + '-closed-test-results.json'] == closed[PREFIX + '-tests-test-results.json']
export_review = json.loads(contents['evidence/' + PREFIX + '-closed-result-review.json'])
assert export_review['readback_errors'] == [] and export_review['original_gate_result'] == 'PASS'
assert export_review['original_test_review'] == json.loads(closed[PREFIX + '-tests-result-review.json'])
assert export_review['original_complete_present'] is True
assert export_review['original_incomplete_present'] is False
assert export_review['original_orchestration_error_present'] is False
assert not export_review['failure_blocks'] and export_review['missing_success_filenames'] == []
failure_index = json.loads(contents['failure-blocks/INDEX.json'])
assert not failure_index['failures'] and failure_index['parse_error'] is None
assert contents['input/baseline/source53-app-server-r29-baseline.json'] == pathlib.Path(
    'source53-app-server-baseline-preparation/BASELINE-IDS.json').read_bytes()

controller = pathlib.Path('native-validation-results/r30-closed-input/controller')
for name in ('launch.json', 'read-0.json', 'read-1.json', 'read-2.json', 'terminal-process-status.json'):
    assert contents['controller/' + name] == (controller / ('r30-controller-closed-' + name)).read_bytes()
for stream in ('stdout', 'stderr'):
    assert contents['controller/original-' + stream + '.txt'] == (controller / ('original-' + stream + '.log')).read_bytes()
source_proof = json.loads(contents['evidence/' + PREFIX + '-export-source-verification.json'])
assert source_proof['source_guard_before'] == source_proof['source_guard_after']
guard = source_proof['source_guard_after']
assert guard['source_commit'] == COMMIT and guard['source_tree'] == TREE and guard['native_head'] == HEAD
assert guard['source_count'] == 197 and guard['pass'] is True
assert source_proof['all197_raw_sha_gitblob_gitmode_verified'] is True

destination = ROOT / 'original'
assert not destination.exists()
destination.mkdir()
for name, raw in contents.items():
    output = destination.joinpath(*safe(name).parts)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as handle:
        handle.write(raw)
    output.chmod(modes[name] & 0o777)
    assert output.read_bytes() == raw

report = {
    'schema': 'hepta.root-r30-full-archive-readback.v1',
    'archive': {'path': str(ARCHIVE), **pin(archive_raw)},
    'members': 303, 'indexed_original_and_derived_members': 302,
    'all_member_bytes_sha_git_and_transport_modes_verified': True,
    'source_manifest': pin(source_raw), 'source_changed_files': 197,
    'all197_source_raw_sha_git_blob_and_Git_mode_verified': True,
    'all195_parent_source_payloads_equal_original_R29_archive': True,
    'two_new_leaf_payloads_equal_actual_source53_apply': True,
    'full_repository_unchanged_files_not_in_this_archive': True,
    'all19_gate_originals_and_outer_equal_independently_reviewed_local_bytes': True,
    'full_log_and_all1345_rows_equal_root_independent_review': True,
    'counts': index['counts'], 'reported_skipped': 2,
    'controller_five_originals_and_full5097_stdout_zero_stderr_equal': True,
    'exporter_source_guards_and_dual_locks_pass': True,
    'original_R30_natural_exit': 0, 'archive_export_is_separate_from_gate': True,
    'original_R29_failure_relabelled': False,
    'R31_result_claimed': False, 'diagnostic_only': True,
    'behavior_repair_claimed': False, 'science': 'HOLD', 'authority': 'DENY_ALL',
    'safe_extraction_after_complete_readback': str(destination),
    'index': pin(contents['INDEX.json']),
}
report_raw = (json.dumps(report, indent=2) + '\n').encode()
output = ROOT / 'ROOT-ARCHIVE-READBACK.json'
with output.open('xb') as handle:
    handle.write(report_raw)
    handle.flush()
    os.fsync(handle.fileno())
print(json.dumps({'path': str(output), **pin(report_raw)}))
