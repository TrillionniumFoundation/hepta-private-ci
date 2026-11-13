"""Compose exact frozen source layers in a new cloud-only candidate directory.

No project code, collector, formatter, compiler, H process, or Git mutation.
E2 CLI/Material source-loan and E3 late enrollment are not included yet.
"""
import hashlib
import json
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
OUT = Path('/tmp/hepta-36fa-root-product-composition-v2')
E1 = Path('/tmp/hepta-36fa-e1-source-candidate-v1')
E2 = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
E3 = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/root-service-layer-v1')
K = ('bytes', 'sha256', 'git_blob')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def parse(path):
    return json.loads(path.read_bytes())


raw_graph = (R / 'PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(raw_graph)['git_blob'] == '7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base = {e['path']: {key: e[key] for key in K} for e in json.loads(raw_graph)['files']}
current = base.copy()
source = {}
layers = []
e1 = parse(E1 / 'MANIFEST.json')
assert e1['tree'] == '3778225f2d49dcd4729d05c02ae9805b43df87d8'
for e in e1['files']:
    path = e['path']
    assert current.get(path) == e['before']
    raw = (E1 / 'after' / path).read_bytes()
    assert pin(raw) == e['after']
    current[path] = e['after']
    source[path] = raw
layers.append({'layer': 'E1 actual review commit 99fada80470f175ba14004ea9fcb006853c7d98f', 'paths': 19})
for name, expected in [('factory-split-layer-v1', '62ad5a5363ca91c335f2d599128f763c355b33bf'),
                       ('factory-test-refusal-increment-v1', '12459a8255be0358c822a825d2445fa48828a7e1'),
                       ('ipc-layer-v1', '06dafdbdeb53eb5ccf6480993596bbb4d939f203')]:
    packet_raw = (E2 / name / 'SOURCE_PACKET.json').read_bytes()
    assert pin(packet_raw)['git_blob'] == expected
    packet = json.loads(packet_raw)
    for e in packet['entries']:
        path = e['path']
        assert current.get(path) == e['before'], ('before pin', name, path)
        if e['before'] is not None:
            before = e['before_utf8'].encode()
            assert pin(before) == e['before']
            if path in source:
                assert source[path] == before
        else:
            assert e['before_utf8'] is None
        after = e['after_utf8'].encode()
        assert pin(after) == e['after']
        source[path] = after
        current[path] = e['after']
    layers.append({'layer': name, 'packet': pin(packet_raw), 'paths': len(packet['entries'])})

ipc = parse(E2 / 'ipc-layer-v1' / 'SOURCE_PACKET.json')
ipc_rows = {e['path']: e for e in ipc['entries']}
replacements = parse(E2 / 'ipc-layer-v1' / 'EXACT_REPLACEMENTS.json')
assert len(replacements) == 12
for row in replacements:
    e = ipc_rows[row['path']]
    assert e['before'] is not None and row['before'] == e['before'] and row['after'] == e['after']
    value = e['before_utf8']
    positions = []
    for change in row['replacements']:
        assert value.count(change['before']) == 1
        at = value.index(change['before'])
        positions.append((at, change))
        value = value[:at] + change['after'] + value[at + len(change['before']):]
    assert value == e['after_utf8']
    for at, change in reversed(positions):
        assert value[at:at + len(change['after'])] == change['after']
        value = value[:at] + change['before'] + value[at + len(change['after']):]
    assert value == e['before_utf8']
driver = ipc_rows['codex-rs/hepta-agentd/src/circuit_task_driver.rs']
anchor = '    pub fn new('
assert driver['before_utf8'].count(anchor) == driver['after_utf8'].count(anchor) == 1
assert driver['before_utf8'].split(anchor, 1)[1] == driver['after_utf8'].split(anchor, 1)[1]

e3_raw = (E3 / 'SOURCE_PACKET.json').read_bytes()
assert pin(e3_raw)['git_blob'] == '0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b'
splices = parse(E3 / 'EXACT_MOUNT_SPLICES.json')
for e in json.loads(e3_raw)['entries']:
    path = e['path']
    assert pin(e['after_utf8'].encode()) == e['after']
    if e['before'] is None:
        assert path not in current
        source[path] = e['after_utf8'].encode()
    else:
        assert base[path] == e['before'] == pin(e['before_utf8'].encode())
        before = source.get(path, e['before_utf8'].encode())
        assert pin(before) == current[path]
        value = before.decode()
        edits = [s for s in splices if s['path'] == path]
        assert edits
        for s in edits:
            assert value.count(s['anchor']) == 1
            value = value.replace(s['anchor'], s.get('insert_before', '') + s['anchor'] + s.get('insert_after', ''))
        inverse = value
        for s in reversed(edits):
            inserted = s.get('insert_before', '') + s['anchor'] + s.get('insert_after', '')
            assert inverse.count(inserted) == 1
            inverse = inverse.replace(inserted, s['anchor'])
        assert inverse.encode() == before
        source[path] = value.encode()
    current[path] = pin(source[path])
layers.append({'layer': 'E3 Root service first unit', 'packet': pin(e3_raw), 'paths': 7,
               'exact_independent_mounts_applied_to_composed_E1_E2': True})
new = sorted(set(current) - set(base))
modified = sorted(path for path in base if current[path] != base[path])
assert not set(base) - set(current)
assert set(source) == set(new + modified)
for path, raw in source.items():
    output = OUT / 'after' / path
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(raw)
review = {
    'format': 'hepta-root-exact-partial-product-composition-v2',
    'base_source': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
    'base_tree': '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638', 'layers': layers,
    'files_before': len(base), 'files_after': len(current), 'new_files': len(new),
    'modified_original_files': len(modified), 'original_files_unchanged': len(base) - len(modified),
    'all_before_images_match_current_composition': True,
    'all_12_IPC_existing_file_replacements_have_exact_whole_inverse': True,
    'original_Driver_first_public_method_to_EOF_byte_unchanged': True,
    'files': [{'path': path, 'before': base.get(path), 'after': current[path]} for path in sorted(source)],
    'remaining': ['E2 ordinary CLI/launcher handoff', 'E2 non-Root Material readonly Source loan',
                  'E2 necessary mechanism tests', 'E3 real late enrollment layer and necessary tests',
                  'Full typed caller/protection registration of new layers', 'Original formatter/compiler/source/native gates',
                  'Actual authorized A-independent B-C and daemon/Root process cold recovery'],
    'no_source_Git_or_H_mutations': True, 'H_calls': 0,
    'formatter_compiler_collector_or_project_tests_executed': False,
    'qualification': False, 'real_qualified_task_chains': 0,
}
raw = (json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
with (OUT / 'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'review': pin(raw), 'changed_paths': len(source), 'new_files': len(new),
                  'modified_original_files': len(modified), 'files_after': len(current), 'qualification': False}))
