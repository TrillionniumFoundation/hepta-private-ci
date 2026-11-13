from pathlib import Path
import hashlib
import json


BASE = Path(__file__).resolve().parent
OUT = BASE / 'archive-status-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    path = OUT / name
    with path.open('xb') as stream:
        stream.write(raw)
    return {'name': name, **identity(raw)}


def main():
    frozen = BASE / 'review-candidate-v1'
    execution = BASE / 'execution-candidate-v1'
    fixed = json.loads((frozen / 'MANIFEST.json').read_bytes())
    candidate = json.loads((execution / 'MANIFEST.json').read_bytes())
    files = [(frozen / row['name'], row) for row in fixed['files']]
    assert len(files) == 59
    files += [(frozen / 'MANIFEST.json', identity((frozen / 'MANIFEST.json').read_bytes()))]
    files += [(execution / row['name'], row) for row in candidate['files']]
    files += [(execution / 'MANIFEST.json', identity((execution / 'MANIFEST.json').read_bytes()))]
    for path in [BASE / 'pure-dataflow-v1/REVIEW.json', BASE / 'pure-dataflow-v1/verify_transport_pure_v1.py',
                 OUT / 'LOCAL_ARCHIVE_ERROR_AND_RECONCILIATION_PLAN.json']:
        files.append((path, identity(path.read_bytes())))
    assert len(files) == 70 and len({str(path) for path, _ in files}) == 70
    rows = []
    for path, expected in files:
        raw = path.read_bytes()
        pin = identity(raw)
        assert pin == {key: expected[key] for key in pin}
        assert pin['bytes'] <= 512000
        local_ledger = json.loads(Path(str(path) + '.PUBLISH_LEDGER_ENTRY.json').read_bytes())
        assert all(local_ledger[key] == pin[key] for key in pin)
        assert local_ledger['actual_full_get_equal'] is True
        get_path = Path(str(path) + '.PUBLISH_GET.original.json')
        if not get_path.exists():
            get_path = Path(str(path) + '.PUBLISH_RECONCILE_GET.original.json')
        get_raw = get_path.read_bytes()
        get = json.loads(get_raw)
        assert not get.get('isError') and get['structuredContent']['content'].encode() == raw
        create_path = Path(str(path) + '.PUBLISH_CREATE.original.json')
        create_pin = None
        if create_path.exists():
            create_raw = create_path.read_bytes()
            create = json.loads(create_raw)
            assert not create.get('isError') and create['structuredContent']['sha'] == pin['git_blob']
            create_pin = {'local_path': str(create_path), **identity(create_raw)}
        else:
            assert path.name in ('PART_001.b64', 'PART_002.b64') and path.parent == frozen / 'parts'
            assert local_ledger['original_create_response_retained'] is False
        rows.append({'path': str(path).removeprefix('/tmp/hepta-36fa-'), 'local_path': str(path),
                     **pin, 'actual_full_GET_equal': True,
                     'actual_create_response_verified': create_pin is not None,
                     'create_response': create_pin,
                     'create_response_status': 'verified' if create_pin is not None else 'Unknown_not_retained',
                     'complete_GET_response': {'local_path': str(get_path), **identity(get_raw)}})
    assert sum(row['actual_create_response_verified'] for row in rows) == 68
    ledger = {'format': 'hepta-transported-original-primary-full-get-ledger-v1',
              'not_an_execution_approval': True, 'H_calls': 0,
              'primary_payload_count': 70, 'immutable_HOLD_payload_count': 59,
              'all_payloads_actual_full_GET_equal': True,
              'verified_create_response_count': 68, 'create_response_not_retained_count': 2,
              'unretained_create_responses_are_not_reconstructed': True,
              'source_request': None, 'native_request': None,
              'historical_data_original_paths_remain_unmodified': True,
              'rows': rows}
    ledger_row = save('COMPLETE_PRIMARY_FULL_GET_LEDGER.json', ledger)
    review = {'format': 'hepta-transported-original-primary-archive-completion-v1',
              'not_an_execution_approval': True, 'H_calls': 0,
              'closed_HOLD_manifest': identity((frozen / 'MANIFEST.json').read_bytes()),
              'immutable_HOLD_payloads': 59, 'immutable_HOLD_full_GET_equal': 59,
              'execution_candidate_manifest': identity((execution / 'MANIFEST.json').read_bytes()),
              'execution_candidate_files_with_manifest': 7,
              'separate_pure_dataflow_files': 2, 'archive_error_observations': 1,
              'primary_files_including_two_manifests': 70,
              'all_primary_files_actual_complete_Git_GET_equal': True,
              'verified_create_response_count': 68, 'create_response_not_retained_count': 2,
              'unretained_create_names': ['review-candidate-v1/parts/PART_001.b64',
                                         'review-candidate-v1/parts/PART_002.b64'],
              'unretained_create_scope': 'Local archive saver rejected a relative path after the create API returned. Original create response statuses remain Unknown; subsequent complete GET responses are retained and equal to the exact frozen bytes.',
              'leaf_limit_bytes': 512000, 'largest_primary_payload': max(row['bytes'] for row in rows),
              'raw_packet_or_gzip_uploaded_as_an_oversized_leaf': False,
              'large_packet_representation': fixed['large_packet_representation'],
              'all_four_actual_staging_fields_null': candidate['actual_stage_fields'],
              'source_request': None, 'native_request': None, 'qualification': False,
              'source_tree_commit_refs_modified': False,
              'complete_ledger': ledger_row,
              'success_GET_SDK_wrappers': 'Retained locally and fully revalidated here. Any oversized wrappers require a separate bounded archival representation; they are not falsely listed as published primary leaves.'}
    review_row = save('ARCHIVE_COMPLETION_REVIEW.json', review)
    script = OUT / 'verify_primary_archive.py'
    with script.open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print(json.dumps({'ledger': ledger_row, 'review': review_row,
                      'script': identity(script.read_bytes()), 'H_calls': 0,
                      'primary_full_GET_equal': len(rows)}, sort_keys=True))


if __name__ == '__main__':
    main()
