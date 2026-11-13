#!/usr/bin/env python3
"""Pure offline byte preservation and source-graph derivation; no Rust or native execution."""
from pathlib import Path
import base64
import copy
import difflib
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')
GRAPH = Path('/tmp/hepta-36fa-full-candidate-graph-v1/CANDIDATE_FILE_GRAPH.json')
INVENTORY = Path('/tmp/hepta-36fa-full-candidate-graph-v1/expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()

def save(name, raw):
    p = ROOT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        assert p.read_bytes() == raw, name
    else:
        p.write_bytes(raw)
    return pin(raw)

def merkle(rows):
    root = {}
    for row in rows:
        parent = root
        components = row['path'].split('/')
        assert all(components)
        for component in components[:-1]:
            parent = parent.setdefault(component, {})
        assert components[-1] not in parent
        parent[components[-1]] = (row['mode'], row['git_blob'])
    def one(node):
        body = bytearray()
        for name in sorted(node, key=lambda n: (n + ('/' if isinstance(node[n], dict) else '')).encode()):
            value = node[name]
            if isinstance(value, dict):
                mode, oid = '40000', one(value)
            else:
                mode, oid = value
            body.extend(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(oid))
        return hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    return one(root)

actual = json.loads((ROOT / 'actual_inputs/RESULT.json').read_bytes())
terminal = json.loads((ROOT / 'actual_inputs/fix.terminal.json').read_bytes())
post = json.loads((ROOT / 'actual_inputs/final.postimages.json').read_bytes())
assert terminal['execution']['returncode'] == 101
assert terminal['execution']['timed_out'] is False
assert terminal['execution']['output_limit_exceeded'] is False
assert len(post['changes']) == 1
witness = post['changes'][0]
witness_path = 'codex-rs/hepta-learning-ledger/src/witness.rs'
assert witness['path'] == witness_path
actual_tree = terminal['retention']['postimages']['all_actual_physical_tree']
assert actual_tree == '4ed32552042fee522965ea54caf95bbebb31ad43'

original_rows = json.loads((ROOT / 'ORIGINAL_FOUR_SOURCE_PINS.json').read_bytes())
changes = []
patch = []
for original in sorted(original_rows, key=lambda r: r['path'].encode()):
    path = original['path']
    before = (ROOT / 'before' / path).read_bytes()
    after = (ROOT / 'after' / path).read_bytes()
    assert pin(before) == {k: original[k] for k in ('bytes', 'sha256', 'git_blob')}
    assert before != after
    changes.append({'path': path, 'mode': original['mode'], 'before': pin(before), 'after': pin(after),
                    'before_text': before.decode(), 'after_text': after.decode()})
    patch.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                                    fromfile='a/' + path, tofile='b/' + path))

inverses = []
for row in changes:
    before, after = row['before_text'], row['after_text']
    if row['path'].endswith('first_material_support_tests.rs'):
        restored = after.replace('use wire::encode_original_report;', 'pub(super) use wire::encode_original_report;', 1)
    elif row['path'].endswith('provider_transport_tests.rs'):
        restored = after
        for old, new in reversed(json.loads((ROOT / 'TRANSPORT_REPLACEMENTS.json').read_bytes())):
            assert restored.count(new) == 1
            restored = restored.replace(new, old, 1)
    else:
        replacement = next(r for r in json.loads((ROOT / 'INPUT_COMPARISON_REPLACEMENTS.json').read_bytes()) if r['path'] == row['path'])
        assert after.count(replacement['new']) == 1
        restored = after.replace(replacement['new'], replacement['old'], 1)
    assert restored == before
    row['full_inverse_equal'] = True
    inverses.append({'path': row['path'], 'whole_before_byte_equal_after_exact_inverse': True})

wb = base64.b64decode(witness['before_raw_base64'], validate=True)
wa = base64.b64decode(witness['after_raw_base64'], validate=True)
assert pin(wb)['git_blob'] == witness['before']['working_blob']
assert pin(wa)['git_blob'] == witness['after']['working_blob']
assert wa == (ROOT / 'after' / witness_path).read_bytes()
carried = {'path': witness_path, 'mode': '100644', 'before': pin(wb), 'after': pin(wa),
           'before_text': wb.decode(), 'after_text': wa.decode(),
           'origin': 'Actual fix postimage, preserved verbatim; no manual edit in this repair.'}

# Reconstruct the already-observed inventory from the exact materialized base,
# the actual complete postimage row, and the original 5118 compact serializer.
# Only exact equality with the actual three identities licenses the recovery name.
base_raw = INVENTORY.read_bytes()
assert pin(base_raw) == {'bytes': 5629701,
    'sha256': 'affce692432a4fa61521561e6717a84984f679f3535190b6b88c92cb0f725f44',
    'git_blob': 'a596ae68859e3263a9ee58e2b5d7334ac9314c34'}
inventory = json.loads(base_raw)
index = {r['path']: i for i, r in enumerate(inventory['files'])}
assert inventory['files'][index[witness_path]] == witness['before']
inventory['files'][index[witness_path]] = witness['after']
inventory['source']['status'] = (' M ' + witness_path + '\n').strip()
recovered = (json.dumps(inventory, sort_keys=True, separators=(',', ':')) + '\n').encode()
assert pin(recovered) == terminal['retention']['inventory']
inventory_pin = save('ACTUAL_FINAL_INVENTORY.exact_recovered.json', recovered)
for row in changes:
    observed = inventory['files'][index[row['path']]]
    assert {'bytes': observed['bytes'], 'sha256': observed['sha256'], 'git_blob': observed['working_blob']} == row['before']
    assert observed['matches_index'] is True and observed['index_mode'] == row['mode']

graph = json.loads(GRAPH.read_bytes())['files']
assert merkle(graph) == '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
by_path = {r['path']: copy.deepcopy(r) for r in graph}
by_path[witness_path].update(pin(wa))
assert merkle(list(by_path.values())) == actual_tree
for row in changes:
    by_path[row['path']].update(row['after'])
expected_tree = merkle(list(by_path.values()))

packet = {
    'format': 'hepta-actual-fix101-minimal-source-repair-proposal-v1',
    'status': 'FROZEN_LOCAL_PROPOSAL_PENDING_INDEPENDENT_REVIEW_AND_ROOT_APPROVAL',
    'source_identity': inventory['source'],
    'actual_maintenance_job': '1a1d3eccd3a-392-231',
    'actual_baseline_inventory': inventory_pin,
    'actual_baseline_physical_tree': actual_tree,
    'expected_successor_physical_tree': expected_tree,
    'expected_leaf_count': len(by_path),
    'qualification': {'rust_compile': 'NOT_RUN_ON_REPAIR', 'fix': 'ORIGINAL_FAILED_101_NO_RETRY_AUTHORIZED',
                      'fmt': 'NOT_RUN', 'source_gates': 'NOT_RUN_ON_REPAIR', 'native_tests': 'NOT_RUN_ON_REPAIR',
                      'actual_task_chain_completions': 0},
    'changes': changes,
    'preserved_actual_fix_postimages': [carried],
    'source_deletions': [],
    'scope': 'Four test/support sources repair six actual compiler errors. The actual witness.rs fix is preserved. No coordinator source, authority implementation, production peer type, owner, UID guard, budget, or execution control is changed.'
}
packet_pin = save('SOURCE_PACKET.json', encoded(packet))
patch_pin = save('REPAIR_DELTA.patch', ''.join(patch).encode())
recovery = {
    'format': 'hepta-exact-inventory-recovery-from-actual-postimages-v1',
    'classification': 'Exact recovered original inventory; not a second native full read.',
    'base_inventory': pin(base_raw),
    'actual_postimage_packet': pin((ROOT / 'actual_inputs/final.postimages.json').read_bytes()),
    'actual_terminal': pin((ROOT / 'actual_inputs/fix.terminal.json').read_bytes()),
    'observed_target': terminal['retention']['inventory'],
    'recovered': inventory_pin,
    'all_three_observed_identities_equal': True,
    'original_serializer': "(json.dumps(inventory, sort_keys=True, separators=(',', ':')) + '\\n').encode()",
    'original_porcelain_processing': "subprocess.check_output(...).decode().strip()",
    'changes': [witness_path],
    'all_four_error_sources_equal_0c59_and_actual_final_rows': True,
    'actual_root_merkle_equal': actual_tree,
    'expected_repair_root_merkle': expected_tree,
    'expected_repair_tree_is_not_native_observation': True,
    'file_count': len(by_path)
}
save('EXACT_INVENTORY_RECOVERY.json', encoded(recovery))
save('EXACT_INVERSE_REVIEW.json', encoded({'changes': inverses, 'all_four_inverse_equal': True,
    'new_functions': 0, 'removed_functions': 0, 'rust_or_qa_execution': False}))
save('SOURCE_MAP.json', encoded({'format': 'hepta-reviewed-source-overlay-v1', 'status': 'PREPARED_NOT_APPLIED',
    'base_head': inventory['source']['head'], 'base_commit_tree': inventory['source']['tree'],
    'actual_baseline_physical_tree': actual_tree, 'expected_successor_physical_tree': expected_tree,
    'canonical_deletions': [], 'files': [
        {'path': r['path'], 'mode': r['mode'], **r['after'],
         'change_origin': 'manual_compile_repair' if r in changes else 'preserved_actual_fix'}
        for r in sorted(changes + [carried], key=lambda r: r['path'].encode())]}))
print(json.dumps({'packet': packet_pin, 'patch': patch_pin, 'actual_inventory': inventory_pin,
                  'actual_physical_tree': actual_tree, 'expected_successor_physical_tree': expected_tree,
                  'repair_paths': len(changes), 'preserved_actual_paths': 1, 'files': len(by_path)}, indent=2))
