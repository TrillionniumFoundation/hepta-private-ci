"""Exact extension of the frozen v4 view. No Rust or project gate execution."""
import hashlib
import json
from pathlib import Path

PREV = Path('/tmp/hepta-36fa-root-product-composition-v4')
OUT = Path('/tmp/hepta-36fa-root-product-composition-v5')
BASE = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/PROPOSED_NONRUST_8EBB_GRAPH.json')

def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

g = BASE.read_bytes()
assert pin(g)['git_blob'] == '7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base = {e['path']: {k: e[k] for k in ('bytes', 'sha256', 'git_blob')} for e in json.loads(g)['files']}
previous_raw = (PREV / 'PREQUALIFICATION_COMPOSITION_REVIEW.json').read_bytes()
assert pin(previous_raw)['git_blob'] == 'eab2a34d1bd7abbaab81d5c1e06177269a14efd4'
previous = json.loads(previous_raw)
current, sources = base.copy(), {}
for e in previous['files']:
    b = (PREV / 'after' / e['path']).read_bytes()
    assert pin(b) == e['after'] and e['before'] == base.get(e['path'])
    current[e['path']] = e['after']
    sources[e['path']] = b

layers = []
for directory, sha, kind in [
    ('/tmp/hepta-36fa-root-product-e2-proposal-v1/material-source-mechanism-tests-layer-v1',
     'e120273ac730addd8cc47f31e829692afa17bc0d', 'test'),
    ('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/inputs-layer-v1',
     'e78f0413a20e306c1064c51eb8e53e76d597fd93', 'loader'),
]:
    d = Path(directory)
    raw = (d / 'SOURCE_PACKET.json').read_bytes()
    assert pin(raw)['git_blob'] == sha
    packet = json.loads(raw)
    edits = json.loads((d / 'MOUNT_SPLICES.json').read_bytes()) if kind == 'loader' else []
    affected = []
    for e in packet['entries']:
        path = e['path']
        assert current.get(path) == e['before'], ('whole current before differs', path)
        after = e['after_utf8'].encode()
        assert pin(after) == e['after']
        if e['before'] is not None:
            before = e['before_utf8'].encode()
            assert pin(before) == e['before'] and sources[path] == before
            if kind == 'test':
                assert after.startswith(before) and len(after) - len(before) == 75
                assert after[len(before):].startswith(b'\n#[cfg(test)]')
            else:
                applicable = [x for x in edits if x['path'] == path]
                assert len(applicable) == 1
                edit = applicable[0]
                assert edit['before'] == e['before']
                old, new = edit['old'].encode(), edit['new'].encode()
                assert before.count(old) >= 1 and after.count(new) == 1
                assert before.replace(old, new, 1) == after
                assert after.replace(new, old) == before
        else:
            assert path not in base and e.get('before_utf8') is None
        sources[path] = after
        current[path] = e['after']
        affected.append({'path': path, 'before': e['before'], 'after': e['after']})
    layers.append({'layer': d.name, 'packet': pin(raw), 'kind': kind, 'files': affected})

new = sorted(set(current) - set(base))
modified = sorted(p for p in base if current[p] != base[p])
assert not set(base) - set(current)
assert set(sources) == set(new + modified)
review = {'format': 'hepta-root-partial-product-composition-v5',
          'base_source': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
          'previous_composition': pin(previous_raw), 'layers': layers,
          'all_complete_current_before_images_equal': True,
          'loader_mounts_whole_inverse_equal': 4,
          'material_test_mount_preserves_complete_original_body': True,
          'files_before': len(base), 'files_after': len(current), 'changed_paths': len(sources),
          'new_files': len(new), 'modified_original_files': len(modified),
          'original_files_unchanged': len(base) - len(modified),
          'files': [{'path': p, 'before': base.get(p), 'after': current[p]} for p in sorted(sources)],
          'remaining': ['same-session Task/Material/V3 orchestration and actual CLI hookup',
                        'complete final caller/protection/test registration',
                        'original formatter/compiler/source/native qualification gates',
                        'real authorized A-independent B-C and actual daemon/Root process cold recovery'],
          'H_calls': 0, 'project_code_executed': False, 'source_Git_mutation': False,
          'qualification': False, 'real_qualified_chains': 0}
for p, b in sources.items():
    path = OUT / 'after' / p
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(b)
b = (json.dumps(review, indent=2, sort_keys=True) + '\n').encode()
with (OUT / 'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as f:
    f.write(b)
print(json.dumps({'review': pin(b), 'changed_paths': len(sources), 'new_files': len(new),
                  'modified_original_files': len(modified), 'files_after': len(current), 'qualification': False}))
