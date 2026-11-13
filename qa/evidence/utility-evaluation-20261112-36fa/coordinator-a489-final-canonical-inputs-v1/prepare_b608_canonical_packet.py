import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
D = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1')
N = Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-format-runtime-v1')
X = Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1')
C = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1')
OLD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
NEW = 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
OLD_TREE = 'a489b394666b8141840275128a780605b024cde0'
NEW_TREE = '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
REPO = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'

def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': typed('blob', raw)}

def typed(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def load(path, sha=None):
    raw = Path(path).read_bytes()
    if sha is not None:
        assert typed('blob', raw) == sha, str(path)
    return raw, json.loads(raw)

def summary(raw):
    value = json.loads(raw)
    assert value['tracked_entries'] == value['filesystem_entries'] == len(value['files']) == 15243
    assert all(row['stable'] is True for row in value['files'])
    return {**identity(raw), 'tracked_entries': value['tracked_entries'], 'filesystem_entries': value['filesystem_entries']}

def trees(rows):
    node = {}
    for row in rows:
        parts = row['path'].split('/')
        cur = node
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        assert parts[-1] not in cur
        cur[parts[-1]] = (row['mode'], row['git_blob'])
    result = {}
    def walk(node, path):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, sha = '40000', walk(value, path + '/' + name if path else name)
            else:
                mode, sha = value
            entries.append((name, mode, sha))
        entries.sort(key=lambda e: (e[0] + ('/' if e[1] == '40000' else '')).encode())
        raw = b''.join(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha) for name, mode, sha in entries)
        sha = typed('tree', raw)
        result[path] = {'sha': sha, 'raw': raw, 'entries': [{'path': n, 'mode': '040000' if m == '40000' else m, 'sha': s, 'type': 'tree' if m == '40000' else 'blob'} for n, m, s in entries]}
        return sha
    root = walk(node, '')
    return root, result

def object_record(kind, raw):
    return {'type': kind, 'sha': typed(kind, raw), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'raw_base64': base64.b64encode(raw).decode()}

D.mkdir(exist_ok=True)
before_raw, before = load(X / 'final.inventory.exact_recovered.json', 'e3ce3d7bba028e29efca751c6f43fde124b05ea0')
assert encode(before) == before_raw
base_raw, base = load('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/CANDIDATE_FILE_GRAPH.json', '097282896b5881614498faf2231e4c8c0da393c3')
projected_raw, projected = load(R / 'PROPOSED_NONRUST_8EBB_GRAPH.json', '7c515dbe48ae3ab42ccc85d916e38675db06ced2')
old_root, old_trees = trees(base['files'])
new_root, new_trees = trees(projected['files'])
assert old_root == OLD_TREE and new_root == NEW_TREE
base_rows = {r['path']: r for r in base['files']}
new_rows = {r['path']: r for r in projected['files']}
assert len(base_rows) == len(new_rows) == 15243 and base_rows.keys() == new_rows.keys()
for row in before['files']:
    assert row['index_blob'] == base_rows[row['path']]['git_blob'] and row['index_mode'] == base_rows[row['path']]['mode']
    assert row['working_blob'] == new_rows[row['path']]['git_blob']
changed = sorted(p for p in base_rows if base_rows[p] != new_rows[p])
assert len(changed) == 21
assert [p for p in changed if p.endswith('.rs')] == [p for p in changed if p.startswith('codex-rs/')]
after = copy.deepcopy(before)
after['source'] = {'head': NEW, 'tree': NEW_TREE, 'status': ''}
for row in after['files']:
    row['index_blob'] = row['working_blob']
    row['index_mode'] = new_rows[row['path']]['mode']
    row['matches_index'] = True
after_raw = encode(after)
assert summary(after_raw)['tracked_entries'] == 15243
for old_row, new_row in zip(before['files'], after['files']):
    strip = lambda r: {k: v for k, v in r.items() if k not in ['index_blob', 'index_mode', 'matches_index']}
    assert strip(old_row) == strip(new_row)
(D / 'EXPECTED_AFTER_INVENTORY.json').write_bytes(after_raw)

body_map = {}
for path in ['/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1/final.postimages.json', str(X / 'final.postimages.exact_recovered.json')]:
    _, transition = load(path)
    for c in transition['changes']:
        raw = base64.b64decode(c['after_raw_base64'], validate=True)
        assert typed('blob', raw) == c['after']['working_blob']
        assert c['path'] not in body_map
        body_map[c['path']] = raw
assert sorted(body_map) == changed
objects = []
object_index = []
for p in changed:
    raw = body_map[p]
    record = object_record('blob', raw)
    assert record['sha'] == new_rows[p]['git_blob'] and record['bytes'] == new_rows[p]['bytes'] and record['sha256'] == new_rows[p]['sha256']
    objects.append(record)
    object_index.append({'path': p, **{k: v for k, v in record.items() if k != 'raw_base64'}})
changed_trees = sorted(p for p, v in new_trees.items() if p not in old_trees or v['sha'] != old_trees[p]['sha'])
assert changed_trees == ['', '.github', 'codex-rs', 'codex-rs/hepta-agentd', 'codex-rs/hepta-agentd/src', 'qa', 'qa/b4-no-bypass']
for p in sorted(changed_trees, key=lambda p: (-p.count('/'), p)):
    record = object_record('tree', new_trees[p]['raw'])
    objects.append(record)
    object_index.append({'path': p, **{k: v for k, v in record.items() if k != 'raw_base64'}})
commit_raw = (R / 'FINAL_B6084394_COMMIT.raw').read_bytes()
assert typed('commit', commit_raw) == NEW
assert commit_raw.split(b'\n\n', 1)[0].splitlines()[:2] == [('tree ' + NEW_TREE).encode(), ('parent ' + OLD).encode()]
objects.append(object_record('commit', commit_raw))
object_index.append({'path': None, **{k: v for k, v in objects[-1].items() if k != 'raw_base64'}})
assert len(objects) == len({v['sha'] for v in objects}) == 29
git_raw, git_state = load(N / 'final.git-state.json', 'aef9e645b81c2a7f349b11d546c5555b1475c906')
packet = {'format': 'hepta-final-canonical-source-alignment-packet-v1', 'source_repo': REPO,
          'complete_leaf_count': 15243,
          'before': {'commit': OLD, 'tree': OLD_TREE, 'parents': ['cc57c7198db6293ccca562253c42fffbe2a04633'],
                     'inventory': summary(before_raw), 'git_state': git_state},
          'after': {'commit': NEW, 'tree': NEW_TREE, 'parents': [OLD], 'inventory': summary(after_raw)},
          'objects': objects}
packet_raw = encode(packet)
(D / 'CANONICAL_PACKET.json').write_bytes(packet_raw)
(D / 'CANONICAL_OBJECT_INDEX.json').write_bytes(encode(object_index))
_, config = load(C / 'WAITING_CONFIG.json')
config.update(status='ROOT_APPROVED_FOR_ONE_CANONICAL_ALIGNMENT', root_execution_approved=True,
              actual_final_postimages_reviewed=True, after_commit=NEW, after_tree=NEW_TREE, after_parents=[OLD],
              after_inventory=summary(after_raw), before_inventory=summary(before_raw),
              canonical_object_count=len(objects), canonical_packet=identity(packet_raw),
              expected_before_git_state=git_state, reviewed_formatter_changed_paths=[])
config['final_format'].update(git_state=identity(git_raw), job_id='1a1d4a979d9-392-50f',
                              result=identity((N / 'RESULT.json').read_bytes()),
                              supervisor=identity((N / 'STATUS_02.original.json').read_bytes()))
config_raw = encode(config)
(D / 'APPROVED_CONFIG.execution-candidate.json').write_bytes(config_raw)
representations = []
for name, raw in [('CANONICAL_PACKET.json', packet_raw), ('EXPECTED_AFTER_INVENTORY.json', after_raw)]:
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    (D / (name + '.gz')).write_bytes(packed)
    parts = []
    for i, offset in enumerate(range(0, len(packed), 307200), 1):
        block = packed[offset:offset + 307200]
        body = base64.b64encode(block) + b'\n'
        part_name = name + '.gz.part-%03d.b64' % i
        (D / part_name).write_bytes(body)
        parts.append({'name': part_name, **identity(body), 'decoded_offset': offset, 'decoded_bytes': len(block), 'decoded_sha256': hashlib.sha256(block).hexdigest()})
    representations.append({'name': name, 'raw': identity(raw), 'gzip': identity(packed), 'parts': parts})
(D / 'LOSSLESS_REPRESENTATIONS.json').write_bytes(encode(representations))
review = {'format': 'hepta-root-canonical-b608-input-binding-v1', 'status': 'CANDIDATE_INPUTS_READY_FOR_EXACT_LAUNCH_REVIEW',
          'actual_before_source_closure': '78f840361a7aea7d70f48f694f9f7dfdfbed547f',
          'actual_final_format_job': '1a1d4a979d9-392-50f', 'actual_old_commit': OLD, 'actual_old_index_tree': OLD_TREE,
          'actual_physical_tree': NEW_TREE, 'actual_created_commit': NEW, 'actual_commit_parents': [OLD],
          'packet': identity(packet_raw), 'config': identity(config_raw), 'before_inventory': summary(before_raw),
          'after_inventory_is_projection_only': summary(after_raw), 'clean_final_source_observed': False,
          'all_actual_physical_bytes_and_modes_preserved_in_projection': True, 'complete_leaves': 15243,
          'changed_source_paths_from_old_index': changed, 'supplied_objects': {'blobs': 21, 'trees': 7, 'commits': 1, 'total': 29},
          'new_tree_paths': changed_trees, 'old_new_membership_equal': True,
          'driver': identity((C / 'driver.HOLD.py').read_bytes()), 'budgets_seconds': {'action': 600, 'records': 180, 'outer': 900},
          'configuration_is_not_a_dispatch_approval': True, 'next_required': 'Independent exact packet/config/request review, then Root approval for one exact request.',
          'H_calls': 0, 'source_index_HEAD_or_ref_mutations': 0, 'qualification': False, 'real_qualified_chains': 0}
(D / 'ROOT_INPUT_BINDING_REVIEW.json').write_bytes(encode(review))
(D / 'TREE_INPUTS.json').write_bytes(encode({p: {'sha': new_trees[p]['sha'], 'entries': new_trees[p]['entries']} for p in changed_trees}))
print(json.dumps({'packet': identity(packet_raw), 'config': identity(config_raw), 'projected_inventory': summary(after_raw), 'objects': len(objects),
                  'packet_gzip_bytes': representations[0]['gzip']['bytes'], 'bounded_parts': sum(len(v['parts']) for v in representations), 'qualification': False}))
