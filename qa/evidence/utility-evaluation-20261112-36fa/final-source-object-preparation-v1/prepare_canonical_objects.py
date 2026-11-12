import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-final-source-preparation-v1')
INVENTORY = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json')
FORMAT = Path('/tmp/hepta-36fa-maintenance-v5-launch/fmt.after.postimages.json')
CANDIDATE = Path('/tmp/hepta-36fa-reviewed-final-nonrust-v1')


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}


def tree_objects(leaves):
    root = {}
    for path, value in leaves.items():
        parts = path.split('/')
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = value
    objects = {}

    def visit(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, sha, order = '40000', visit(value), name.encode() + b'/'
            else:
                mode, sha = value
                order = name.encode()
            entries.append((order, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(row for _, row in sorted(entries))
        sha = oid('tree', raw)
        assert sha not in objects or objects[sha] == raw
        objects[sha] = raw
        return sha

    return visit(root), objects


def main():
    original = json.loads(INVENTORY.read_bytes())
    assert len(original['files']) == 15188
    old = {row['path']: (row['index_mode'], row['index_blob']) for row in original['files']}
    working = {row['path']: ('120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644'), row['working_blob']) for row in original['files']}
    old_tree, old_trees = tree_objects(old)
    assert old_tree == original['source']['tree'] == 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'
    assert tree_objects(working)[0] == '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
    packet = json.loads((CANDIDATE / 'NONRUST_PACKET.json').read_bytes())
    bodies = {}
    for change in json.loads(FORMAT.read_bytes())['changes']:
        raw = base64.b64decode(change['after_raw_base64'], validate=True)
        sha = oid('blob', raw)
        assert sha == change['after']['working_blob'] == working[change['path']][1]
        assert hashlib.sha256(raw).hexdigest() == change['after']['sha256']
        bodies[change['path']] = raw
    assert len(bodies) == 43
    for change in packet['changes']:
        assert change['path'] not in bodies
        raw = base64.b64decode(change['after_base64'], validate=True)
        assert pin(raw) == change['after']
        working[change['path']] = (change['mode'], change['after']['git_blob'])
        bodies[change['path']] = raw
    assert len(bodies) == 54
    new_tree, new_trees = tree_objects(working)
    assert new_tree == packet['expected_after_physical_tree'] == '74a2fe12be39aba5ab55d537124cd9462673fd9e'
    changed = sorted(path for path in old if old[path] != working[path])
    assert changed == sorted(bodies)
    objects = {}
    for path, raw in bodies.items():
        sha = oid('blob', raw)
        assert sha == working[path][1]
        objects[sha] = {'type': 'blob', 'sha': sha, 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(),
                        'raw_base64': base64.b64encode(raw).decode()}
    for sha in sorted(set(new_trees) - set(old_trees)):
        raw = new_trees[sha]
        objects[sha] = {'type': 'tree', 'sha': sha, 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(),
                        'raw_base64': base64.b64encode(raw).decode()}
    output = {'format': 'hepta-canonical-candidate-object-preparation-v1',
              'status': 'prepared_only_actual_final_format_and_commit_required',
              'old_commit': original['source']['head'], 'old_tree': old_tree,
              'candidate_tree': new_tree, 'complete_leaf_count': len(working),
              'changed_paths': changed, 'new_commit': None,
              'objects': [objects[key] for key in sorted(objects)],
              'native_execution': False, 'source_reference_updated': False, 'qualification': False}
    raw = (json.dumps(output, sort_keys=True, separators=(',', ':')) + '\n').encode()
    compressed = gzip.compress(raw, mtime=0)
    (ROOT / 'OBJECTS_PREPARED.json').write_bytes(raw)
    (ROOT / 'OBJECTS_PREPARED.json.gz').write_bytes(compressed)
    report = {'format': output['format'], 'status': output['status'],
              'raw': pin(raw), 'gzip': pin(compressed), 'old_tree': old_tree, 'candidate_tree': new_tree,
              'complete_leaf_count': len(working), 'changed_paths': len(changed),
              'object_count': len(objects),
              'blob_count': sum(x['type'] == 'blob' for x in objects.values()),
              'tree_count': sum(x['type'] == 'tree' for x in objects.values()),
              'new_commit': None, 'native_execution': False, 'qualification': False}
    (ROOT / 'OBJECTS_PREPARED_MANIFEST.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
