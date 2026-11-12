#!/usr/bin/env python3
"""Offline peer verification; no native reads, source writes, or extractor main."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAP = Path('/tmp/hepta-36fa-postformat-capture-launch-v1')
INV = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def read_json(path):
    raw = path.read_bytes()
    return raw, json.loads(raw)

def put(name, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    with (HERE / name).open('xb') as f:
        f.write(raw)
    return identity(raw)

def physical_tree(rows):
    root = {}
    for row in rows:
        pieces = row['path'].split('/')
        assert pieces and all(part not in ('', '.', '..') for part in pieces)
        cursor = root
        for part in pieces[:-1]:
            cursor = cursor.setdefault(part, {})
            assert isinstance(cursor, dict)
        assert pieces[-1] not in cursor
        mode = ('120000' if row['kind'] == 'symlink' else
                '100755' if row['permissions'] & 0o111 else '100644')
        cursor[pieces[-1]] = (mode, row['working_blob'])
    def digest(node):
        items = []
        for name, value in node.items():
            if isinstance(value, dict):
                items.append((name.encode() + b'/', b'40000', name.encode(), digest(value)))
            else:
                mode, sha = value
                items.append((name.encode(), mode.encode(), name.encode(), sha))
        raw = b''.join(mode + b' ' + name + b'\0' + bytes.fromhex(sha)
                       for _, mode, name, sha in sorted(items))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return digest(root)

def main():
    packet_raw, packet = read_json(CAP / 'ACTUAL_73_FILES.json')
    assert identity(packet_raw) == {'bytes': 3018618,
        'sha256': '44477f7ce5ec90f2d052911745fb3b244111155a9539a22365c545b47e86c9a1',
        'git_blob_sha': '1399f73925ee43aff84829c9ae681d0bde017e1e'}
    compressed = (CAP / 'ACTUAL_73_FILES.json.gz').read_bytes()
    assert identity(compressed) == {'bytes': 626888,
        'sha256': '760d8a79a868c3980baccfa45937701897852290d5e11a2aa07118f47f889df5',
        'git_blob_sha': '711f4f90220c228850023947792cb407d156c6f8'}
    assert gzip.decompress(compressed) == packet_raw
    inv_raw, inventory = read_json(INV)
    assert identity(inv_raw) == {'bytes': 5614211,
        'sha256': '3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f',
        'git_blob_sha': '1563de8825fc183d345d10d03e68d79b2d9211ca'}
    assert len(inventory['files']) == inventory['filesystem_entries'] == inventory['tracked_entries'] == 15188
    assert all(row['stable'] is True for row in inventory['files'])
    physical = physical_tree(inventory['files'])
    assert physical == packet['actual_physical_tree'] == '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
    baseline_raw, contract = read_json(HERE / 'EXTRACTOR_CONTRACT_V5_PENDING_SHARED_CAPTURE.json')
    assert identity(baseline_raw)['git_blob_sha'] == 'f3ea30b1e45df3e201a0c7834e0b09a81874caa6'
    assert inventory['source'] == packet['source_identity'] == contract['source_identity']
    assert contract['complete_source_inventory'] == identity(inv_raw)
    rows = {row['path']: row for row in inventory['files']}
    expected_paths = set()
    for group in packet['groups'].values():
        assert group['count'] == len(group['paths'])
        assert not (expected_paths & set(group['paths']))
        expected_paths.update(group['paths'])
    assert len(expected_paths) == len(packet['files']) == 73
    assert {row['path'] for row in packet['files']} == expected_paths
    checked = []
    for row in packet['files']:
        path = row['path']
        original = rows[path]
        raw = base64.b64decode(row['content_base64'], validate=True)
        meta = identity(raw)
        assert meta == {key: row[key] for key in meta}
        assert original == row['original_inventory_row']
        assert original['working_blob'] == meta['git_blob_sha']
        assert original['bytes'] == meta['bytes'] and original['sha256'] == meta['sha256']
        assert original['permissions'] == row['permissions']
        assert original['kind'] == row['kind'] == 'file' and row['stable'] is True
        assert row['mode'] == ('100755' if row['permissions'] & 0o111 else '100644')
        assert (HERE / 'source_view' / path).read_bytes() == raw
        if path in contract['formatted_source_pins']:
            assert meta == {key: contract['formatted_source_pins'][path][key] for key in meta}
        checked.append({'path': path, **meta, 'mode': row['mode'],
                        'matches_full_inventory': True, 'matches_independent_review_bytes': True})
    assert set(contract['formatted_source_pins']) == set(packet['groups']['formatted_rust_scope']['paths'])
    result_raw, result = read_json(CAP / 'RESULT.json')
    assert identity(result_raw)['git_blob_sha'] == 'aef06c019dd96f2a8e493fa524e09183a4b215bf'
    assert result['status'] == 'CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED'
    assert result['captured_paths'] == 73 and result['source_changed'] is False
    assert result['source_write_authorized'] is False and result['extractor_executed'] is False
    assert result['tests_dispatched'] == 0 and result['qualification'] is False
    assert result['source_identity'] == inventory['source']
    assert all(audit['status'] == 'verified' for audit in result['final_audits'])
    normal_raw, normal_sdk = read_json(CAP / 'STATUS_01.original.json')
    normal = json.loads(normal_sdk['content'][0]['text'])
    assert normal['job_id'] == '1a1d1880477-2564-1c56'
    assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
    assert normal['timed_out'] is False and normal['automatic_retry'] is False
    assert normal['output_complete'] is True and normal['output_durable'] is True
    sh_raw, shared = read_json(CAP / 'SOURCE_COORDINATION_SH.json')
    ex_raw, exclusive = read_json(Path('/tmp/hepta-36fa-maintenance-v5-launch/SOURCE_COORDINATION_EX_V5.json'))
    for key in ('path', 'device', 'inode', 'uid', 'mode', 'nlink'):
        assert shared[key] == exclusive[key]
    assert shared['lock_acquired'] == 'LOCK_SH|LOCK_NB'
    assert exclusive['lock_acquired'] == 'LOCK_EX|LOCK_NB'
    assert shared['path'] == contract['source_lock_path']
    git_before = (CAP / 'GIT_BEFORE.json').read_bytes()
    git_after = (CAP / 'GIT_AFTER.json').read_bytes()
    assert git_before == git_after
    artifacts = {row['name']: row for row in result['artifacts']}
    for name in ('SOURCE_COORDINATION_SH.json',):
        raw = (CAP / name).read_bytes()
        meta = identity(raw)
        expected = artifacts[name]
        assert meta['bytes'] == expected['bytes'] and meta['sha256'] == expected['sha256']
        assert meta['git_blob_sha'] == expected['git_blob']
    report = {
        'format': 'hepta-postformat-actual-capture-offline-peer-v1',
        'status': 'verified_actual_capture_inputs_requires_root_review',
        'qualification': False, 'native_actions_performed': 0, 'extractor_main_executed': False,
        'capture_packet': identity(packet_raw), 'capture_packet_gzip': identity(compressed),
        'capture_result': identity(result_raw), 'capture_normal_sdk': identity(normal_raw),
        'shared_lease': identity(sh_raw), 'maintenance_exclusive_lease': identity(ex_raw),
        'git_before': identity(git_before), 'git_after': identity(git_after), 'git_byte_equal': True,
        'complete_inventory': identity(inv_raw), 'physical_tree': physical, 'leaf_count': 15188,
        'complete_inventory_provenance': 'exact recovered original matching observed raw/gzip/parts; not a second native full read',
        'captured_files_provenance': 'actual successful native SH capture, stable fixed-version complete packet readback',
        'independent_review_bytes_provenance': '34 actual fmt postimages plus 39 exact unchanged Git blobs; now byte-equal to all 73 actual SH reads',
        'source_identity': inventory['source'], 'paths': checked,
        'cooperative_lock_limit': 'same task-owned inode coordinates this task participating writers only; complete source and Git before/after remain mandatory',
        'original_full_gate_or_real_A_B_C_claimed': False,
    }
    review_meta = put('ACTUAL_SHARED_CAPTURE_PEER_REVIEW.json', report)
    contract['status'] = 'WAITING_ROOT_REVIEW_ACTUAL_SHARED_CAPTURE_VERIFIED'
    contract['root_review_blob'] = None
    actual = contract['actual_maintenance']
    actual['shared_capture_observed'] = True
    actual['shared_capture_result'] = {**identity(result_raw),
        'path': '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/postformat-handoff-v5-v1/RESULT.json'}
    actual['shared_capture'] = {
        'job_id': normal['job_id'], 'normal_sdk': identity(normal_raw),
        'source_lock_shared_lease': {**identity(sh_raw),
            'path': '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/postformat-handoff-v5-v1/SOURCE_COORDINATION_SH.json'},
        'packet': identity(packet_raw), 'packet_gzip': identity(compressed),
        'git_before': identity(git_before), 'git_after': identity(git_after),
        'independent_offline_review': review_meta,
        'actual_paths_verified': 73, 'source_write_authorized': False,
        'extractor_executed': False, 'root_approval_pending': True,
    }
    contract['instructions'][0] = 'Actual V5 and SH73 records are bound. This remains non-executable until Root independently reviews these inputs and supplies its exact review identity and the enabling status.'
    contract_meta = put('EXTRACTOR_CONTRACT_V5_PENDING_ROOT_REVIEW.json', contract)
    print(json.dumps({'review': review_meta, 'contract': contract_meta,
                      'paths_verified': 73, 'physical_tree': physical,
                      'root_approval_pending': True, 'extractor_executed': False}, sort_keys=True))

if __name__ == '__main__':
    main()
