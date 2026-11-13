#!/usr/bin/env python3
"""Freeze the explicit already-published preparation set, not future runtime files."""
import hashlib
import json
from pathlib import Path

BASE = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def write(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    path = BASE / name
    if path.exists():
        assert path.read_bytes() == raw
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'name': name, 'path': str(path), **pin(raw)}


def main():
    entries = []
    sdk_rows = []
    for directory in (BASE, BASE / 'execution-candidate-v1', BASE / 'original-9101-readback-encoded-v1'):
        for ledger in sorted(directory.glob('*.PUBLISH_LEDGER_ENTRY.json')):
            row = json.loads(ledger.read_bytes())
            if row['name'] in {'PREPARATION_MANIFEST.json', 'PLACEMENT.json', 'CLOSED_GIT_SDK_ARCHIVE_INPUTS.json'}:
                continue
            raw = Path(row['path']).read_bytes()
            assert pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
            assert len(raw) <= 512000
            responses = {}
            for operation in ('CREATE', 'GET'):
                name = row['name'] + '.PUBLISH_' + operation + '.original.json'
                path = directory / name
                sdk_raw = path.read_bytes()
                assert len(sdk_raw) <= 512000
                response = json.loads(sdk_raw)
                assert not response.get('isError', False)
                if operation == 'CREATE':
                    assert response['structuredContent']['sha'] == row['git_blob']
                else:
                    assert response['structuredContent']['content'].encode() == raw
                item = {'path': str(path),
                        'evidence_path': str(path.relative_to(BASE.parent)).removeprefix('hepta-36fa-'),
                        **pin(sdk_raw), 'source_artifact_git_blob': row['git_blob'],
                        'operation': operation,
                        'sdk_git_publication_in_this_manifest': False}
                responses[operation.lower()] = item
                sdk_rows.append(item)
            entries.append({**row, 'saved_original_git_responses': responses})
    assert len({e['evidence_path'] for e in entries}) == len(entries)
    scope = {'format': 'hepta-prepared-fix101-apply-format-package-v1',
             'status': 'HOLD_ROOT_EXACT_REQUEST_APPROVAL_REQUIRED',
             'native_execution_count_under_this_package': 0,
             'prior_failed_fix_reclassified': False,
             'known_request_git_blob': 'b63bd0d12684a3ba39e63f1f12fef56cb56cb3d9',
             'no_future_runtime_files_included': True,
             'entry_count': len(entries), 'entries': entries,
             'verification': 'Each primary artifact was actually Git-created and fully GET-read. This seal rechecks the saved original response content against exact local bytes.',
             'large_original_ancestor_request': '60e6b8d8b12523318410b8f60d7626a7fdc1643e',
             'large_original_representation_manifest': 'd736206a7b5895eb82f1e3492b8895da7984a17e',
             'leaf_byte_cap': 512000}
    archive = {'format': 'hepta-fixed-original-git-sdk-archive-inputs-v1',
               'status': 'FIXED_LOCAL_ORIGINALS_READY_FOR_SEPARATE_GIT_ARCHIVAL',
               'entry_count': len(sdk_rows), 'entries': sdk_rows,
               'scope': 'Only the explicit current preparation publication responses; not a recursive scan and not native observations.',
               'capture_files_unchanged': True, 'future_responses_excluded': True,
               'maximum_leaf_bytes': max(x['bytes'] for x in sdk_rows)}
    a = write('CLOSED_GIT_SDK_ARCHIVE_INPUTS.json', archive)
    b = write('PREPARATION_MANIFEST.json', scope)
    print(json.dumps({'primary_count': len(entries), 'sdk_count': len(sdk_rows), 'outputs': [a, b]}))


if __name__ == '__main__':
    main()
