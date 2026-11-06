"""Construct a source54 integrity candidate without granting test qualification."""
from pathlib import Path
import copy
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
P = Path(__file__).parent
REPORT = ROOT / 'hepta-cell/qualification/cell-unification-20261106'
NATIVE = REPORT / 'native-evidence'
PREFIX = 'qualification/cell-unification-20261106/native-evidence/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read(path):
    return json.loads(Path(path).read_bytes())

def reference(relative):
    return {'path': relative, **pin((NATIVE / relative).read_bytes())}

def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with (P / name).open('xb') as f: f.write(raw)
    return {'path': str((P / name).relative_to(ROOT)), **pin(raw)}

old_raw = (P / 'INDEX-v4-original.json').read_bytes()
assert pin(old_raw)['sha256'] == 'fe9d15906ac379e33e7d58e0bed4e385592cf79d4b8eaf6e76e2c90beb48dc61'
assert (NATIVE / 'INDEX.json').read_bytes() == old_raw
old = json.loads(old_raw)
candidate = copy.deepcopy(old)
overlay = read(ROOT / 'r31-formal-root-preparation/COMBINED-STAGED-OVERLAY.json')
formal_raw = (ROOT / 'source53-finalization-root-publication/ROOT-UPLOAD-PLAN.json').read_bytes()
assert pin(formal_raw)['sha256'] == '92de209c74f5590bab22669de4efb2d2db381dc603f09ba07feadea803b34f6a'
formal = json.loads(formal_raw)
raw_rows = []
for path, blob in overlay['files'].items():
    assert path.startswith(PREFIX)
    raw = (ROOT / 'hepta-cell' / path).read_bytes()
    actual = pin(raw)
    assert actual['git_blob'] == blob and actual['bytes'] == overlay['file_sizes'][path]
    raw_rows.append({'path': path.removeprefix(PREFIX), **actual})
for row in formal['files']:
    assert row['repo_path'].startswith(PREFIX)
    raw = Path(row['local_path']).read_bytes()
    assert pin(raw) == {k: row[k] for k in pin(raw)}
    raw_rows.append({'path': row['repo_path'].removeprefix(PREFIX), **pin(raw)})
preserved_path = 'history/source54-index/INDEX-v4.json.gz'
preserved = (NATIVE / preserved_path).read_bytes()
assert gzip.decompress(preserved) == old_raw and preserved[4:8] == b'\0' * 4
raw_rows.append({'path': preserved_path, **pin(preserved),
                 'decompressed_bytes': len(old_raw), 'decompressed_sha256': pin(old_raw)['sha256'],
                 'decompressed_git_blob': pin(old_raw)['git_blob'], 'encoding': 'gzip-mtime0'})
new_paths = {r['path'] for r in raw_rows}
assert len(new_paths) == len(raw_rows) == 1510
assert not new_paths & {r['path'] for r in old['artifacts']}
assert not new_paths & {r['path'] for r in old['additional_inherited_git_paths_not_in_prior_raw_inventory']}
candidate['artifacts'].extend(sorted(raw_rows, key=lambda r: r['path']))
candidate['observed_local_artifacts'].extend(sorted(raw_rows, key=lambda r: r['path']))
for key in ['artifacts', 'observed_local_artifacts']:
    current = {r['path']: r for r in candidate[key]}
    assert all(current[r['path']] == r for r in old[key])
for key in ['historical_artifact_git_bindings', 'additional_inherited_git_paths_not_in_prior_raw_inventory', 'unmaterialized_binary_references']:
    assert candidate[key] == old[key]

tested_commit = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
tested_tree = '440d4a8e09af4009e4d9ea067388826308da8803'
source_commit = 'b5209cfdf509e990f10922197b32540bf8c353a7'
source_tree = '42c1dd4e1a751c690c2800dfc3868e771dc9c70b'
r31 = read(NATIVE / 'r31-workspace-checkpoint/CLOSURE.json')
r30 = read(NATIVE / 'r30-project-checkpoint/CLOSURE.json')
final = read(NATIVE / 'source53-finalization-checkpoint/CLOSURE.json')
assert r31['source_commit'] == r30['source_commit'] == tested_commit
assert r31['source_tree'] == r30['source_tree'] == tested_tree
assert final['root_registered_final_commit'] == source_commit and final['final_formatted_tree'] == source_tree
candidate.update(schema='hepta.cell-unification-evidence-index.v5', status='FROZEN_INTEGRITY_INVENTORY',
    scope='Preserve all 2109 prior raw rows, 50 Git-only identities and 139 historical reference observation boundaries; add only 1510 fully rehashed local files. Blob-map and publication-tree verification are separate from test and scientific qualification.',
    source_identity={'commit': source_commit, 'tree': source_tree, 'stage': 54, 'changed_paths': 197,
                     'rust_paths': 183, 'other_paths': 14, 'gitdata_identity_not_native_checkout': True},
    tested_source_identity={'commit': tested_commit, 'tree': tested_tree, 'stage': 53,
                            'native_HEAD': 'bef6fa7645df9df12b69fda499e97eed25de6c75'},
    candidate_state='READY_FOR_STACKED_DRAFT_PR',
    snapshot_basis='Closed R30/R31 original gates on source53, actual subsequent scoped fix/default fmt, and separately registered source54. Branch, artifact7 and exact published-SHA CI remain future at this snapshot.',
    facts_input=reference('source53-finalization-checkpoint/CLOSURE.json'),
    previous_index={'path': preserved_path, **pin(preserved), 'encoding': 'gzip-mtime0',
                    'original_raw': pin(old_raw), 'artifact_checkpoint': '9896f63f1352906a6afec53b94d4d123143ba35e',
                    'report_tree': '94736852bab3ffd438d66a5e980c7f4eb9d968ad', 'artifact_count': 2109},
    checkpoint6_actual_git_basis={'commit': '9896f63f1352906a6afec53b94d4d123143ba35e',
        'report_tree': '94736852bab3ffd438d66a5e980c7f4eb9d968ad', 'report_files': 2370,
        'native_evidence_leaves_including_self': 2160,
        'tree_url': 'https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/trees/94736852bab3ffd438d66a5e980c7f4eb9d968ad?recursive=1'},
    source_ledger_snapshot={'path': '../history/source53-final-report/final-code-registration/PUBLICATION-LEDGER-SNAPSHOT.json',
        **pin((ROOT / 'source54-root-registration/LEDGER-AFTER-SOURCE54.json').read_bytes()),
        'registered_source_records': 54, 'registered_binary_paths_at_that_snapshot': 264,
        'artifact_checkpoints_at_that_snapshot': 6, 'not_a_permanent_current_attachment_count': True},
    prior_index_root_adoption=copy.deepcopy(old['root_adoption']),
    root_adoption={'old2109_raw_rows_preserved_exact': True, 'new1510_artifacts_rehashed': True,
        'old50_Git_only_and139_reference_observation_fields_preserved': True,
        'source_code_or_native_execution_changed_by_index_construction': False,
        'independent_actual_blob_map_verification_required_before_adoption': True,
        'separate_actual_publication_tree_verification_still_required': True},
    post_fix_or_format_tests_executed=False, qualification_transferred_to_mutated_tree=False,
    final_SHA_CI='PENDING_EXACT_PUBLISHED_SHA', branch_created=False, pull_request_created=False,
    formal_INDEX_written=False,
    formal_INDEX_written_scope='Construction-time snapshot; any later root adoption is recorded separately without rewriting this snapshot.',
    self_excluded=True, all_prior_Git_paths_retained_by_publication_plan_required=True,
    qualification_not_inferred_from_integrity=True, science='HOLD', authority='DENY_ALL')
candidate['last_closed_workspace_gate'] = {
    'gate': 'r31', 'source_commit': tested_commit, 'source_tree': tested_tree, 'status': 'PASS',
    'exit_code': 0, 'raw_exit': 0, 'effective_exit': 0, 'outer_exit': 0,
    'command': r31['original_command'], 'counts': r31['counts'], 'reported_skipped': 130,
    'workspace_members': 193, 'workspace_default_members': 193,
    'originals': reference('r31-workspace-checkpoint/CLOSURE.json')}
candidate['last_closed_complete_project_gate'] = {
    'gate': 'r30', 'source_commit': tested_commit, 'source_tree': tested_tree, 'status': 'PASS',
    'exit_code': 0, 'strict_exit': 0, 'tests_exit': 0, 'outer_exit': 0,
    'counts': r30['counts'], 'reported_skipped': 2,
    'originals': reference('r30-project-checkpoint/CLOSURE.json')}
candidate['current_workspace_snapshot'] = {
    'gate': 'r31', 'job_id': '1a1b275ba33-fc05-7e17', 'source_commit': tested_commit, 'source_tree': tested_tree,
    'command': r31['original_command'], 'fresh_metadata_exit_code': 0, 'workspace_members': 193,
    'workspace_default_members': 193, 'terminal_counts': r31['counts'], 'terminal_exit_code': 0,
    'reported_skipped': 130, 'fixed_closed_snapshot_not_live_status': True,
    'post_fix_or_format_tests_executed': False}
candidate['actual_finalization'] = {
    'originals': reference('source53-finalization-checkpoint/CLOSURE.json'),
    'fix_exit': 0, 'format_exit': 0, 'outer_exit': 0, 'fix_changed_paths': 0, 'format_changed_paths': 56,
    'final_registered_commit': source_commit, 'final_tree': source_tree, 'residual_warning_diagnostics': 3,
    'strict_D_warnings_clean_claimed': False, 'diagnostic_only': True, 'behavior_repair_claimed': False,
    'post_fix_or_format_tests_executed': False, 'qualification_transferred_to_mutated_tree': False}
for field, array in [('artifact_count', 'artifacts'), ('historical_artifact_count', 'historical_artifact_git_bindings'),
                     ('current_raw_hash_count', 'observed_local_artifacts'),
                     ('inherited_additional_git_reference_count', 'additional_inherited_git_paths_not_in_prior_raw_inventory'),
                     ('unmaterialized_reference_count', 'unmaterialized_binary_references')]:
    candidate[field] = len(candidate[array])
assert candidate['artifact_count'] == 3619 and candidate['current_raw_hash_count'] == 1946
result = write('INDEX.candidate.json', candidate)
proof = write('ROOT-CONSTRUCTION-READBACK.json', {
    'schema': 'hepta.root-source54-index-construction.v1', 'candidate': result, 'previous_index': pin(old_raw),
    'preserved_gzip': pin(preserved), 'old_raw_rows': 2109, 'new_raw_rows': 1510,
    'old_git_only_paths': 50, 'old_unmaterialized_reference_rows': 139,
    'old_historical_observation_fields_preserved': True, 'source54_actual_code': source_commit,
    'source53_tested_code': tested_commit, 'canonical_written': False, 'native_commands_executed': False,
    'actual_blob_and_independent_review_still_required': True})
print(json.dumps({'candidate': result, 'construction': proof}, indent=2))
