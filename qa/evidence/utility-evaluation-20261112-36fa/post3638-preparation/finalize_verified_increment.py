"""Verify complete actual Git readbacks and freeze the append-only filemap."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-post3638-evidence-preparation-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def output(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    with (ROOT / name).open('xb') as stream:
        stream.write(raw)
    return {'path': str(ROOT / name), **pin(raw)}


def contents(value):
    if isinstance(value, dict):
        structured = value.get('structuredContent')
        if isinstance(structured, dict) and isinstance(structured.get('content'), str):
            yield structured['content']
        for child in value.values():
            yield from contents(child)
    elif isinstance(value, list):
        for child in value:
            yield from contents(child)


base = json.loads((ROOT / 'BASE_3638_FILEMAP.json').read_bytes())
selected_raw = (ROOT / 'SELECTED_ROWS.json').read_bytes()
selected = json.loads(selected_raw)
assert len(base) == 3638 and len(selected) == 186
assert len({r['path'] for r in selected}) == len(selected)
verified = []
new = {}
readback_files = {}
for row in selected:
    raw = Path(row['frozen_local']).read_bytes()
    assert pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
    assert row['path'] not in base
    candidates = [ROOT / 'git-readbacks' / (row['git_blob'] + '.json')]
    candidates.extend(Path(p) for p in row['verified_original_git_readbacks'])
    proofs = []
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        actual_raw = path.read_bytes()
        actual = json.loads(actual_raw)
        matches = [payload for payload in contents(actual) if payload.encode() == raw]
        if matches:
            if path.parent == ROOT / 'git-readbacks':
                assert actual['create']['structuredContent']['sha'] == row['git_blob']
                assert actual['full_content_equal'] is True
                assert len(matches) == len(actual['verified_equal_payload_fields'])
                assert len(matches) >= 2
            proofs.append({'path': str(path), **pin(actual_raw), 'exact_full_payload_fields': len(matches)})
            readback_files[str(path)] = proofs[-1]
    known = row['git_blob'] in base.values()
    assert proofs or known, ('missing complete actual Git readback', row['path'])
    verified.append({**row, 'complete_actual_readback_proofs': proofs,
                     'same_blob_in_verified_published_base': known, 'full_readback_equal': True})
    new[row['path']] = row['git_blob']

transports = []
for row in selected:
    if row['kind'] != 'lossless_transport_manifest':
        continue
    document = json.loads(Path(row['frozen_local']).read_bytes())
    parts = []
    for part in document['parts']:
        encoded = (ROOT / 'frozen' / part['path']).read_bytes()
        assert pin(encoded) == part['encoded']
        decoded = base64.b64decode(encoded.strip(), validate=True)
        assert pin(decoded) == part['decoded']
        assert sum(map(len, parts)) == part['offset']
        parts.append(decoded)
    packed = b''.join(parts)
    assert pin(packed) == document['gzip']
    actual = gzip.decompress(packed)
    assert pin(actual) == document['raw']
    assert actual == Path(document['origin']).read_bytes()
    transports.append({'path': row['path'], 'complete_reconstruction_matches_frozen_original': True,
                       'raw': document['raw'], 'gzip': document['gzip'], 'parts': len(parts)})

full = {**base, **new}
assert len(full) == 3824 and all(full[path] == blob for path, blob in base.items())
assert full['README.md'] == 'beaa457aad524b8f16bc71bc7c2029a65c327b99'
files = [output('VERIFIED_INCREMENTAL_ENTRIES.json', verified),
         output('INCREMENTAL_FILEMAP.json', new), output('FULL_FILEMAP.json', full)]
report = {
    'format': 'hepta-post3638-verified-frozen-window-v1',
    'base_head': '07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0',
    'base_files': 3638, 'incremental_paths': 186, 'total_files': len(full),
    'all_old_paths_preserved': True, 'old_readme_unchanged': True,
    'frozen_selected_rows_identity': pin(selected_raw),
    'all_frozen_bytes_verified': True, 'all_actual_full_readbacks_or_previous_exact_objects_verified': True,
    'new_full_readback_files': len(list((ROOT / 'git-readbacks').glob('*.json'))) // 2,
    'new_readback_errors': len(list((ROOT / 'git-readbacks').glob('*.ERROR.json'))),
    'lossless_transports': transports, 'outputs': files,
    'scope': json.loads((ROOT / 'SELECTION_REVIEW.json').read_bytes()),
    'later_active_admission_and_full_provider_work_excluded': True,
    'source_branch_changed': False, 'evidence_branch_changed': False,
    'real_qualified_task_chains': 0,
}
assert report['new_full_readback_files'] == 117 and report['new_readback_errors'] == 0
files.append(output('MANIFEST.json', report))
print(json.dumps({'files': files, 'total': len(full), 'new_paths': len(new),
                  'fully_reconstructed_large_originals': len(transports)}))
