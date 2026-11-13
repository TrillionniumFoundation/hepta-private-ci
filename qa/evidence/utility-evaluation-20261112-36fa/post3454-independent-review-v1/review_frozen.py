#!/usr/bin/env python3
"""Offline verification of frozen evidence bytes. No native/source/Git actions."""
from pathlib import Path, PurePosixPath
import base64
import collections
import gzip
import hashlib
import json

BASE = Path('/tmp/hepta-36fa-post3454-evidence-preparation-v1')
OUT = Path(__file__).resolve().parent


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def strings(value, path=()):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, path + (index,))


def read_json(path):
    return json.loads(Path(path).read_bytes())


def main():
    names = ['BASE_3454_FILEMAP.json', 'SELECTED_ROWS.json', 'PENDING_GIT_READBACK.json',
             'SELECTION_REVIEW.json', 'LOCAL_READBACK_SAVE_FIRST_ERROR.json']
    inputs = {name: pin((BASE / name).read_bytes()) for name in names}
    base = read_json(BASE / names[0])
    rows = read_json(BASE / names[1])
    pending = read_json(BASE / names[2])
    selection = read_json(BASE / names[3])
    assert len(base) == 3454 and len(rows) == 169 and len(pending) == 71
    assert inputs[names[0]] == selection['base_map']
    assert inputs[names[0]]['git_blob'] == '5dd29e2d74cf849728aa0e1ca0fdb6d7eba669c6'
    assert inputs[names[1]]['sha256'] == 'e67349a9f9cd419688842b356866abf401b4a8e3a42af16ffc92af8069f62576'
    by_sha = collections.defaultdict(list)
    selected = {}
    for row in rows:
        relative = PurePosixPath(row['path'])
        assert not relative.is_absolute() and all(x not in ('', '.', '..') for x in relative.parts)
        assert row['path'] not in base and row['path'] not in selected
        body = Path(row['frozen_local']).read_bytes()
        assert pin(body) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
        assert len(body) < 500000
        selected[row['path']] = row['git_blob']
        by_sha[row['git_blob']].append(row)
    assert len(selected) == 169 and len(by_sha) == 167
    duplicates = selection['duplicates_already_exactly_preserved']
    assert len(duplicates) == 63
    for row in duplicates:
        assert base[row['path']] == row['git_blob']
        assert pin(Path(row['origin']).read_bytes()) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
    sdk_review = []
    fresh_sha = set()
    for path in sorted((BASE / 'git-readbacks').glob('*.json')):
        value = read_json(path)
        expected = by_sha[path.stem][0]
        body = Path(expected['frozen_local']).read_bytes()
        fetch = value['fetch']
        assert fetch['isError'] is False
        assert value['full_content_identity_equal'] is True
        for key in ('bytes', 'sha256', 'git_blob'):
            assert value['expected'][key] == expected[key]
        content_paths = [(q, s) for q, s in strings(fetch) if q and q[-1] == 'content']
        assert len(content_paths) == 2 and all(s.encode('utf-8') == body for q, s in content_paths)
        observed_paths = {q for q, s in content_paths}
        declared_paths = value.get('matched_payload_paths')
        if declared_paths is not None:
            assert {tuple(q) for q in declared_paths} == observed_paths
        urls = [s for q, s in strings(fetch) if q and q[-1] in ('url', 'display_url')]
        assert urls and all(s == 'https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/' + path.stem for s in urls)
        fresh_sha.add(path.stem)
        sdk_review.append({'path': str(path), **pin(path.read_bytes()), 'payload_blob': path.stem,
                           'both_complete_content_fields_equal': True,
                           'observed_payload_paths': [list(q) for q in sorted(observed_paths)],
                           'declared_payload_paths_present': declared_paths is not None})
    assert len(fresh_sha) == 71 and fresh_sha == {row['git_blob'] for row in pending}
    row_evidence = []
    counts = collections.Counter()
    for row in rows:
        body = Path(row['frozen_local']).read_bytes()
        if row['git_blob'] in fresh_sha:
            kind = 'complete_new_GET_SDK'
            proof = [str(BASE / 'git-readbacks' / (row['git_blob'] + '.json'))]
        else:
            proof = []
            for source in row['verified_original_git_readbacks']:
                value = read_json(source)
                found = [q for q, s in strings(value)
                         if any(k in q for k in ('fetch', 'read', 'readback')) and s.encode('utf-8') == body]
                if found:
                    proof.append({'path': source, **pin(Path(source).read_bytes()), 'complete_payload_paths': [list(q) for q in found]})
            if proof:
                kind = 'complete_previous_GET_SDK'
            else:
                assert row['git_blob'] in set(base.values())
                kind = 'identical_blob_already_in_verified_base'
                proof = [path for path, value in base.items() if value == row['git_blob']]
        counts[kind] += 1
        row_evidence.append({'path': row['path'], 'git_blob': row['git_blob'], 'proof_kind': kind, 'proof': proof})
    assert sum(counts.values()) == 169
    relative = Path('native-cc57-precondition-readonly-diagnostic-v1')
    manifest_path = BASE / 'frozen' / relative / 'source-after.files.EXACT_RECOVERED.json.transport-manifest.json'
    transport = read_json(manifest_path)
    assert len(transport['parts']) == 5
    blocks = []
    for part in transport['parts']:
        body = (BASE / 'frozen' / part['path']).read_bytes()
        assert pin(body) == part['encoded']
        decoded = base64.b64decode(body.strip(), validate=True)
        assert pin(decoded) == part['decoded']
        assert part['offset'] == sum(map(len, blocks))
        blocks.append(decoded)
    packed = b''.join(blocks)
    raw = gzip.decompress(packed)
    assert pin(packed) == transport['gzip'] and pin(raw) == transport['raw']
    assert hashlib.sha256(raw).hexdigest() == '6c28a1e1291c9c96879718e6c1b81028f9fa12c9ba358123090852d5b6e72b8f'
    recovered = json.loads(raw)
    assert len(recovered) == 15188
    actual_diff = read_json(BASE / 'frozen' / relative / 'SNAPSHOT_DIFF.original.json')
    missing = {row['path']: row for row in recovered if row.get('missing') is True}
    assert len(missing) == 7 and missing == {row['path']: row['after'] for row in actual_diff}
    canonical_path = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
    canonical_raw = canonical_path.read_bytes()
    assert hashlib.sha256(canonical_raw).hexdigest() == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
    canonical = json.loads(canonical_raw)
    original_projection = {row['path']: {'path': row['path'], 'mode': row['index_mode'],
                           'bytes': row['bytes'], 'sha256': row['sha256'], 'blob': row['working_blob']}
                           for row in canonical['files']}
    equal_rows = 0
    for row in recovered:
        if row['path'] in missing:
            continue
        assert row == original_projection[row['path']]
        equal_rows += 1
    assert equal_rows == 15181
    for row in actual_diff:
        assert row['before'] == original_projection[row['path']]
    actual_snapshot = read_json(BASE / 'frozen/native-cc57-v1-failed-precondition/source-after.json')
    assert actual_snapshot['inventory_sha256'] == transport['raw']['sha256']
    recovery = read_json(BASE / 'frozen' / relative / 'EXACT_ORIGINAL_SNAPSHOT_RECOVERY.json')
    assert recovery['raw'] == transport['raw'] and recovery['gzip'] == transport['gzip']
    assert recovery['source_writes'] is False and recovery['tests_run'] is False
    failure = read_json(BASE / 'LOCAL_READBACK_SAVE_FIRST_ERROR.json')
    assert failure['Git_fetch_completed_before_save_error'] is True and failure['local_output_file_created'] is False
    assert failure['native_calls'] == 0 and failure['test_changes'] is False
    merged = dict(base)
    merged.update(selected)
    assert len(merged) == 3623 and all(merged[k] == v for k, v in base.items())
    assert selection['old_paths_changed'] == [] and selection['old_readme_unchanged'] is True
    detail = {'new_GET_SDKs': sdk_review, 'row_evidence': row_evidence}
    detail_raw = (json.dumps(detail, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    with (OUT / 'BYTE_REVIEW.json').open('xb') as stream:
        stream.write(detail_raw)
    report = {
        'format': 'hepta-post3454-frozen-increment-independent-review-v1',
        'status': 'FROZEN_BYTES_AND_READBACK_PROOFS_CONSISTENT',
        'inputs': inputs,
        'frozen_at_utc_from_selection': selection['frozen_at_utc'],
        'base_paths_preserved': 3454, 'new_paths': 169, 'new_unique_blobs': 167,
        'already_preserved_same_path_same_blob': 63, 'base_paths_changed': 0,
        'merged_pre_publication_metadata_path_count': 3623,
        'not_a_final_published_tree_or_count': True,
        'all_new_frozen_payload_size_sha256_git_sha_match': True,
        'all_new_evidence_payloads_below_500000_bytes': True,
        'fresh_GET_unique_blobs': 71, 'fresh_GET_complete_payload_fields_verified': 142,
        'fresh_GET_SDks_without_declared_paths_but_two_full_fields_present': sum(not row['declared_payload_paths_present'] for row in sdk_review),
        'proof_coverage_by_selected_path': dict(counts),
        'path_order_in_matched_payload_paths_has_no_semantic_effect': True,
        'historical_pending_flags_preserved': {'selected_true': 98, 'selected_false': 71, 'pending_rows': 71},
        'readback_note': 'The frozen pending flags record their original selection time. The 71 complete later GET SDKs close that evidence gap without rewriting the selection. One new GET blob also covers an additional identical selected payload path.',
        'snapshot_transport': {'manifest': pin(manifest_path.read_bytes()), 'parts': 5,
                               'gzip': pin(packed), 'raw': pin(raw), 'rows': 15188,
                               'rows_equal_to_original_full_inventory_projection': 15181,
                               'missing_rows_exactly_equal_to_original_diff': 7,
                               'scope': 'Lossless recovery of the already observed 1cd4 snapshot; neither new physical-source observation nor another native run.'},
        'local_readback_save_failure': {'identity': inputs['LOCAL_READBACK_SAVE_FIRST_ERROR.json'],
                                      'included_in_selected_169': False,
                                      'classification': 'Local oversized-shell-argument save failure after completed Git GET; not an H/source/gate failure.',
                                      'publication_note': 'Preserve this frozen outer sidecar when Root assembles checkpoint metadata; do not rewrite older cutoff records.'},
        'semantic_boundaries_preserved': [
            '1cb4 three original source gates passed only for their actual scope.',
            '1cd4 failed precondition with zero behavioral stages; unknown_missing_before remains.',
            '1ce4 proves recorded seven missing archive rows, not who changed them.',
            'Provider v1 remains an uncompiled, ungated, unactivated isolated proposal.',
            'No real qualified task chain or independent real B result is manufactured by evidence review.',
        ],
        'details': pin(detail_raw),
        'H_calls': 0, 'tests_or_original_main_executed': False,
        'existing_frozen_files_modified': False, 'source_index_refs_modified': False,
        'blocking_gaps': [],
    }
    report_raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    with (OUT / 'REVIEW.json').open('xb') as stream:
        stream.write(report_raw)
    print(json.dumps({'report': pin(report_raw), 'details': pin(detail_raw), 'proof_counts': dict(counts)}, sort_keys=True))


if __name__ == '__main__':
    main()
