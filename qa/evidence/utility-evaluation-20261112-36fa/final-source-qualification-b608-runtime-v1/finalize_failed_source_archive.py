import hashlib
import json
from pathlib import Path

D = Path('/tmp/hepta-36fa-final-source-qualification-b608-runtime-v1')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def put(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    assert len(raw) <= 512000
    p = D / name
    if p.exists():
        assert p.read_bytes() == raw, p
    else:
        with p.open('xb') as f:
            f.write(raw)
    return {'path': str(p), **identity(raw)}

idxraw = (D / 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json').read_bytes()
assert identity(idxraw) == {'bytes': 47251, 'sha256': '1ad75fd2029c8da94a86e7f30c5e30021ae4bb4b0f29c78a06ec3b997b9bb201',
                            'git_blob': '1e8a1fab4ddbb63a8f14f4fced8a8ab21ce6cfcf'}
idx = json.loads(idxraw)
assert idx['count'] == len(idx['entries']) == 88
rows = []
for entry in idx['entries']:
    p = Path(entry['path'])
    b = p.read_bytes()
    pin = identity(b)
    assert pin == {k: entry[k] for k in pin}
    assert len(b) <= 512000
    b.decode('utf-8')
    lr = Path(str(p) + '.PUBLISH_LEDGER_ENTRY.json').read_bytes()
    cr = Path(str(p) + '.PUBLISH_CREATE.original.json').read_bytes()
    gr = Path(str(p) + '.PUBLISH_GET.original.json').read_bytes()
    ledger, made, fetched = [json.loads(x) for x in (lr, cr, gr)]
    assert ledger['actual_git_create'] and ledger['actual_full_get_equal']
    assert all(ledger[k] == v for k, v in pin.items())
    assert made.get('isError') is not True and made['structuredContent']['sha'] == pin['git_blob']
    assert fetched.get('isError') is not True and fetched['structuredContent']['content'].encode() == b
    previous = entry.get('prior_actual_full_get')
    if previous:
        assert identity(gr) == previous['get_sdk_identity']
    rows.append({'path': entry['evidence_path'], 'local_path': str(p), **pin,
                 'actual_create_and_complete_GET_equal': True,
                 'prior_claim_revalidated': bool(previous),
                 'original_create_sdk_identity': identity(cr), 'original_full_get_sdk_identity': identity(gr)})
assert sum(x['prior_claim_revalidated'] for x in rows) == 13
assert len({x['path'] for x in rows}) == 88
ledger = put('ARCHIVE_FULL_READBACK_LEDGER.json', {
    'format': 'hepta-completed-failed-source-runtime-full-get-ledger-v1',
    'job_id': idx['job_id'], 'fixed_at_utc': idx['fixed_at_utc'],
    'closed_index': identity(idxraw), 'count': 88, 'prior_full_get_claims_verified': 13,
    'new_full_get_equal': 75, 'entries': rows,
    'no_native_operations_by_this_verifier': True})
review = put('ARCHIVE_CLOSURE_REVIEW.json', {
    'format': 'hepta-completed-failed-source-runtime-archive-closure-v1',
    'status': 'FIXED_88_MEMBERS_ALL_ACTUAL_GIT_FULL_GET_EQUAL',
    'job_id': idx['job_id'], 'closed_index': identity(idxraw),
    'full_readback_ledger': ledger, 'fixed_runtime_members': 88,
    'prior_full_get_claims_revalidated': 13, 'new_members': 75,
    'unique_blob_count': len({x['git_blob'] for x in rows}),
    'maximum_leaf_bytes': max(x['bytes'] for x in rows), 'leaf_cap_bytes': 512000,
    'supervisor': {'state': 'failed', 'exit_code': 1, 'timed_out': False},
    'original_wrapper_status': 'failed', 'driver_main_entered': False,
    'source_gates_started': 0, 'native_fourteen_phases_started': False,
    'qualified': False,
    'primary_error_scope': 'FileNotFoundError for the fixed historical materialization RESULT path. The cause of current unavailability is not established.',
    'secondary_error_scope': 'Original SourceChanged preserved; complete retained control flow shows the initial Git baseline was not assigned. The actual final raw Git state is byte-equal to the canonical endpoint.',
    'transport_observations': {'native_binary_read_calls': 38, 'successful_chunks': 37,
                               'original_connection_closed_255_errors': 1,
                               'same_file_first_successful_version_then_bound_tail_reconciled': True,
                               'complete_original_native_file_paths': 30,
                               'stream_bytes': {'stdout': 838, 'stderr': 0}},
    'archive_publication_errors': 0,
    'no_original_source_or_index_or_ref_repair': True,
    'no_historical_materialization_path_probe': True,
    'no_second_main': True,
    'full_physical_inventory_or_runtime_environment_not_reached': True,
    'follow_on_execution_authorized_by_this_record': False})
print(json.dumps({'ledger': ledger, 'review': review}, sort_keys=True))
