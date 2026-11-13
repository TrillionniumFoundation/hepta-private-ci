#!/usr/bin/env python3
"""Assemble bounded new evidence entries without changing any published object."""
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


base_bytes = (ROOT / 'PUBLISHED_0E5A50_FILE_MAP.json').read_bytes()
assert identity(base_bytes)['git_blob'] == '4ce42e647327fa2810bcddde3d815f2fb354c99f'
base = json.loads(base_bytes)
stage1 = json.loads((ROOT / 'POST_0E5_VERIFIED_ADDITIONS_STAGE1.json').read_bytes())
excluded = 'post-0e5-publication-readback-v1/FULL_PUBLISHED_FILE_MAP.json'
entries = {}
sources = []


def add(row, provenance):
    path = row['path']
    assert path and not path.startswith('/') and '..' not in PurePosixPath(path).parts, path
    assert row.get('mode', '100644') == '100644', path
    candidates = [row[k] for k in ('git_blob', 'sha', 'blob') if k in row]
    assert candidates and all(s == candidates[0] for s in candidates), path
    sha = candidates[0]
    assert isinstance(sha, str) and len(sha) == 40, path
    assert row['bytes'] <= 512000, (path, row['bytes'])
    normalized = {'path': path, 'git_blob': sha, 'bytes': row['bytes'],
                  'sha256': row['sha256'], 'mode': '100644'}
    if path in base:
        assert base[path] == sha, ('published path would change', path)
        return
    if path in entries:
        assert all(entries[path][k] == normalized[k] for k in normalized), path
        entries[path]['provenance'].append(provenance)
    else:
        entries[path] = dict(normalized, provenance=[provenance])


for row in stage1['entries']:
    if row['path'] == excluded:
        assert row['git_blob'] == '4ce42e647327fa2810bcddde3d815f2fb354c99f' and row['bytes'] == 572255
        continue
    add(row, 'verified-stage1:43afb5a85e12942c68e4c71966826e9b72a2ce04')

for path in sorted((ROOT / 'next-checkpoint-placements').glob('*.json')):
    raw = path.read_bytes()
    meta = identity(raw)
    packet = json.loads(raw)
    prefix = packet.get('prefix')
    assert isinstance(packet['entries'], list), str(path)
    for item in packet['entries']:
        row = dict(item)
        if prefix and not row['path'].startswith(prefix + '/'):
            row['path'] = prefix + '/' + row['path']
        add(row, meta['git_blob'])
    all_present_sha = set(base.values()) | {r['git_blob'] for r in entries.values()}
    if meta['git_blob'] not in all_present_sha:
        add(dict(meta, path='post-0e5-checkpoint-v3/placements/' + path.name), 'exact retained placement')
    sources.append({'name': path.name, **meta, 'member_entries': len(packet['entries'])})

result = {
    'format': 'hepta-post-0e5-bounded-checkpoint-pending-entries-v2',
    'parent_commit': '0e5a50fc4f7f26b4120c0837902cb5d046d3f58e',
    'parent_file_map': '4ce42e647327fa2810bcddde3d815f2fb354c99f',
    'parent_file_count': len(base),
    'entries': [entries[k] for k in sorted(entries)],
    'placement_inputs': sources,
    'stage1_packaging_correction': {
        'omitted_proposed_leaf': excluded,
        'raw_identity_unchanged': '4ce42e647327fa2810bcddde3d815f2fb354c99f',
        'replacement_prefix': 'post-0e5-publication-readback-v1/bounded-published-file-map',
        'reason': 'The original 512000-byte blob policy applies to new evidence paths. Retain complete original bytes through lossless gzip/base64 with explicit reconstruction identities; no exception or truncation.'
    },
    'original_blob_policy_script': '18bc6175c274abaeabe3ef0c32d82627d498bbe7',
    'original_blob_policy_workflow': 'd870b6f9c1e025aff458c32f0461c752fcd2f0b3',
    'maximum_new_blob_bytes': max(r['bytes'] for r in entries.values()),
    'all_new_entries_at_most_512000': True,
    'published_paths_overwritten_here': [],
    'readme_and_final_manifest_not_yet_included': True,
    'git_tree_or_ref_mutations': False,
    'qualification': False,
}
(ROOT / 'POST_0E5_PENDING_ADDITIONS_STAGE3.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'entries': len(entries), 'unique_blobs': len({r['git_blob'] for r in entries.values()}),
                  'placements': len(sources), 'maximum_new_blob_bytes': result['maximum_new_blob_bytes'],
                  'plan': identity((ROOT / 'POST_0E5_PENDING_ADDITIONS_STAGE3.json').read_bytes())}))
