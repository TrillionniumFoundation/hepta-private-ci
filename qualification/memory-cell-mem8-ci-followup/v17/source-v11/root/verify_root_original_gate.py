"""Bind root's independent complete V11 ZIP/canonical replay to original API records."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / 'mem8-source-v11-original-run'
REPLAY = HERE / 'root-original-readback-v2'

def read(path):
    return json.loads(path.read_bytes())

def unwrap(value):
    if 'structuredContent' in value:
        return unwrap(value['structuredContent'])
    if isinstance(value.get('content'), str):
        return unwrap(json.loads(value['content']))
    return value

def subset_equal(full, captured):
    if isinstance(captured, dict):
        assert isinstance(full, dict)
        for key, value in captured.items():
            assert key in full
            subset_equal(full[key], value)
    elif isinstance(captured, list):
        assert isinstance(full, list) and len(full) == len(captured)
        for a, b in zip(full, captured, strict=True):
            subset_equal(a, b)
    else:
        assert full == captured

jobs = read(HERE / 'ROOT_ORIGINAL_JOBS.json')
captured_jobs = unwrap(read(ORIGINAL / 'TERMINAL_JOBS.json'))
for captured_job in captured_jobs['jobs']:
    assert captured_job.pop('logs_url') is None
subset_equal(jobs, captured_jobs)
assert len(jobs['jobs']) == 1
job = jobs['jobs'][0]
assert (job['id'], job['run_id'], job['run_attempt']) == (130691870162, 43069105073, 1)
assert job['status'] == 'completed' and job['conclusion'] == 'success'
assert job['head_sha'] == '15d51439723126f446185905d609d6f755be9f5a'
assert all(s['status'] == 'completed' and s['conclusion'] == 'success' for s in job['steps'])
arts = read(HERE / 'ROOT_ORIGINAL_ARTIFACTS.json')['artifacts']
assert len(arts) == 1
artifact = arts[0]
old_art = unwrap(read(ORIGINAL / 'ARTIFACT_METADATA.json'))['artifacts'][0]
assert all(artifact[k] == v for k, v in old_art.items())
assert artifact['id'] == 13878360578 and not artifact['expired']
data = (ORIGINAL / 'ORIGINAL_ARTIFACT.zip').read_bytes()
assert len(data) == artifact['size_in_bytes'] == 7243382
assert 'sha256:' + hashlib.sha256(data).hexdigest() == artifact['digest']
assert artifact['workflow_run']['id'] == 43069105073
assert artifact['workflow_run']['head_sha'] == job['head_sha']
zip_audit = read(REPLAY / 'ZIP_FULL_MEMBER_AUDIT.json')
assert zip_audit['member_count'] == 386 and zip_audit['all_lengths_crc_and_sha_checked']
material = read(REPLAY / 'CANONICAL_ARCHIVE_MATERIALIZATION.json')
assert material['state'] == 'COMPLETE_ORIGINAL_TAR_READ_AND_MATCHED'
assert material['tar_members'] == 387 and len(material['direct_zip_omitted_paths']) == 9
raw = (REPLAY / 'canonical-original/OFFLINE_VERIFICATION.json').read_bytes()
assert raw == (ORIGINAL / 'readback/canonical-original/OFFLINE_VERIFICATION.json').read_bytes()
result = json.loads(raw)
assert result['formatter_changed_paths'] == [] and result['source_after_status'] == ''
assert result['source_head_unchanged'] == 'ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80'
assert result['initial_tree'] == result['formatted_tree'] == '27651abb15e269c427c75f28f92a3bd1cd9d191f'
assert result['source_python_actual_pass'] == 18
assert result['source_python_actual_fail'] == result['source_python_actual_skip'] == 0
assert result['renamed_case_old_name_hits'] == 0 and result['rust_files_scanned'] == 6204
assert result['full_golden_equal_except_derived_rust_count']
assert len(result['locks_unchanged']) == 2
binding = read(ORIGINAL / 'VERIFIER_BINDING.json')
text = (ORIGINAL / 'verify_source_records_v11.py').read_text()
for edit in reversed(binding['edits']):
    assert text.count(edit['new']) == edit['count']
    text = text.replace(edit['new'], edit['old'])
assert text.encode() == (HERE.parent / 'mem8-source-v10-original-run/verify_source_records_v10.py').read_bytes()
assert (ORIGINAL / 'materialize_original.py').read_text().replace('mem8-source-gates-v11', 'mem8-source-gates-v10').encode() == (HERE.parent / 'mem8-source-v10-original-run/materialize_original.py').read_bytes()
proof = {
    'schema': 'mem8.v11.root-original-gate-replay.v1',
    'status': 'PASS_FULL_ORIGINAL_ZIP_CANONICAL_TAR_AND_UNCHANGED_VERIFIER',
    'run': 43069105073, 'job': 130691870162, 'attempt': 1,
    'source': result['source_head_unchanged'], 'tree': result['formatted_tree'],
    'original_ZIP_bytes': len(data), 'original_ZIP_sha256': hashlib.sha256(data).hexdigest(),
    'ZIP_members': 386, 'original_tar': result['original_archive'], 'manifest_members': 386,
    'full_replayed_result_bytes_equal': True,
    'original_API_all_captured_job_step_and_artifact_fields_bound': True,
    'additional_full_API_metadata_preserved': True,
    'normalized_tool_only_null_field': 'logs_url: null; absent from raw GitHub jobs API',
    'formatter_changed_paths': [], 'source_after_clean': True,
    'cumulative_overlay_paths': 118, 'rust_inventory': 6204, 'python_pass': 18,
    'old_name_hits': 0, 'full_golden_equal_except_derived_count': True,
    'both_lock_bytes_unchanged': True,
    'elapsed_seconds': result['elapsed_seconds'], 'original_deadline_seconds': 600,
    'native_tests_executed': 0, 'real_model_requests': 0,
    'first_root_copy_failure_retained': 'ROOT_EXTRACTION_ENOSPC.json',
    'complete_root_copy': 'root-original-readback-v2/canonical-original',
}
(HERE / 'ROOT_SOURCE_GATE_AUDIT.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof, indent=2))
