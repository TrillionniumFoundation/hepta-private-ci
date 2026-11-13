import hashlib
import json
from pathlib import Path

root = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')


def pin(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }


def tree_hash(files):
    tree = {}
    for path, identity in files.items():
        parts = path.split('/')
        assert path and not path.startswith('/') and all(x not in ('', '.', '..') for x in parts)
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            assert isinstance(node, dict)
        assert parts[-1] not in node
        node[parts[-1]] = identity

    def digest(node):
        rows = []
        for name, item in node.items():
            mode, sha = ('40000', digest(item)) if isinstance(item, dict) else item
            key = name.encode() + (b'/' if mode == '40000' else b'')
            rows.append((key, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(row for _, row in sorted(rows))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

    return digest(tree)


packet_raw = (root / 'SOURCE_PACKET.json').read_bytes()
assert pin(packet_raw) == {
    'bytes': 152573,
    'sha256': '84b79dd4fc36e070f57f3de05982cd7a55130b5af67f7890a98ad187a1219300',
    'git_blob': '12a664ce2905feb8107ae66b303c4975f17a9fe3',
}
packet = json.loads(packet_raw)
inventory_raw = (root / 'ACTUAL_FINAL_INVENTORY.exact_recovered.json').read_bytes()
assert pin(inventory_raw) == packet['actual_baseline_inventory']
inventory = json.loads(inventory_raw)
assert len(inventory['files']) == inventory['filesystem_entries'] == inventory['tracked_entries'] == 15237
rows = {row['path']: row for row in inventory['files']}
assert len(rows) == 15237
assert all(row['stable'] for row in rows.values())
physical = {}
for path, row in rows.items():
    mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
    assert mode == row['index_mode']
    physical[path] = (mode, row['working_blob'])
actual_tree = tree_hash(physical)
assert actual_tree == packet['actual_baseline_physical_tree'] == '4ed32552042fee522965ea54caf95bbebb31ad43'
assert [path for path, row in rows.items() if not row['matches_index']] == ['codex-rs/hepta-learning-ledger/src/witness.rs']

replacements = json.loads((root / 'INPUT_COMPARISON_REPLACEMENTS.json').read_text())
transport = json.loads((root / 'TRANSPORT_REPLACEMENTS.json').read_text())
verified = []
for change in packet['changes']:
    path = change['path']
    for phase in ('before', 'after'):
        assert pin(change[phase + '_text'].encode()) == change[phase]
    row = rows[path]
    assert (row['bytes'], row['sha256'], row['working_blob']) == (
        change['before']['bytes'], change['before']['sha256'], change['before']['git_blob'])
    assert change['mode'] == row['index_mode'] == '100644'
    pairs = [(x['old'], x['new']) for x in replacements if x['path'] == path]
    if path.endswith('authority_host_learning_resident_provider_transport_tests.rs'):
        pairs = transport
    if path.endswith('circuit_resident_candidate_first_material_support_tests.rs'):
        pairs = [('pub(super) use wire::encode_original_report;', 'use wire::encode_original_report;')]
    assert pairs
    forward = change['before_text']
    inverse = change['after_text']
    for old, new in pairs:
        assert forward.count(old) == inverse.count(new) == 1
        forward = forward.replace(old, new)
        inverse = inverse.replace(new, old)
    assert forward == change['after_text'] and inverse == change['before_text']
    physical[path] = (change['mode'], change['after']['git_blob'])
    verified.append({'path': path, 'exact_splices': len(pairs), 'full_inverse_equal': True})

assert len(packet['changes']) == 4 and not packet['source_deletions']
assert len(packet['preserved_actual_fix_postimages']) == 1
witness = packet['preserved_actual_fix_postimages'][0]
assert pin(witness['after_text'].encode()) == witness['after']
assert witness['after']['git_blob'] == 'a45cfde5e0d6c17a8b9502f66c43979f26f6bc4d'
assert physical[witness['path']] == ('100644', witness['after']['git_blob'])
successor_tree = tree_hash(physical)
assert successor_tree == packet['expected_successor_physical_tree'] == '1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1'
print(json.dumps({
    'format': 'hepta-root-pure-fix101-repair-byte-and-merkle-review-v1',
    'packet': pin(packet_raw),
    'exact_recovered_original_inventory': pin(inventory_raw),
    'inventory_provenance': 'Lossless reconstruction equal to original producer-observed bytes/SHA/Git; not a second native inventory read.',
    'file_count': len(physical),
    'actual_baseline_tree': actual_tree,
    'expected_successor_tree': successor_tree,
    'four_exact_manual_repairs': verified,
    'actual_witness_preserved': witness['after'],
    'H_dispatched': False,
    'qualification': False,
    'compile_fmt_tests': 'not run on repair',
}, indent=2, sort_keys=True))
