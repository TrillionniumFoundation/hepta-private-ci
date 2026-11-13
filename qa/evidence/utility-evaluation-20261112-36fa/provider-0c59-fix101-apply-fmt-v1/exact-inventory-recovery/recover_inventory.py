#!/usr/bin/env python3
"""Pure reconstruction of already-observed inventories; no source or Git writes.

This does not execute the original inventory driver or read the native source.
The source.status candidate is derived under the unchanged-index/no-additions
transition and accepted only after all original raw/gzip/part identities match.
"""
import ast
import base64
import copy
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')
BASE = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1/ACTUAL_FINAL_INVENTORY.exact_recovered.json')
ORIGINAL = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1/staged-readback/inventory-driver.original.py')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check(raw, expected, label):
    actual = pin(raw)
    assert actual == {key: expected[key] for key in actual}, (label, actual, expected)
    return actual


def persist(name, raw):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, f'create-only existing bytes differ: {path}'
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'name': name, 'path': str(path), **pin(raw)}


def jbytes(value):
    # Exact return expression in original 51181866 inventory(), line 157.
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def merkle(rows, indexed=False):
    root = {}
    for row in rows:
        oid = row['index_blob'] if indexed else row['working_blob']
        mode = row['index_mode']
        assert mode in ('100644', '100755', '120000')
        path = row['path'].split('/')
        directory = root
        for component in path[:-1]:
            directory = directory.setdefault(component, {})
        assert path[-1] not in directory
        directory[path[-1]] = (mode, oid)

    def tree(directory):
        records = []
        for name, value in directory.items():
            if isinstance(value, dict):
                mode, oid, key = '40000', tree(value), name.encode() + b'/'
            else:
                mode, oid = value
                key = name.encode()
            records.append((key, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(oid)))
        raw = b''.join(row[1] for row in sorted(records))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

    return tree(root)


def strict_transition(value, packet, label):
    by_path = {row['path']: row for row in value['files']}
    assert len(by_path) == value['tracked_entries'] == value['filesystem_entries'] == 15237
    proofs = []
    paths = [row['path'] for row in packet['changes']]
    assert paths == sorted(set(paths))
    for change in packet['changes']:
        path = change['path']
        assert by_path[path] == change['before'], (label, path, 'entire before row')
        for side in ('before', 'after'):
            row = change[side]
            raw = base64.b64decode(change[side + '_raw_base64'], validate=True)
            actual = pin(raw)
            assert actual == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
            assert row['path'] == path and row['kind'] == 'file' and row['stable'] is True
            assert row['index_mode'] == '100644' and row['permissions'] == 420
            assert row['matches_index'] == (row['working_blob'] == row['index_blob'])
        before, after = change['before'], change['after']
        for key in ('path', 'kind', 'permissions', 'index_mode', 'index_blob', 'stable'):
            assert before[key] == after[key], (label, path, key)
        by_path[path] = copy.deepcopy(after)
        proofs.append({'path': path, 'before_blob': before['working_blob'],
                       'after': {'bytes': after['bytes'], 'sha256': after['sha256'], 'git_blob': after['working_blob']},
                       'entire_before_row_equal': True, 'both_complete_raw_contents_verified': True})
        if label == 'fmt':
            persist('actual-after/' + path, base64.b64decode(change['after_raw_base64'], validate=True))
    value['files'] = [by_path[path] for path in sorted(by_path)]
    # All original tracked paths and index modes/OIDs are preserved. There are no
    # additions, deletions, permission changes, ignored/untracked leaves or stages.
    dirty = [row['path'] for row in value['files'] if not row['matches_index']]
    candidate_status = '\n'.join(' M ' + path for path in dirty).strip()
    value['source']['status'] = candidate_status
    return proofs, dirty


def retained(raw, name, artifacts):
    entry = artifacts[name + '.gz']
    check(raw, {'bytes': entry['raw_bytes'], 'sha256': entry['raw_sha256'], 'git_blob': entry['raw_git_blob']}, name)
    packed = gzip.compress(raw, mtime=0)
    check(packed, entry, name + '.gz')
    outputs = [persist(name.replace('.json', '.exact_recovered.json'), raw), persist(name + '.gz', packed)]
    offset = 0
    for part in entry['parts']:
        assert part['decoded_offset'] == offset
        chunk = packed[offset:offset + part['decoded_bytes']]
        assert len(chunk) == part['decoded_bytes']
        assert hashlib.sha256(chunk).hexdigest() == part['decoded_sha256']
        encoded = base64.b64encode(chunk) + b'\n'
        check(encoded, part, part['name'])
        assert base64.b64decode(encoded.rstrip(b'\n'), validate=True) == chunk
        outputs.append(persist(part['name'], encoded))
        offset += len(chunk)
    assert offset == len(packed)
    return outputs


def main():
    original = ORIGINAL.read_bytes()
    check(original, {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2',
                     'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}, 'original serializer')
    source = original.decode()
    syntax = ast.parse(source)
    functions = {node.name: ast.get_source_segment(source, node) for node in syntax.body if isinstance(node, ast.FunctionDef)}
    assert 'sort_keys=True, separators=(",", ":")' in functions['inventory']
    assert '.decode().strip()' in functions['git']
    persist('inventory-driver.original.py', original)
    persist('ORIGINAL_SERIALIZER_EXCERPT.py', ('\n\n'.join(functions[name] for name in ('git', 'identity', 'inventory')) + '\n').encode())
    artifacts_raw = (RUNTIME / 'ARTIFACTS.json').read_bytes()
    artifacts = {row['name']: row for row in json.loads(artifacts_raw)['files']}
    result_raw = (RUNTIME / 'RESULT.json').read_bytes()
    check(result_raw, {'bytes': 26765, 'sha256': '45dcfb960717c209e89eb47d8cf1bb5ebf536ad7548198c1f621e0a754bab640',
                       'git_blob': '23c8f1375aa98a4c166a9ff4245d8500f060d97f'}, 'actual RESULT')
    result = json.loads(result_raw)
    assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
    assert result['fix_dispatched'] is False and result['qualification'] is False
    assert result['actual_final_source']['complete'] and result['application']['complete']
    base_raw = BASE.read_bytes()
    base_pin = check(base_raw, {'bytes': 5629749, 'sha256': 'b19022cb0957b760703a1193f20b0c2934738e68f7c0cf6956fab34468c41dfa',
                                'git_blob': 'd7e2e31df4c8d463b643874bdcd11309a1df02f4'}, 'actual recovered failed-fix base')
    value = json.loads(base_raw)
    assert jbytes(value) == base_raw
    assert value['source']['head'] == '0c59aaca0b4932507f068c723f73da2f96729b3d'
    assert value['source']['tree'] == '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
    assert merkle(value['files'], indexed=True) == value['source']['tree']
    assert merkle(value['files']) == '4ed32552042fee522965ea54caf95bbebb31ad43'
    assert [row['path'] for row in value['files'] if not row['matches_index']] == ['codex-rs/hepta-learning-ledger/src/witness.rs']
    assert all(row['kind'] in ('file', 'symlink') and row['stable'] and row['index_blob'] and row['index_mode'] for row in value['files'])
    sources = []
    stage_results = []
    output_entries = []
    for label, count, expected_tree, result_scope in (
        ('apply', 4, '1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1', result['application']),
        ('fmt', 62, 'f905b18e6b05de1582024548179725a05d932536', result['actual_final_source']),
    ):
        packet_raw = (RUNTIME / (label + '.after.postimages.json')).read_bytes()
        entry = artifacts[label + '.after.postimages.json.gz']
        check(packet_raw, {'bytes': entry['raw_bytes'], 'sha256': entry['raw_sha256'], 'git_blob': entry['raw_git_blob']}, label + ' actual packet')
        packet = json.loads(packet_raw)
        assert len(packet['changes']) == count
        assert packet['base_inventory_sha256'] == pin(jbytes(value))['sha256']
        assert packet['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
        proofs, dirty = strict_transition(value, packet, label)
        raw = jbytes(value)
        actual = check(raw, result_scope['inventory'], label + ' actual inventory')
        assert actual['sha256'] == packet['after_inventory_sha256']
        tree = merkle(value['files'])
        assert tree == expected_tree == result_scope['postimages']['all_actual_physical_tree']
        assert len(value['files']) == result_scope['postimages']['all_actual_physical_leaf_count'] == 15237
        assert merkle(value['files'], indexed=True) == value['source']['tree']
        outputs = retained(raw, label + '.after.inventory.json', artifacts)
        output_entries.extend(outputs)
        stage_results.append({'stage': label, 'complete_inventory': actual, 'physical_tree': tree,
                              'leaves': len(value['files']), 'dirty_paths': dirty, 'source': copy.deepcopy(value['source']),
                              'status_is_exact_recovered_not_separately_native_read': True,
                              'transition_count': count, 'transition_proofs': proofs,
                              'all_raw_gzip_and_parts_equal_original_artifacts': True})
        sources.append({'path': str(RUNTIME / (label + '.after.postimages.json')), **pin(packet_raw)})
    final_raw = jbytes(value)
    final_outputs = retained(final_raw, 'final.inventory.json', artifacts)
    output_entries.extend(final_outputs)
    assert len(stage_results[-1]['dirty_paths']) == 63
    assert stage_results[1]['complete_inventory'] == pin(final_raw)
    for name in ('apply.after.git-state.json', 'fmt.after.git-state.json', 'final.git-state.json'):
        raw = (RUNTIME / name).read_bytes()
        check(raw, artifacts[name], name)
        state = json.loads(raw)
        assert len(state) == 9 and 'status' not in state
        assert state['head'] == value['source']['head'] and state['tree'] == value['source']['tree']
    report = {'format': 'hepta-exact-recovered-original-inventory-v1',
              'status': 'EXACT_RECOVERY_ALL_OBSERVED_PINS_MATCH', 'qualification': False,
              'native_second_full_inventory_read': False, 'native_source_commands_executed_by_this_script': 0,
              'original_driver_was_executed': False, 'source_or_git_objects_refs_written': False,
              'basis': {'actual_failed_fix_base': {'path': str(BASE), **base_pin},
                        'actual_transition_packets': sources, 'actual_RESULT': {'path': str(RUNTIME / 'RESULT.json'), **pin(result_raw)},
                        'actual_ARTIFACTS': {'path': str(RUNTIME / 'ARTIFACTS.json'), **pin(artifacts_raw)},
                        'original_inventory_serializer': {'path': str(ORIGINAL), **pin(original)}},
              'status_reconstruction': 'Under a complete unchanged index and exhaustive no-addition/no-deletion/no-mode-change physical transition, derive sorted porcelain worktree-modified paths; apply the original git().decode().strip(). Accept only because complete raw byte count, SHA256 and Git blob, deterministic gzip and every original base64 part identity all match the actual producer ARTIFACTS. Nine-field git-state files do not contain source.status and are not described as such.',
              'stages': stage_results, 'final_mode_counts': dict(sorted(Counter(row['index_mode'] for row in value['files']).items())),
              'preserved_actual_witness': next(row for row in value['files'] if row['path'] == 'codex-rs/hepta-learning-ledger/src/witness.rs'),
              'final': {'path': str(HERE / 'final.inventory.exact_recovered.json'), **pin(final_raw),
                        'physical_tree': merkle(value['files']), 'leaf_count': len(value['files'])},
              'transport_failures': 'All original native read failures and retries remain in the producer runtime archive; this script does not replace, delete, retry or reclassify them.',
              'limits': 'Actual formatter success and bytes only. No semantic formatter review, lint success, compilation, gate/test qualification or real task-chain success is asserted.',
              'outputs': output_entries}
    persist('RECOVERY_REVIEW.json', (json.dumps(report, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({'review': pin((HERE / 'RECOVERY_REVIEW.json').read_bytes()), 'final': report['final'],
                      'stages': [{k: row[k] for k in ('stage','complete_inventory','physical_tree','transition_count')} for row in stage_results],
                      'mode_counts': report['final_mode_counts']}, sort_keys=True))


if __name__ == '__main__':
    main()
