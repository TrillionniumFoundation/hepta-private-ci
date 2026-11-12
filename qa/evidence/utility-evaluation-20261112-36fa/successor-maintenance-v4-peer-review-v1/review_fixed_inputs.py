import base64
import copy
import hashlib
import json
from pathlib import Path

root = Path('/tmp/hepta-36fa-successor-peer-review-v4')


def identity(body, kind='blob'):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob_sha': hashlib.sha1(kind.encode() + b' ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def serialized_inventory(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


packet_raw = (root / 'CANONICAL_PACKET.json').read_bytes()
packet = json.loads(packet_raw)
contract_raw = (root / 'SOURCE_ADVANCE_CONTRACT.json').read_bytes()
contract = json.loads(contract_raw)
assert identity(packet_raw)['git_blob_sha'] == 'a62a7e701f42ea18dfa93fc0d5eb521f836750cb'
assert identity(contract_raw)['git_blob_sha'] == 'a1ef48291d34646c4c5c763ba51a63d32a76c3f7'
objects = {}
for obj in packet['objects']:
    body = base64.b64decode(obj['raw_base64'], validate=True)
    observed = identity(body, obj['type'])
    assert len(body) == obj['bytes']
    assert observed['sha256'] == obj['sha256'] and observed['git_blob_sha'] == obj['sha']
    objects[obj['sha']] = {'type': obj['type'], 'body': body}
assert len(objects) == len(packet['objects']) == 6
inventory_raw = Path('/tmp/hepta-36fa-a96-recovery/MATERIALIZED_86DD_INVENTORY.recovered.json').read_bytes()
inventory = json.loads(inventory_raw)
assert identity(inventory_raw)['sha256'] == 'bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711'
assert serialized_inventory(inventory) == inventory_raw
leaves = {row['path']: (row['index_mode'], row['index_blob']) for row in inventory['files']}
assert len(leaves) == 15188
created_trees = {}


def merkle(leaf_map):
    directory = {}
    for path, entry in leaf_map.items():
        node = directory
        components = path.split('/')
        for component in components[:-1]:
            node = node.setdefault(component, {})
        assert components[-1] not in node
        node[components[-1]] = entry

    def walk(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, sha = '40000', walk(value)
                key = name.encode() + b'/'
            else:
                mode, sha = value
                key = name.encode()
            entries.append((key, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        body = b''.join(value for _, value in sorted(entries))
        sha = identity(body, 'tree')['git_blob_sha']
        created_trees[sha] = body
        return sha

    return walk(directory)


old_tree = merkle(leaves)
assert old_tree == packet['before']['tree'] == '383ab85c39ef9d848252ef5c25922d13d9fae6c6'
assert packet['before']['commit'] == inventory['source']['head'] == '86dd56a930277e0d1aef3e475e35c2b5d60b43b7'
assert len(packet['changed_source']) == 1
change = packet['changed_source'][0]
path = change['path']
before = (root / 'ports.before.rs').read_bytes()
after = objects[change['after_git_blob']]['body']
assert identity(before)['git_blob_sha'] == change['before_git_blob'] == leaves[path][1]
assert len(before) == change['before_bytes'] and identity(before)['sha256'] == change['before_sha256']
assert len(after) == change['after_bytes'] and identity(after)['sha256'] == change['after_sha256']
added_line = b'pub(crate) use super::super::connection::recovered_peer;\n'
assert after.count(added_line) == 1 and after.replace(added_line, b'', 1) == before
updated_leaves = dict(leaves)
updated_leaves[path] = (change['mode'], change['after_git_blob'])
new_tree = merkle(updated_leaves)
assert new_tree == packet['after']['tree'] == 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'
for sha, obj in objects.items():
    if obj['type'] == 'tree':
        assert created_trees[sha] == obj['body']
commit = packet['after']['commit']
header = objects[commit]['body'].split(b'\n\n', 1)[0].splitlines()
assert [line[5:].decode() for line in header if line.startswith(b'tree ')] == [new_tree]
assert [line[7:].decode() for line in header if line.startswith(b'parent ')] == [packet['before']['commit']] == packet['after']['parents']
updated_inventory = copy.deepcopy(inventory)
updated_inventory['source'] = {'head': commit, 'tree': new_tree, 'status': ''}
row = next(row for row in updated_inventory['files'] if row['path'] == path)
row.update(bytes=len(after), index_blob=change['after_git_blob'], working_blob=change['after_git_blob'], sha256=change['after_sha256'])
predicted = identity(serialized_inventory(updated_inventory))
expected = packet['after']['expected_inventory']
assert predicted['bytes'] == expected['bytes'] and predicted['sha256'] == expected['sha256'] and predicted['git_blob_sha'] == expected['git_blob']
success = contract['successful_result_required_fields']
assert success['before']['commit'] == packet['before']['commit'] and success['before']['tree'] == old_tree
assert success['after']['commit'] == commit and success['after']['tree'] == new_tree
assert success['after']['parents'] == packet['after']['parents'] and success['after']['inventory'] == expected
assert success['changes'] == packet['changed_source']
report = {
    'format': 'hepta-successor-v4-peer-static-input-review-v1', 'qualification': False,
    'native_execution': False, 'source_mutation': False,
    'status': 'STATIC_INPUT_IDENTITIES_AND_SINGLE_LEAF_PROJECTION_MATCH',
    'contract': identity(contract_raw), 'packet': identity(packet_raw),
    'canonical_objects_verified': len(objects),
    'object_types': {kind: sum(obj['type'] == kind for obj in objects.values()) for kind in ('commit', 'tree', 'blob')},
    'complete_leaves': len(leaves), 'before_commit': packet['before']['commit'], 'before_tree': old_tree,
    'after_commit': commit, 'after_tree': new_tree, 'after_parents': packet['after']['parents'],
    'changed_source': change,
    'only_source_change': 'One pub(crate) recovered_peer reexport line; inverse deletion exactly returns the original blob.',
    'predicted_inventory': predicted, 'prediction_not_actual_observation': True,
    'no_source_advance_result_reviewed_yet': True, 'no_maintenance_driver_v4_reviewed_yet': True,
    'review_note': 'An initial local checker stopped on an incorrect pretty-JSON formatting assumption before projection. This version first proves the original compact JSON serialization byte-identical; no native command or gate was involved.'
}
(root / 'STATIC_INPUT_REVIEW.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
