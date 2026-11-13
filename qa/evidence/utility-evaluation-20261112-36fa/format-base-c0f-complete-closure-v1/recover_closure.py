#!/usr/bin/env python3
"""Pure-byte recovery of preserved Git originals; no Git process or native IO."""
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_COMMIT = 'c0f78493f815780f68b9bf5e390a21314d79311f'
BASE_TREE = '313ee34febc8ccc54c611ab56286e289518c63cb'

def identity(data, kind='blob'):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(kind.encode('ascii') + b' ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()}

def check(data, expected, kind='blob'):
    got = identity(data, kind)
    for key, aliases in [('bytes', ('bytes', 'raw_bytes')), ('sha256', ('sha256', 'raw_sha256')), ('git_blob', ('git_blob', 'git_blob_sha', 'sha', 'raw_git_blob'))]:
        for alias in aliases:
            if alias in expected:
                assert got[key] == expected[alias], (key, got, expected)
                break
    return got

def write_once_or_equal(path, data):
    if path.exists():
        assert path.read_bytes() == data, ('existing derived output differs', str(path))
    else:
        with path.open('xb') as out:
            out.write(data)

def encode_json(obj):
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode('utf-8')

def decoded_part(path):
    b = path.read_bytes()
    assert b.endswith(b'\n') and not b.endswith(b'\n\n') and b'\n' not in b[:-1] and b'\r' not in b
    decoded = base64.b64decode(b[:-1], validate=True)
    assert base64.b64encode(decoded) + b'\n' == b
    return b, decoded

def recover_inventory(manifest, input_prefix, target):
    parts = []
    observed = []
    for i, expected in enumerate(manifest['parts']):
        encoded, decoded = decoded_part(ROOT / (input_prefix + str(i) + '.b64'))
        check(encoded, expected)
        assert len(decoded) == expected['decoded_bytes']
        assert sum(map(len, parts)) == expected['decoded_offset']
        assert hashlib.sha256(decoded).hexdigest() == expected['decoded_sha256']
        parts.append(decoded)
        observed.append({'ordinal': i, 'encoded': identity(encoded), 'decoded': identity(decoded)})
    compressed = b''.join(parts)
    check(compressed, manifest)
    raw = gzip.decompress(compressed)
    check(raw, {'bytes': manifest['raw_bytes'], 'sha256': manifest['raw_sha256'], 'git_blob': manifest['raw_git_blob']})
    write_once_or_equal(ROOT / (target + '.json.gz'), compressed)
    write_once_or_equal(ROOT / (target + '.json'), raw)
    return json.loads(raw), {'raw': identity(raw), 'gzip': identity(compressed), 'parts': observed}

def tree_entries(raw):
    pos = 0
    entries = []
    while pos < len(raw):
        sp = raw.index(b' ', pos)
        nul = raw.index(b'\0', sp + 1)
        mode = raw[pos:sp].decode('ascii')
        name = raw[sp + 1:nul]
        assert mode in ('40000', '100644', '100755', '120000'), mode
        assert name not in (b'', b'.', b'..') and b'/' not in name and b'\0' not in name
        assert nul + 21 <= len(raw)
        oid = raw[nul + 1:nul + 21].hex()
        entries.append((mode, name, oid))
        pos = nul + 21
    assert pos == len(raw)
    assert entries == sorted(entries, key=lambda row: row[1] + (b'/' if row[0] == '40000' else b''))
    assert len({x[1] for x in entries}) == len(entries)
    return entries

def leaf_map(inventory):
    assert inventory['filesystem_entries'] == inventory['tracked_entries'] == len(inventory['files'])
    result = {}
    for row in inventory['files']:
        path = row['path']
        assert path not in result and not path.startswith('/') and all(x not in ('', '.', '..') for x in path.split('/'))
        assert row['stable'] and row['matches_index']
        assert row['index_blob'] == row['working_blob']
        assert row['index_mode'] in ('100644', '100755', '120000')
        result[path] = {'mode': row['index_mode'], 'sha': row['index_blob'], 'bytes': row['bytes'], 'sha256': row['sha256'], 'kind': row['kind']}
    return result

def make_trees(leaves):
    dirs = {'': {}}
    for path, row in leaves.items():
        names = path.split('/')
        for i in range(len(names) - 1):
            parent = '/'.join(names[:i])
            child_path = '/'.join(names[:i + 1])
            dirs.setdefault(child_path, {})
            previous = dirs[parent].setdefault(names[i], ('40000', child_path))
            assert previous == ('40000', child_path)
        parent = '/'.join(names[:-1])
        assert names[-1] not in dirs[parent]
        dirs[parent][names[-1]] = (row['mode'], row['sha'])
    path_oids = {}
    bodies = {}
    for path in sorted(dirs, key=lambda p: (p.count('/'), len(p)), reverse=True):
        entries = []
        for name, (mode, target) in dirs[path].items():
            oid = path_oids[target] if mode == '40000' else target
            entries.append((mode, name.encode('utf-8'), oid))
        entries.sort(key=lambda e: e[1] + (b'/' if e[0] == '40000' else b''))
        raw = b''.join(mode.encode('ascii') + b' ' + name + b'\0' + bytes.fromhex(oid) for mode, name, oid in entries)
        oid = identity(raw, 'tree')['git_blob']
        if oid in bodies:
            assert bodies[oid] == raw
        bodies[oid] = raw
        path_oids[path] = oid
    return path_oids[''], bodies, path_oids

def blob_metadata(leaves):
    output = {}
    for path, row in sorted(leaves.items()):
        oid = row['sha']
        value = output.setdefault(oid, {'type': 'blob', 'sha': oid, 'bytes': row['bytes'], 'sha256': row['sha256'], 'paths': []})
        assert value['bytes'] == row['bytes'] and value['sha256'] == row['sha256']
        value['paths'].append(path)
    return output

def main():
    inputs = json.loads((ROOT / 'INPUT_MANIFEST.json').read_bytes())
    for item in inputs['originals']:
        data = (ROOT / item['path']).read_bytes()
        if item['local_copy_append_LF_if_missing']:
            assert data.endswith(b'\n')
            data = data[:-1]
        check(data, item)
    retained = json.loads((ROOT / 'c0f_recovery_manifest.json').read_bytes())
    proof = json.loads((ROOT / 'c0f_inventory_reconstruction_proof.json').read_bytes())
    raw_parts = retained['dependencies']['c0f_original_inventory']['parts']
    recovered_parts = []
    encoded_checks = []
    for i, expected in enumerate(raw_parts):
        encoded, decoded = decoded_part(ROOT / ('c0f_inventory_companion_' + str(i) + '.b64'))
        check(decoded, expected)
        recovered_parts.append(decoded)
        encoded_checks.append({'ordinal': i, 'encoded': identity(encoded), 'decoded': identity(decoded)})
    c0f_gzip = b''.join(recovered_parts)
    assert len(c0f_gzip) == proof['reconstructed_gzip_bytes']
    assert hashlib.sha256(c0f_gzip).hexdigest() == proof['reconstructed_gzip_sha256']
    c0f_raw = gzip.decompress(c0f_gzip)
    check(c0f_raw, retained['dependencies']['c0f_original_inventory']['raw'])
    assert (ROOT / 'C0F_INVENTORY.json').read_bytes() == c0f_raw
    assert (ROOT / 'C0F_INVENTORY.json.gz').read_bytes() == c0f_gzip
    c0f_inventory = json.loads(c0f_raw)
    c0f_leaves = leaf_map(c0f_inventory)
    c0f_root, c0f_trees, c0f_tree_paths = make_trees(c0f_leaves)
    assert c0f_root == BASE_TREE and len(c0f_leaves) == 14851

    tree_manifest = next(x for x in retained['recovered_original_outputs'] if x['name'] == 'TREE_AND_ANCHOR_RAW.json.gz')
    tree_doc, tree_recovery = recover_inventory(tree_manifest, 'c0f_tree_anchor_part_', 'TREE_AND_ANCHOR_RAW')
    supplied_objects = {}
    for collection in ('existing', 'provided_tree_and_commit'):
        for item in tree_doc[collection]:
            raw = base64.b64decode(item['raw_base64'], validate=True)
            assert base64.b64encode(raw).decode('ascii') == item['raw_base64']
            check(raw, item, item['type'])
            if item['sha'] in supplied_objects:
                assert supplied_objects[item['sha']] == (item['type'], raw)
            supplied_objects[item['sha']] = (item['type'], raw)
    for oid, raw in c0f_trees.items():
        assert supplied_objects[oid] == ('tree', raw), ('derived/original tree mismatch', oid)
        tree_entries(raw)
    kind, c0f_commit_raw = supplied_objects[BASE_COMMIT]
    assert kind == 'commit'
    anchor = next(x for x in retained['dependencies']['anchor_commits'] if x['commit'] == BASE_COMMIT)
    check(c0f_commit_raw, {'bytes': anchor['bytes'], 'sha256': anchor['sha256'], 'sha': BASE_COMMIT}, 'commit')
    headers = c0f_commit_raw.split(b'\n\n', 1)[0].split(b'\n')
    assert headers[0] == b'tree ' + BASE_TREE.encode('ascii')
    parents = [x[7:].decode('ascii') for x in headers if x.startswith(b'parent ')]
    assert parents == ['e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd', 'b29869e856d08db1bfb066116a9c443376ccc57d']
    write_once_or_equal(ROOT / 'C0F_COMMIT.raw', c0f_commit_raw)

    cc57_manifest = json.loads((ROOT / 'CC57_INVENTORY_MANIFEST.json').read_bytes())
    cc57_inventory, cc57_recovery = recover_inventory(cc57_manifest, 'c0f_compare_cc57_part_', 'CC57_INVENTORY')
    cc57_leaves = leaf_map(cc57_inventory)
    packet_bytes = (ROOT / 'MATERIALIZER_PACKET.original.json').read_bytes()
    assert identity(packet_bytes)['git_blob'] == '06503652a2895120daf8b66e42b3a01cefeaf4fb'
    materializer = json.loads(packet_bytes)
    assert len(cc57_leaves) == 15188
    cc57_root, cc57_trees, _ = make_trees(cc57_leaves)
    assert cc57_root == materializer['current']['tree']
    parent_leaves = copy.deepcopy(cc57_leaves)
    for change in materializer['parent_snapshot']['changes_from_current']:
        original = parent_leaves[change['path']]
        assert original['mode'] == change['mode']
        assert (original['sha'], original['bytes'], original['sha256']) == (change['current']['git_blob'], change['current']['bytes'], change['current']['sha256'])
        original.update(sha=change['parent']['git_blob'], bytes=change['parent']['bytes'], sha256=change['parent']['sha256'])
    parent_root, parent_trees, _ = make_trees(parent_leaves)
    assert parent_root == materializer['parent_snapshot']['tree']
    cc57_blobs = blob_metadata(cc57_leaves)
    parent_blobs = blob_metadata(parent_leaves)
    current_union_trees = set(cc57_trees) | set(parent_trees)
    current_union_blobs = set(cc57_blobs) | set(parent_blobs)
    assert (len(current_union_trees), len(current_union_blobs)) == (1832, 14615)
    assert len(current_union_trees) + len(current_union_blobs) + 2 == 16449
    c0f_blobs = blob_metadata(c0f_leaves)
    base_only_blobs = [c0f_blobs[x] for x in sorted(set(c0f_blobs) - current_union_blobs)]
    base_only_trees = sorted(set(c0f_trees) - current_union_trees)
    common_blobs = sorted(set(c0f_blobs) & current_union_blobs)
    for oid in common_blobs:
        actual = cc57_blobs.get(oid, parent_blobs.get(oid))
        assert (c0f_blobs[oid]['bytes'], c0f_blobs[oid]['sha256']) == (actual['bytes'], actual['sha256'])
    known_tree_objects = [{'type': 'tree', 'sha': oid, 'bytes': len(c0f_trees[oid]), 'sha256': hashlib.sha256(c0f_trees[oid]).hexdigest(), 'raw_base64': base64.b64encode(c0f_trees[oid]).decode('ascii')} for oid in base_only_trees]
    commit_object = {'type': 'commit', 'sha': BASE_COMMIT, 'bytes': len(c0f_commit_raw), 'sha256': hashlib.sha256(c0f_commit_raw).hexdigest(), 'raw_base64': base64.b64encode(c0f_commit_raw).decode('ascii')}
    closure = {'schema': 'hepta-c0f-format-base-complete-object-identities-v1', 'commit': BASE_COMMIT, 'tree': BASE_TREE, 'parents': parents,
               'snapshot_only_not_ancestry': True, 'leaves': len(c0f_leaves),
               'objects': [commit_object] + [{'type': 'tree', 'sha': oid, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for oid, raw in sorted(c0f_trees.items())] + [c0f_blobs[x] for x in sorted(c0f_blobs)]}
    delta = {'schema': 'hepta-c0f-format-base-object-delta-v1', 'status': 'HOLD_BLOB_BODIES_PENDING', 'base_commit': BASE_COMMIT, 'base_tree': BASE_TREE,
             'compared_current_snapshot_commits': [materializer['current']['commit'], materializer['parent_snapshot']['commit']], 'current_declared_object_count': 16449,
             'provided_tree_and_commit_objects': [commit_object] + known_tree_objects,
             'missing_blob_bodies': base_only_blobs,
             'required_existing_objects': [{'type': 'blob', 'sha': oid, 'bytes': c0f_blobs[oid]['bytes'], 'sha256': c0f_blobs[oid]['sha256']} for oid in common_blobs] + [{'type': 'tree', 'sha': oid, 'bytes': len(c0f_trees[oid]), 'sha256': hashlib.sha256(c0f_trees[oid]).hexdigest()} for oid in sorted(set(c0f_trees) & current_union_trees)],
             'old_repo_mutation': False, 'native_availability_observed_now': False}
    outputs = [('C0F_CLOSURE_IDENTITIES.json', closure), ('BASE_OBJECT_DELTA.HOLD.json', delta), ('BASE_ONLY_BLOB_IDENTITIES.json', base_only_blobs)]
    output_pins = []
    for name, value in outputs:
        data = encode_json(value)
        write_once_or_equal(ROOT / name, data)
        output_pins.append({'path': name, **identity(data)})
    summary = {'schema': 'hepta-c0f-format-base-exact-recovery-review-v1', 'status': 'EXACT_RECOVERED_ORIGINALS_AND_STATIC_CLOSURE',
               'native_execution': False, 'source_mutation': False,
               'c0f_inventory': {'raw': identity(c0f_raw), 'gzip': identity(c0f_gzip), 'parts': encoded_checks},
               'tree_and_anchor_original': tree_recovery, 'cc57_inventory': cc57_recovery,
               'c0f_commit_raw': identity(c0f_commit_raw, 'commit'), 'c0f_parents': parents,
               'c0f': {'leaves': len(c0f_leaves), 'tree': c0f_root, 'unique_trees': len(c0f_trees), 'unique_blobs': len(c0f_blobs), 'commits': 1, 'closure_objects': len(c0f_trees) + len(c0f_blobs) + 1},
               'existing_declared_pack': {'commits': [materializer['current']['commit'], materializer['parent_snapshot']['commit']], 'trees': len(current_union_trees), 'blobs': len(current_union_blobs), 'total': 16449, 'c0f_commit_present': False},
               'required_increment': {'commit_objects': 1, 'tree_objects': len(base_only_trees), 'blob_objects': len(base_only_blobs), 'total': 1 + len(base_only_trees) + len(base_only_blobs), 'blob_bytes': sum(x['bytes'] for x in base_only_blobs)},
               'limits': ['The comparison is to the exactly declared and previously observed cc57+246d snapshot pack. It is not a fresh native object-store observation.', 'The recovered inventories are original preserved bytes, not new physical filesystem reads.', 'Required base-only blob bodies have not yet been retrieved by this script.', 'No parent ancestry traversal, network in the script, Git command, source/index/ref write, gate or formatter was executed.', 'A future approved materializer must reverify every imported or reused object and actual full source; this metadata is not execution permission.'],
               'outputs': output_pins}
    data = encode_json(summary)
    write_once_or_equal(ROOT / 'RECOVERY_REVIEW.json', data)
    print(json.dumps({'review': identity(data), 'c0f': summary['c0f'], 'required_increment': summary['required_increment'], 'outputs': output_pins}, sort_keys=True))

if __name__ == '__main__':
    main()
