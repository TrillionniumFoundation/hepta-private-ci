#!/usr/bin/env python3
"""Pure exact schema derivation. No project code, native execution, or source write."""
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path

OUT = Path(__file__).resolve().parent
PROPOSAL = Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1')
ACTUAL = Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1')
PREFIX = 'a489-maintenance-nonrust-apply-packet-v1/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

def put(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return pin(raw)

def merkle(rows):
    root = {}
    for row in rows:
        parts = row['path'].split('/')
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            assert isinstance(node, dict)
        assert parts[-1] not in node
        node[parts[-1]] = (row['index_mode'], row['working_blob'])
    def tree(node):
        entries = []
        for name, item in node.items():
            directory = isinstance(item, dict)
            mode, oid = ('40000', tree(item)) if directory else item
            entries.append((os.fsencode(name) + (b'/' if directory else b''),
                            mode.encode() + b' ' + os.fsencode(name) + b'\0' + bytes.fromhex(oid)))
        raw = b''.join(value for _, value in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return tree(root)

def main():
    proposal_raw = (PROPOSAL / 'SOURCE_PACKET.json').read_bytes()
    assert pin(proposal_raw) == {'bytes': 5999431, 'sha256': 'a197e68853035ea4dd46eae16b15d548ded6bccb1392f528a1cc9677ce0d0082', 'git_blob': 'b3490071b2b109aa1854afd3353952890b8e0eab'}
    proposal = json.loads(proposal_raw)
    actual_raw = (ACTUAL / 'final.inventory.exact_recovered.json').read_bytes()
    assert pin(actual_raw) == proposal['base_inventory'] == {'bytes': 5633323, 'sha256': '981e5971d3e8afc2694bcb1951b0261d24f0238675187005ec8e9bb386a07bf1', 'git_blob': '4a77b645fd76a980ef746997efbd09fcd8f233ba'}
    actual = json.loads(actual_raw)
    assert actual['source'] == proposal['source_identity']
    assert merkle(actual['files']) == proposal['base_physical_tree'] == 'c026a8d7e93c958b39a36c666debecb3dba4be14'
    rows = {row['path']: row for row in actual['files']}
    assert len(rows) == len(actual['files']) == 15243
    allowed = {row['path'] for row in proposal['all_seven_fence_bindings']}
    assert len(allowed) == 7
    paths = [row['path'] for row in proposal['changes']]
    assert len(paths) == len(set(paths)) == 4 and paths == sorted(paths, key=os.fsencode)
    expected = copy.deepcopy(rows)
    changes = []
    for item in proposal['changes']:
        path = item['path']
        assert path in allowed and path in rows and not path.endswith('.rs')
        before, after = item['before'], item['after']
        assert before == rows[path]
        assert before['index_mode'] == after['index_mode'] == '100644'
        assert before['kind'] == after['kind'] == 'file'
        assert before['permissions'] == after['permissions'] == 420
        before_raw = base64.b64decode(item['before_raw_base64'], validate=True)
        after_raw = base64.b64decode(item['after_raw_base64'], validate=True)
        before_pin, after_pin = pin(before_raw), pin(after_raw)
        for row, identity in ((before, before_pin), (after, after_pin)):
            assert identity == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
        assert before_raw != after_raw
        assert (PROPOSAL / 'before' / path).read_bytes() == before_raw
        assert (PROPOSAL / 'after' / path).read_bytes() == after_raw
        expected[path] = after
        changes.append({'path': path, 'mode': '100644', 'before': before_pin,
                        'after': after_pin, 'after_base64': item['after_raw_base64']})
    root = merkle(list(expected.values()))
    assert root == proposal['expected_after_physical_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
    packet = {'format': 'hepta-reviewed-nonrust-source-apply-v1',
              'source_identity': actual['source'], 'base_inventory': pin(actual_raw),
              'base_physical_tree': proposal['base_physical_tree'], 'changes': changes,
              'expected_after_leaf_count': len(expected), 'expected_after_physical_tree': root}
    raw = encode(packet)
    raw_pin = put('NONRUST_PACKET.json', raw)
    compressed = gzip.compress(raw, mtime=0)
    gzip_pin = put('NONRUST_PACKET.json.gz', compressed)
    parts = []
    rebuilt = b''
    for offset in range(0, len(compressed), 307200):
        chunk = compressed[offset:offset + 307200]
        encoded = base64.b64encode(chunk) + b'\n'
        name = 'NONRUST_PACKET.json.gz.part-%03d.b64' % (len(parts) + 1)
        identity = put(name, encoded)
        assert identity['bytes'] <= 512000
        decoded = base64.b64decode(encoded.rstrip(b'\n'), validate=True)
        assert decoded == chunk
        rebuilt += decoded
        parts.append({'name': name, 'path': PREFIX + name, 'local_path': str(OUT / name),
                      'chars': len(encoded), **identity, 'decoded_offset': offset, 'decoded': pin(chunk)})
    assert rebuilt == compressed and gzip.decompress(rebuilt) == raw
    review = {'format': 'hepta-strict-nonrust-schema-derivation-review-v1', 'status': 'HOLD_NOT_EXECUTED',
              'source_proposal_raw': pin(proposal_raw), 'actual_final_inventory': pin(actual_raw),
              'proposal_manifest_git': '4bc60fab145563469f1cbb992feeaf216d58dfb5',
              'source_object_full_readback_git': 'c0430074e5f2c8943600a9d7dd54ef59d924b741',
              'source_identity_exact_original_dictionary': True, 'seven_reviewed_paths': sorted(allowed),
              'exactly_four_unique_sorted_existing_paths': paths, 'source_bytes_changed_by_derivation': 0,
              'original_proposal_unchanged': True, 'base_physical_tree': proposal['base_physical_tree'],
              'expected_after_physical_tree': root, 'expected_after_leaf_count': len(expected),
              'packet': raw_pin, 'qualification': False, 'execution_approval': False,
              'H_calls': 0, 'project_or_QA_execution': 0, 'source_tree_commit_ref_mutations': 0,
              'note': 'Data-only adaptation to the original strict apply schema; the native successor must separately bind exact existing paths, complete actual receipts, live prerequisites and Root approval. The fixed existing provider contract JSON path requires an explicit allowed-path entry; no broad extension allowance is implied.'}
    review_pin = put('REVIEW.json', encode(review))
    manifest = {'format': 'hepta-bounded-nonrust-apply-packet-v1', 'status': 'HOLD_NOT_EXECUTED',
                'prefix': PREFIX, 'raw': raw_pin, 'gzip': gzip_pin, 'parts': parts,
                'encoding': 'gzip.compress(raw,mtime=0), level9; 307200 gzip bytes per canonical base64 plus LF leaf',
                'review': review_pin, 'qualified_or_executed': False, 'leaf_limit': 512000}
    manifest_pin = put('MANIFEST.json', encode(manifest))
    entries = []
    for name in ('REVIEW.json', 'MANIFEST.json', 'derive_nonrust_packet.py'):
        body = (OUT / name).read_bytes()
        entries.append({'name': name, 'path': PREFIX + name, 'local_path': str(OUT / name),
                        'chars': len(body.decode()), **pin(body)})
    entries.extend(parts)
    index = {'format': 'hepta-fixed-archive-inputs-v1', 'prefix': PREFIX, 'count': len(entries), 'entries': entries}
    index_pin = put('ARCHIVE_INPUT_INDEX.json', encode(index))
    print(json.dumps({'packet': raw_pin, 'gzip': gzip_pin, 'parts': parts, 'review': review_pin,
                      'manifest': manifest_pin, 'index': index_pin}, sort_keys=True))

if __name__ == '__main__':
    main()
