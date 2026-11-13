"""Verify immutable saved original readbacks and freeze an append-only file map."""
from pathlib import Path
import base64
import datetime
import gzip
import hashlib
import importlib.util
import json

OUT = Path('/tmp/hepta-36fa-post3454-evidence-preparation-v1')
spec = importlib.util.spec_from_file_location('frozen_selection', OUT / 'prepare_frozen_increment.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def write_new(path, value):
    with path.open('xb') as f:
        f.write(m.jb(value))


def main():
    rows = json.loads((OUT / 'SELECTED_ROWS.json').read_bytes())
    base = json.loads((OUT / 'BASE_3454_FILEMAP.json').read_bytes())
    assert len(rows) == 169 and len(base) == 3454
    verified = []
    proof_counts = {'current_root_complete_sdk': 0, 'previous_complete_sdk': 0, 'same_blob_in_verified_base': 0}
    for row in rows:
        raw = Path(row['frozen_local']).read_bytes()
        assert m.pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
        content = raw.decode('utf-8')
        current = OUT / 'git-readbacks' / (row['git_blob'] + '.json')
        if current.exists():
            sdk = json.loads(current.read_bytes())
            assert sdk['expected']['git_blob'] == row['git_blob']
            assert sdk['fetch']['isError'] is False
            returned = sdk['fetch']['structuredContent']['content']
            assert returned == content
            if sdk.get('create') is not None:
                assert sdk['create']['isError'] is False and sdk['create']['structuredContent']['sha'] == row['git_blob']
            nested = sdk['fetch']['structuredContent'].get('structuredContent', {}).get('content')
            if nested is not None:
                assert nested == content
            basis = 'current_root_complete_sdk'
            observations = [str(current)]
        elif row['verified_original_git_readbacks']:
            observations = row['verified_original_git_readbacks']
            assert all(any(value == content for value in m.fetched_contents(json.loads(Path(p).read_bytes()))) for p in observations)
            basis = 'previous_complete_sdk'
        else:
            assert row['same_blob_in_prior_verified_map'] and row['git_blob'] in base.values()
            observations = ['/tmp/hepta-36fa-post3328-evidence-preparation-v1/FULL_FILEMAP.json']
            basis = 'same_blob_in_verified_base'
        proof_counts[basis] += 1
        assert row['path'] not in base
        verified.append({**row, 'full_readback_equal': True, 'verification_basis': basis, 'actual_readback_records': observations})

    transport = [r for r in rows if r['kind'] == 'lossless_transport_manifest']
    assert len(transport) == 1
    manifest = json.loads(Path(transport[0]['frozen_local']).read_bytes())
    joined = b''
    for part in manifest['parts']:
        encoded = (OUT / 'frozen' / part['path']).read_bytes()
        assert m.pin(encoded) == part['encoded']
        decoded = base64.b64decode(encoded.strip(), validate=True)
        assert m.pin(decoded) == part['decoded'] and len(joined) == part['offset']
        joined += decoded
    assert m.pin(joined) == manifest['gzip']
    raw = gzip.decompress(joined)
    assert m.pin(raw) == manifest['raw']
    assert manifest['raw']['sha256'] == '6c28a1e1291c9c96879718e6c1b81028f9fa12c9ba358123090852d5b6e72b8f'
    assert manifest['gzip']['sha256'] == '780933b23d9d2d3c792b7eb753544056c8ac4e72e07003b2c58932d0ba671282'
    observed = json.loads(Path('/tmp/hepta-36fa-native-precondition-snapshot-diagnostic-v1/STDOUT.complete.log').read_bytes())
    assert manifest['raw'] == observed['actual_native_identity']
    assert manifest['gzip'] == next(r['identity'] for r in observed['observations'] if r['label'] == 'native_gzip')

    incremental = {r['path']: r['git_blob'] for r in verified}
    full = {**base, **incremental}
    assert len(full) == 3623 and all(full[p] == value for p, value in base.items())
    write_new(OUT / 'VERIFIED_INCREMENTAL_ENTRIES.json', verified)
    write_new(OUT / 'INCREMENTAL_FILEMAP.json', incremental)
    write_new(OUT / 'FULL_FILEMAP.json', full)
    report = {'format': 'hepta-post3454-verified-append-only-window-v1',
              'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'status': 'COMPLETE_IMMUTABLE_GIT_READBACK_REVIEW_NO_REF_PUBLICATION',
              'base_count': 3454, 'new_paths': 169, 'merged_count': 3623,
              'old_paths_changed': [], 'old_readme_unchanged': True,
              'proof_counts': proof_counts,
              'largest_payload_bytes': max(r['bytes'] for r in rows),
              'complete_failed_native_snapshot_transport_verified': True,
              'new_source_or_native_execution_inferred': False,
              'local_save_error_preserved': '/tmp/hepta-36fa-post3454-evidence-preparation-v1/LOCAL_READBACK_SAVE_FIRST_ERROR.json',
              'source_gates': 'Three actual source gates passed and originals reviewed; no hosted CI or native behavioral pass inferred.',
              'native_first_attempt': 'Precondition failed, zero behavior stages, unknown_missing_before retained.',
              'provider': 'Source-only v1 proposal and bounded independent static review. New v2 work excluded.',
              'real_task_chains': 0,
              'filemaps': {name: m.pin((OUT / name).read_bytes()) for name in ['VERIFIED_INCREMENTAL_ENTRIES.json', 'INCREMENTAL_FILEMAP.json', 'FULL_FILEMAP.json']},
              'sidecars_not_self_included': True,
              'source_H_refs_or_PR_mutations': False}
    write_new(OUT / 'MANIFEST.json', report)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
