#!/usr/bin/env python3
"""Pure local byte/AST/Merkle review; never imports or executes the reviewed driver."""
import ast
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-cc57-isolated-materializer-v1')
INVENTORY = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
OUT = Path(__file__).resolve().parent

def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def object_id(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def require_pin(raw, expected):
    got = ident(raw)
    assert all(got[key] == value for key, value in expected.items()), (got, expected)

def trees(rows):
    node = {}
    for row in rows:
        parts = row['path'].split('/')
        assert all(p and p not in ('.', '..') and p.lower() != '.git' for p in parts)
        parent = node
        for part in parts[:-1]:
            parent = parent.setdefault(part, {})
            assert isinstance(parent, dict)
        assert parts[-1] not in parent
        parent[parts[-1]] = (row['index_mode'], row['working_blob'])
    objects = {}
    def visit(parent):
        entries = []
        for name, value in parent.items():
            mode, key = ('40000', visit(value)) if isinstance(value, dict) else value
            encoded_name = name.encode('utf-8')
            entries.append((encoded_name + (b'/' if mode == '40000' else b''),
                            mode.encode() + b' ' + encoded_name + b'\0' + bytes.fromhex(key)))
        raw = b''.join(body for _, body in sorted(entries))
        key = object_id('tree', raw)
        assert key not in objects or objects[key] == raw
        objects[key] = raw
        return key
    return visit(node), objects

def definitions(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    parsed = ast.parse(text)
    return {n.name: ''.join(lines[n.lineno - 1:n.end_lineno])
            for n in parsed.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}

def main():
    driver = (ROOT / 'driver-v4.HOLD.py').read_bytes()
    require_pin(driver, {'bytes': 57607, 'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436', 'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'})
    original = (ROOT / 'driver.HOLD.py').read_bytes()
    require_pin(original, {'bytes': 52624, 'sha256': 'f062ffd6cd280baa3cf9d502cbc2db09035055310c67538cdaca4599972eee82', 'git_blob': '8bbdb73beb9156a70943c71067bb37efab056317'})
    packet_raw = (ROOT / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes()
    require_pin(packet_raw, {'bytes': 13764, 'sha256': 'b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3', 'git_blob': '06503652a2895120daf8b66e42b3a01cefeaf4fb'})
    packet = json.loads(packet_raw)
    full_raw = INVENTORY.read_bytes()
    require_pin(full_raw, packet['current']['inventory'])
    full = json.loads(full_raw)
    rows = full['files']
    assert len(rows) == full['filesystem_entries'] == full['tracked_entries'] == 15188
    assert full['source'] == {'head': packet['current']['commit'], 'tree': packet['current']['tree'], 'status': ''}
    assert all(r['stable'] and r['matches_index'] for r in rows)
    current_root, current_trees = trees(rows)
    assert current_root == packet['current']['tree']
    parent_rows = {r['path']: dict(r) for r in rows}
    changes = packet['parent_snapshot']['changes_from_current']
    assert len(changes) == 5 and len({r['path'] for r in changes}) == 5
    for change in changes:
        row = parent_rows[change['path']]
        assert row['index_mode'] == change['mode']
        assert {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']} == change['current']
        row.update(index_blob=change['parent']['git_blob'], working_blob=change['parent']['git_blob'], bytes=change['parent']['bytes'], sha256=change['parent']['sha256'])
    parent_root, parent_trees = trees(parent_rows.values())
    assert parent_root == packet['parent_snapshot']['tree']
    objects = {}
    for row in [*rows, *parent_rows.values()]:
        value = ('blob', row['bytes'], row['sha256'])
        assert row['working_blob'] not in objects or objects[row['working_blob']] == value
        objects[row['working_blob']] = value
    for key, raw in {**current_trees, **parent_trees}.items():
        objects[key] = ('tree', len(raw), hashlib.sha256(raw).hexdigest())
    commits = []
    for row in packet['raw_commits']:
        raw = base64.b64decode(row['raw_base64'], validate=True)
        assert row['type'] == 'commit' and object_id('commit', raw) == row['sha']
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        header = raw.split(b'\n\n', 1)[0].split(b'\n')
        tree = [line[5:].decode() for line in header if line.startswith(b'tree ')]
        parents = [line[7:].decode() for line in header if line.startswith(b'parent ')]
        expected = packet['current'] if row['sha'] == packet['current']['commit'] else packet['parent_snapshot']
        assert row['sha'] == expected['commit'] and tree == [expected['tree']] and parents == expected['parents']
        objects[row['sha']] = ('commit', len(raw), row['sha256'])
        commits.append({'sha': row['sha'], 'bytes': len(raw), 'sha256': row['sha256'], 'tree': tree[0], 'parents': parents})
    counts = {kind: sum(v[0] == kind for v in objects.values()) for kind in ('blob', 'tree', 'commit')}
    assert counts == {'blob': 14615, 'tree': 1832, 'commit': 2} and len(objects) == 16449
    missing = {row['path']: row for row in packet['seven_missing']}
    assert len(missing) == 7 and sum(row['bytes'] for row in missing.values()) == 18176884
    native = []
    damaged = []
    for row in rows:
        item = {'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'], 'sha256': row['sha256'], 'blob': row['working_blob']}
        native.append(item)
        if row['path'] in missing:
            fixed = missing[row['path']]
            assert row['kind'] == 'file' and row['index_mode'] == '100644'
            assert (row['bytes'], row['sha256'], row['working_blob']) == (fixed['bytes'], fixed['sha256'], fixed['sha'])
            damaged.append({'path': row['path'], 'missing': True})
        else:
            damaged.append(item)
    def serialize(value):
        return json.dumps(sorted(value, key=lambda r:r['path'].encode()), sort_keys=True, separators=(',', ':')).encode()
    current_native = serialize(native)
    old_native = serialize(damaged)
    require_pin(current_native, packet['current']['native_inventory'])
    require_pin(old_native, packet['expected_old_native_inventory'])
    old_defs, new_defs = definitions(original), definitions(driver)
    changed = [key for key in old_defs if old_defs[key] != new_defs.get(key)]
    added = sorted(new_defs.keys() - old_defs.keys())
    assert changed == ['command', 'ObjectReader', 'initialize_index', 'final_old', 'main']
    assert added == ['retain_existing_output']
    cfg_raw = (ROOT / 'WAITING_CONFIG_V4.json').read_bytes()
    cfg = json.loads(cfg_raw)
    assert cfg['driver'] == ident(driver) and cfg['packet'] == ident(packet_raw)
    assert cfg['status'] == 'HOLD_FOR_ROOT_EXACT_REVIEW' and cfg['root_execution_approved'] is False and cfg['qualification'] is False
    assert (cfg['action_seconds'], cfg['record_seconds'], cfg['outer_seconds']) == (600, 180, 900)
    result = {
        'format': 'independent-isolated-materializer-static-byte-review-v1',
        'driver': ident(driver), 'original_driver': ident(original), 'packet': ident(packet_raw), 'waiting_config': ident(cfg_raw),
        'actual_execution': False, 'reviewed_driver_main_executed': False, 'H_calls': 0,
        'basis_inventory': ident(full_raw), 'basis_is_retained_canonical_bytes_not_new_physical_read': True,
        'current': {'head': packet['current']['commit'], 'tree': current_root, 'leaves': len(rows), 'trees': len(current_trees)},
        'parent': {'head': packet['parent_snapshot']['commit'], 'tree': parent_root, 'leaves': len(parent_rows), 'trees': len(parent_trees), 'inverse_changed_paths': [r['path'] for r in changes]},
        'object_union': {'count': len(objects), 'counts': counts, 'complete_ancestry': False, 'unmaterialized_parent': packet['parent_snapshot']['parents']},
        'original_commit_bodies': commits,
        'current_native_projection': ident(current_native), 'old_missing_native_projection': ident(old_native),
        'seven_missing_bytes': sum(r['bytes'] for r in missing.values()),
        'ast': {'old_definitions': len(old_defs), 'new_definitions': len(new_defs), 'unchanged_original_definitions': len(old_defs) - len(changed), 'changed': changed, 'added': added},
        'budgets': {'action': 600, 'retention': 180, 'outer': 900},
        'no_materialization_or_qualification_claim': True
    }
    raw = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    destination = OUT / 'STATIC_BYTE_REVIEW.json'
    with destination.open('xb') as stream:
        stream.write(raw)
    print(json.dumps(ident(raw), sort_keys=True))

if __name__ == '__main__':
    main()
