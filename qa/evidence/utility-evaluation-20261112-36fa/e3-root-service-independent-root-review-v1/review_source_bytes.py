"""Pure independent byte/composition review, with no Rust/project execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
LAYER = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/root-service-layer-v1')
E1 = Path('/tmp/hepta-36fa-e1-source-candidate-v1/after')
E2 = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/factory-split-layer-v1')
OUT = Path('/tmp/hepta-36fa-e3-root-service-independent-root-review-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


graph_raw = (ROOT / 'PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(graph_raw)['git_blob'] == '7c515dbe48ae3ab42ccc85d916e38675db06ced2'
graph = {row['path']: row for row in json.loads(graph_raw)['files']}
raw = (LAYER / 'SOURCE_PACKET.json').read_bytes()
assert pin(raw) == {'bytes': 249900, 'sha256': 'b2f1b2aa681cea702b14ebb7ec0095d93b4896969013ca9280247dde4d306d4c', 'git_blob': '0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b'}
packet = json.loads(raw)
assert packet['base_commit'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert packet['base_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
splices = json.loads((LAYER / 'EXACT_MOUNT_SPLICES.json').read_bytes())
factory = {row['path']: row for row in json.loads((E2 / 'SOURCE_PACKET.json').read_bytes())['entries']}
assert len(packet['entries']) == 7 and len(splices) == 4
results = []
new = modified = 0
for row in packet['entries']:
    path = row['path']
    assert pin(row['after_utf8'].encode()) == row['after']
    mounts = [s for s in splices if s['path'] == path]
    if row['before'] is None:
        assert path not in graph and not mounts and row['before_utf8'] is None
        new += 1
        results.append({'path': path, 'new': True, 'after': row['after']})
        continue
    before = row['before_utf8']
    assert pin(before.encode()) == row['before']
    assert row['before'] == {key: graph[path][key] for key in ('bytes', 'sha256', 'git_blob')}
    assert mounts
    current = before
    for splice in mounts:
        anchor = splice['anchor']
        assert current.count(anchor) == 1
        if 'insert_before' in splice:
            current = current.replace(anchor, splice['insert_before'] + anchor)
        else:
            current = current.replace(anchor, anchor + splice['insert_after'])
    assert current == row['after_utf8']
    inverse = current
    for splice in reversed(mounts):
        anchor = splice['anchor']
        whole = splice.get('insert_before', '') + anchor + splice.get('insert_after', '')
        assert inverse.count(whole) == 1
        inverse = inverse.replace(whole, anchor)
    assert inverse == before
    # Compose only in memory against the frozen E1 candidate and E2 factory
    # layer. This is not the unfinished actual IPC layer or a source write.
    base = (E1 / path).read_text() if (E1 / path).exists() else before
    base_origin = 'E1-99fada' if (E1 / path).exists() else 'b608'
    if path in factory:
        assert pin(base.encode()) == factory[path]['before']
        base = factory[path]['after_utf8']
        base_origin += '+E2-factory-62ad5a5'
    composed = base
    for splice in mounts:
        anchor = splice['anchor']
        assert composed.count(anchor) == 1
        composed = composed.replace(anchor, splice.get('insert_before', '') + anchor + splice.get('insert_after', ''))
    inverted = composed
    for splice in reversed(mounts):
        anchor = splice['anchor']
        whole = splice.get('insert_before', '') + anchor + splice.get('insert_after', '')
        assert inverted.count(whole) == 1
        inverted = inverted.replace(whole, anchor)
    assert inverted == base
    modified += 1
    results.append({'path': path, 'new': False, 'before_b608': row['before'],
                    'proposal_after': row['after'], 'insertion_only_inverse_exact': True,
                    'composition_base': base_origin, 'composition_before': pin(base.encode()),
                    'composition_after': pin(composed.encode()), 'composition_inverse_exact': True})
assert (new, modified) == (4, 3)
references = json.loads((LAYER / 'SOURCE_REFERENCES.json').read_bytes())
for ref in references:
    assert ref['path'] in graph
    assert {key: ref[key] for key in ('bytes', 'sha256', 'git_blob')} == {key: graph[ref['path']][key] for key in ('bytes', 'sha256', 'git_blob')}
result = {'format': 'hepta-e3-root-cli-independent-byte-composition-review-v1',
          'packet': pin(raw), 'reference_files_bound_to_exact_b608_graph': len(references),
          'new_production_modules': new, 'modified_original_files': modified,
          'mounts': len(splices), 'files': results,
          'source_written': False, 'H_calls': 0, 'formatter_compiler_or_project_tests_run': False,
          'actual_IPC_layer_composed': False, 'qualification': False}
body = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode()
with (OUT / 'BYTE_COMPOSITION_REVIEW.json').open('xb') as stream:
    stream.write(body)
print(json.dumps({'review': pin(body), 'new_production_modules': new, 'modified_original_files': modified, 'qualification': False}))
