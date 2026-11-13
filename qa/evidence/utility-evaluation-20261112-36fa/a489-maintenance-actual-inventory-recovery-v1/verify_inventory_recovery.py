#!/usr/bin/env python3
"""Replay captured source transitions as data; never invoke Git, a gate, or H."""
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path

OUT = Path(__file__).resolve().parent
RUNTIME = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
BASE = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json')
ORIGINAL = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-staging-archive-v1/originals/native-readback/inventory-driver.original.py')
PREFIX = 'a489-maintenance-actual-inventory-recovery-v1/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def js(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

def put(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return pin(raw)

def merkle(files):
    root = {}
    for row in files:
        node = root
        parts = row['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (row['index_mode'], row['working_blob'])
    def walk(node):
        entries = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, oid = ('40000', walk(value)) if directory else value
            entries.append((os.fsencode(name) + (b'/' if directory else b''),
                            mode.encode() + b' ' + os.fsencode(name) + b'\0' + bytes.fromhex(oid)))
        raw = b''.join(value for _, value in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return walk(root)

def serialize(original, rows):
    value = copy.deepcopy(original)
    value['files'] = [rows[path] for path in sorted(rows, key=os.fsencode)]
    dirty = [row['path'] for row in value['files'] if row['working_blob'] != row['index_blob']]
    value['source']['status'] = ''.join(' M ' + path + '\n' for path in dirty).strip()
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()

def main():
    source = ORIGINAL.read_bytes()
    assert pin(source)['git_blob'] == '51181866cbbb6e0176aab04117efffa8b6792b31'
    module = ast.parse(source.decode())
    inventory = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'inventory')
    serializer_return = ast.get_source_segment(source.decode(), inventory.body[-1])
    assert serializer_return == 'return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\\n").encode()'
    put('ORIGINAL_INVENTORY_DRIVER_5118.py', source)
    base_raw = BASE.read_bytes()
    assert pin(base_raw) == {'bytes': 5631947, 'sha256': '0463522b45970d8ae9dbf5f4560e1b15e61768ec7c9ec164848019009c4643f0', 'git_blob': 'f1e2d72f99093581403a2dcc91b55da22a33f905'}
    original = json.loads(base_raw)
    assert original['source'] == {'head': 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f', 'tree': 'a489b394666b8141840275128a780605b024cde0', 'status': ''}
    assert len(original['files']) == 15243 and merkle(original['files']) == original['source']['tree']
    rows = {row['path']: row for row in original['files']}
    before_rows = copy.deepcopy(rows)
    before_raw = base_raw
    recovered = {pin(base_raw)['sha256']: base_raw}
    chains = []
    for stage, count in [('fix.after', 12), ('fmt.after', 14)]:
        raw = (RUNTIME / (stage + '.postimages.json')).read_bytes()
        packet = json.loads(raw)
        assert packet['base_inventory_sha256'] == pin(before_raw)['sha256']
        assert packet['source_commit_unchanged'] == original['source']['head']
        assert len(packet['changes']) == count
        seen = set()
        for item in packet['changes']:
            path = item['path']
            assert path not in seen and item['before'] == rows[path]
            seen.add(path)
            for side in ('before', 'after'):
                body = base64.b64decode(item[side + '_raw_base64'], validate=True)
                row = item[side]
                assert pin(body) == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
                assert row['index_mode'] == '100644' and row['kind'] == 'file' and row['permissions'] == 420
            rows[path] = item['after']
        after_raw = serialize(original, rows)
        assert pin(after_raw)['sha256'] == packet['after_inventory_sha256']
        recovered[pin(after_raw)['sha256']] = after_raw
        chains.append({'stage': stage, 'packet': pin(raw), 'before_inventory': pin(before_raw),
                       'after_inventory': pin(after_raw), 'change_count': count, 'physical_tree': merkle(list(rows.values()))})
        put(stage + '.inventory.exact_recovered.json', after_raw)
        before_raw = after_raw
    final = json.loads((RUNTIME / 'final.postimages.json').read_bytes())
    changed = {path for path in rows if rows[path] != before_rows[path]}
    assert len(changed) == len(final['changes']) == 17
    assert changed == {item['path'] for item in final['changes']}
    for item in final['changes']:
        assert item['before'] == before_rows[item['path']] and item['after'] == rows[item['path']]
        for side in ('before', 'after'):
            body = base64.b64decode(item[side + '_raw_base64'], validate=True)
            assert pin(body) == {'bytes': item[side]['bytes'], 'sha256': item[side]['sha256'], 'git_blob': item[side]['working_blob']}
    assert pin(before_raw) == {'bytes': 5633323, 'sha256': '981e5971d3e8afc2694bcb1951b0261d24f0238675187005ec8e9bb386a07bf1', 'git_blob': '4a77b645fd76a980ef746997efbd09fcd8f233ba'}
    assert merkle(list(rows.values())) == 'c026a8d7e93c958b39a36c666debecb3dba4be14'
    put('final.inventory.exact_recovered.json', before_raw)
    artifacts_raw = (RUNTIME / 'ARTIFACTS.json').read_bytes()
    assert pin(artifacts_raw)['git_blob'] == '222eb4e2913d62cdd308e2ce26edf7c320ebe47f'
    artifacts = json.loads(artifacts_raw)
    all_records = {row['name']: row for row in artifacts['files']}
    aliases, leaves = [], []
    for record in artifacts['files']:
        raw = recovered.get(record.get('raw_sha256'))
        if raw is None:
            continue
        assert pin(raw) == {'bytes': record['raw_bytes'], 'sha256': record['raw_sha256'], 'git_blob': record['raw_git_blob']}
        compressed = gzip.compress(raw, mtime=0)
        assert pin(compressed) == {key: record[key] for key in ('bytes', 'sha256', 'git_blob')}
        rebuilt = b''
        for number, part in enumerate(record['parts']):
            assert part == all_records[part['name']]
            offset = number * 262144
            chunk = compressed[offset:offset + 262144]
            encoded = base64.b64encode(chunk) + b'\n'
            assert pin(encoded) == {key: part[key] for key in ('bytes', 'sha256', 'git_blob')}
            assert (offset, len(chunk), hashlib.sha256(chunk).hexdigest()) == (part['decoded_offset'], part['decoded_bytes'], part['decoded_sha256'])
            rebuilt += base64.b64decode(encoded.rstrip(b'\n'), validate=True)
            if record['name'] in ('fix.after.inventory.json.gz', 'final.inventory.json.gz'):
                put(part['name'], encoded)
                leaves.append({'name': part['name'], 'path': PREFIX + part['name'], 'local_path': str(OUT / part['name']), 'chars': len(encoded), **pin(encoded)})
        assert rebuilt == compressed and gzip.decompress(rebuilt) == raw
        aliases.append({'artifact': record, 'raw': pin(raw), 'all_raw_gzip_part_pins_equal': True})
    assert len(aliases) == 7 and sum(len(a['artifact']['parts']) for a in aliases) == 35
    review = {'format': 'hepta-actual-41e-inventory-exact-recovery-v1', 'status': 'EXACT_RECOVERY_MATCHED_ALL_ACTUAL_IDENTITIES',
              'actual_result': 'b87aed7647ac34e3db0e381110bf685438aee0ee', 'actual_artifacts': pin(artifacts_raw),
              'original_serializer': {'driver': pin(source), 'exact_return': serializer_return},
              'preheld_initial_inventory': pin(base_raw), 'preheld_initial_bounded_placement': '88ad362796481f768cde7953c9c9485719c04591',
              'earlier_materializer_actual_identity_recovery_placement': '8fbeefd451f81b06ca783e69559b0296cdbfc082',
              'chains': chains, 'final_inventory': pin(before_raw), 'final_physical_tree': merkle(list(rows.values())),
              'filesystem_entries': len(rows), 'actual_final_transition_count': len(changed),
              'unchanged_source_rows': len(rows) - len(changed), 'aliases': aliases,
              'source_status_provenance': 'Unique tracked-modification porcelain candidate using original stdout.strip; accepted only when the entire original raw, gzip and all part identities match. Not a separately read native status response.',
              'not_a_second_native_full_inventory_read': True, 'raw_index_or_stat_reconstructed': False,
              'qualification': False, 'tests_or_project_gates': 0, 'H_calls': 0, 'source_tree_commit_ref_changes': 0,
              'local_preparation_attempt': 'Original isolated pretty-serializer assertion failure is retained as LOCAL_SERIALIZER_ATTEMPT_01.json in the source proposal archive. It was rejected before any native claim; compact original serialization is the only accepted recovery.'}
    review_pin = put('REVIEW.json', js(review))
    manifest = {'format': 'hepta-bounded-actual-inventory-recovery-v1', 'prefix': PREFIX, 'review': review_pin,
                'leaf_limit': 512000, 'raws': [chains[0]['after_inventory'], pin(before_raw)],
                'parts': leaves, 'all_aliases': [a['artifact']['name'] for a in aliases],
                'two_complete_raws_preserved': True, 'not_native_read': True}
    manifest_pin = put('MANIFEST.json', js(manifest))
    entries = []
    for name in ('REVIEW.json', 'MANIFEST.json', 'verify_inventory_recovery.py', 'ORIGINAL_INVENTORY_DRIVER_5118.py'):
        raw = (OUT / name).read_bytes()
        entries.append({'name': name, 'path': PREFIX + name, 'local_path': str(OUT / name), 'chars': len(raw.decode()), **pin(raw)})
    entries.extend(leaves)
    assert all(row['bytes'] <= 512000 for row in entries)
    index = {'format': 'hepta-fixed-archive-inputs-v1', 'prefix': PREFIX, 'count': len(entries), 'entries': entries}
    index_pin = put('ARCHIVE_INPUT_INDEX.json', js(index))
    print(json.dumps({'review': review_pin, 'manifest': manifest_pin, 'index': index_pin, 'entries': len(entries), 'final_inventory': pin(before_raw)}))

if __name__ == '__main__':
    main()
