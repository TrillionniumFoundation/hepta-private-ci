"""Read-only verification of the five-file repair and its bounded fmt control."""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import tomllib

OUT = Path('/tmp/hepta-36fa-after2793-20261112')
PROPOSAL = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
CONTROL = Path('/tmp/hepta-36fa-source-repair-finalfmt-246d-v1')


def pin(raw):
    return {'bytes': len(raw), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
            'sha256': hashlib.sha256(raw).hexdigest()}


def merkle(leaves):
    root = {}
    for path, value in leaves.items():
        components = path.split('/')
        node = root
        for part in components[:-1]:
            node = node.setdefault(part, {})
        node[components[-1]] = value

    def walk(node):
        entries = []
        for name, value in node.items():
            mode, sha = ('40000', walk(value)) if isinstance(value, dict) else value
            entries.append((name, mode, sha))
        entries.sort(key=lambda row: (row[0] + ('/' if row[1] == '40000' else '')).encode())
        raw = b''.join(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
                       for name, mode, sha in entries)
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return walk(root)


def definitions(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    return {node.name: ''.join(lines[node.lineno - 1:node.end_lineno])
            for node in ast.parse(text).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def main():
    raw = (PROPOSAL / 'REPAIR_PACKET.json').read_bytes()
    packet = json.loads(raw)
    invraw = Path('/tmp/hepta-36fa-canonical-inventory-exact-recovery-v1/output/recovered/SOURCE.final.inventory.json').read_bytes()
    assert pin(invraw) == packet['base_inventory']
    inventory = json.loads(invraw)
    assert inventory['source'] == {'head': packet['base_commit'], 'tree': packet['base_tree'], 'status': ''}
    assert inventory['tracked_entries'] == inventory['filesystem_entries'] == 15188
    indexed = {row['path']: row for row in inventory['files']}
    assert len(indexed) == 15188 and all(row['stable'] and row['matches_index'] for row in indexed.values())
    leaves = {path: (row['index_mode'], row['working_blob']) for path, row in indexed.items()}
    assert merkle(leaves) == packet['base_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    paths = [row['path'] for row in packet['changes']]
    expected_paths = ['.github/blob-size-allowlist.txt', 'CALLERS.toml',
                      'qa/b4-no-bypass/test_original_circuit_observer_source_closure.py',
                      'qa/b4-no-bypass/test_original_selection_readback_source_closure.py',
                      'qa/b4-no-bypass/test_resident_root_source_closure.py']
    assert paths == expected_paths
    for row in packet['changes']:
        before = (PROPOSAL / 'source-before' / row['path']).read_bytes()
        after = (PROPOSAL / 'proposal-after' / row['path']).read_bytes()
        assert pin(before) == row['before'] and pin(after) == row['after']
        assert after == base64.b64decode(row['after_base64'], validate=True) and before != after
        original = indexed[row['path']]
        assert row['mode'] == original['index_mode'] == '100644' and original['permissions'] == 0o644
        assert original['working_blob'] == row['before']['git_blob']
        assert original['bytes'] == row['before']['bytes'] and original['sha256'] == row['before']['sha256']
        leaves[row['path']] = (row['mode'], row['after']['git_blob'])
    after_tree = merkle(leaves)
    assert after_tree == packet['expected_after_tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    assert len(leaves) == packet['expected_after_leaf_count'] == 15188

    old = tomllib.loads((PROPOSAL / 'source-before/CALLERS.toml').read_text())
    new = tomllib.loads((PROPOSAL / 'proposal-after/CALLERS.toml').read_text())
    reverted = copy.deepcopy(new)
    for index in [386, 387, 388]:
        assert new['protected_file'][index]['forbidden'] == old['protected_file'][index]['forbidden'] + ['recover_original_custody']
        reverted['protected_file'][index]['forbidden'].pop()
    assert reverted == old
    assert len(new['protected_file']) == 422 and len(new['boundary']) == 569
    assert all(value is False for value in new['authority'].values())
    allow_before = (PROPOSAL / 'source-before/.github/blob-size-allowlist.txt').read_bytes()
    allow_after = (PROPOSAL / 'proposal-after/.github/blob-size-allowlist.txt').read_bytes()
    assert allow_after.startswith(allow_before)
    addition = allow_after[len(allow_before):].decode()
    assert addition == ('\n# Original Trainer readonly adapters reject actual custody recovery; exact reviewed inventory.\n'
                        'sha256:13a03ff7b69506cac47dbf25d3803083ba0e750c72c31f9ce3c3519250dff3ec CALLERS.toml\n')

    method_changes = {}
    for path in expected_paths[2:]:
        before = (PROPOSAL / 'source-before' / path).read_bytes()
        after = (PROPOSAL / 'proposal-after' / path).read_bytes()
        def methods(data):
            text = data.decode(); lines = text.splitlines(keepends=True)
            return {node.name: ''.join(lines[node.lineno - 1:node.end_lineno])
                    for node in ast.walk(ast.parse(text))
                    if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}
        a, b = methods(before), methods(after)
        assert a.keys() == b.keys()
        method_changes[path] = [name for name in a if a[name] != b[name]]
    assert method_changes[expected_paths[2]] == [] and method_changes[expected_paths[4]] == []
    assert method_changes[expected_paths[3]] == ['test_wire_purpose_action_sequence_and_original_context_cannot_change']
    training = (PROPOSAL / 'source-before/qa/b4-no-bypass/test_original_training_readback_source_closure.py').read_bytes()
    assert pin(training)['git_blob'] == 'be8a1affafa0ee7b7180725ffc5d004b0a8f9f6b'

    previous = Path('/tmp/hepta-36fa-final-nonrust-fmt-v2/driver.HOLD.py').read_bytes()
    current = (CONTROL / 'driver.HOLD.py').read_bytes()
    assert pin(previous)['git_blob'] == '24d705376fe042f040d87b6a5fc72a67780b01fa'
    assert pin(current)['git_blob'] == '9101b44fb2ab24ae41a1344425dd74b536a40de4'
    a, b = definitions(previous), definitions(current)
    unchanged = ['identity', 'first_read', 'lock_identity', 'apply_packet', 'retain_terminal', 'main']
    assert all(a[name] == b[name] for name in unchanged)
    assert set(a) - set(b) == {'prove_actual_capture'} and set(b) - set(a) == {'prove_actual_clean_source'}
    assert {name for name in set(a) & set(b) if a[name] != b[name]} == {'module_from_original', 'prepare'}
    cfg = json.loads((CONTROL / 'WAITING_CONFIG.json').read_text())
    assert cfg['driver'] == pin(current) and cfg['allowed_paths'] == expected_paths
    assert (cfg['preflight_seconds'], cfg['fmt_seconds'], cfg['record_seconds'], cfg['outer_seconds']) == (600, 900, 300, 2100)
    assert cfg['fix_authorized'] is cfg['test_commands_authorized'] is cfg['ref_updates_authorized'] is False
    assert cfg['root_execution_approved'] is False and cfg['nonrust_packet'] is None

    result = {'format': 'hepta-root-source-repair-static-candidate-review-v1',
              'source': packet['base_commit'], 'base_tree': packet['base_tree'], 'base_inventory': pin(invraw),
              'proposal': pin(raw), 'five_paths': paths, 'expected_after_tree': after_tree,
              'leaf_count': len(leaves), 'all_five_preimages_match_actual_full_inventory': True,
              'all_five_postimages_match_packet': True, 'only_toml_change': 'append recover_original_custody to three existing forbidden lists',
              'old_forbidden_marker_order_preserved': True, 'unchanged_boundary_count': 569,
              'unchanged_protected_row_count': 422, 'all_authority_flags_still_false': True,
              'old_training_test_unchanged': pin(training), 'QA_method_changes': method_changes,
              'all_test_method_names_preserved': True, 'allowlist_change_exact_sha_append_only': True,
              'driver': pin(current), 'old_driver': pin(previous), 'unchanged_control_functions': unchanged,
              'source_failed_status_retained_in_control': True, 'runtime_control_is_historical_v5_not_relabelled_source': True,
              'budgets': {'preflight': 600, 'fmt': 900, 'record': 300, 'outer': 2100},
              'actual_H_execution': False, 'qualification': False, 'real_qualified_task_chains': 0,
              'approval': 'STATIC_REVIEW_ONLY_PENDING_ORIGINAL_SCHEMA_APPLY_PACKET_AND_EXACT_REQUEST'}
    (OUT / 'ROOT_SOURCE_REPAIR_STATIC_REVIEW.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
