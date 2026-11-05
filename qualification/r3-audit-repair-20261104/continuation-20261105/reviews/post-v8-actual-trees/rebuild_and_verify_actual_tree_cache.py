"""Decode complete Git API tree identities and independently recompute Merkle nodes."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

ROOT = Path('/workspace/scratch/07dd58cc9630/hepta-audit-fifth/recovery-2113')
MODES = {'t': ('040000', 'tree'), 'f': ('100644', 'blob'), 'x': ('100755', 'blob'),
         's': ('120000', 'blob'), 'c': ('160000', 'commit')}


def row(path, mode_code, sha):
    mode, kind = MODES[mode_code]
    return {'path': path, 'mode': mode, 'type': kind, 'sha': sha}


def verify(tree):
    entries = tree['tree']
    expected = {'': tree['sha']}
    children = {'': []}
    for e in entries:
        parent, _, name = e['path'].rpartition('/')
        children.setdefault(parent, []).append({**e, 'name': name})
        if e['type'] == 'tree':
            expected[e['path']] = e['sha']
            children.setdefault(e['path'], [])
    assert len(expected) == len(children)
    for path, group in children.items():
        group.sort(key=lambda e: (e['name'] + ('/' if e['type'] == 'tree' else '')).encode())
        body = b''.join(e['mode'].lstrip('0').encode() + b' ' + e['name'].encode() + b'\0' + bytes.fromhex(e['sha']) for e in group)
        actual = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        assert actual == expected[path], (path, actual, expected[path])
    return {'tree': tree['sha'], 'entries': len(entries), 'directory_nodes': len(children),
            'leaves': sum(e['type'] != 'tree' for e in entries), 'all_Merkle_nodes_match': True}


d = json.loads((ROOT / 'actual-trees-compact.json').read_text())
prior = ''
entries = []
for common, suffix, mode, sha in d['base']['prefix_rows']:
    path = prior[:common] + suffix
    entries.append(row(path, mode, sha))
    prior = path
trees = {'5b': {'sha': d['base']['sha'], 'tree': entries, 'truncated': False}}
base = {e['path']: e for e in entries}
for derivative in d['derived']:
    values = dict(base) if derivative['relative_to_base'] else {}
    for path in derivative['deleted']:
        del values[path]
    for path, mode, sha in derivative['rows']:
        values[path] = row(path, mode, sha)
    assert len(values) == derivative['entries']
    trees[derivative['label']] = {'sha': derivative['sha'], 'tree': list(values.values()), 'truncated': False}

ancestors = json.loads((ROOT / 'audit-ancestor-trees.json').read_text())
audit = dict(base)
for i, prefix, child in [(0, '', 'qualification'), (1, 'qualification/', 'r3-audit-repair-20261104'),
                         (2, 'qualification/r3-audit-repair-20261104/', 'continuation-20261105')]:
    old = {e['path'][len(prefix):]: e for e in entries if e['path'].startswith(prefix) and '/' not in e['path'][len(prefix):]}
    current = {e['path']: e for e in ancestors[i]['tree']}
    assert set(old) - {child} == set(current) - {child}
    for name, e in current.items():
        if name != child:
            assert all(e[k] == old[name][k] for k in ('mode', 'type', 'sha'))
    if i > 0:
        directory = prefix.rstrip('/')
        audit[directory] = {**audit[directory], 'sha': ancestors[i]['sha']}
prefix = 'qualification/r3-audit-repair-20261104/continuation-20261105'
continuation = trees['auditContinuationV8']
audit[prefix] = {'path': prefix, 'mode': '040000', 'type': 'tree', 'sha': continuation['sha']}
for e in continuation['tree']:
    audit[prefix + '/' + e['path']] = {**e, 'path': prefix + '/' + e['path']}
trees['auditV8'] = {'sha': ancestors[0]['sha'], 'tree': list(audit.values()), 'truncated': False}

destination = ROOT / 'trees'
destination.mkdir(exist_ok=True)
proofs = {}
for label, tree in trees.items():
    proofs[label] = verify(tree)
    (destination / (label + '.json')).write_text(json.dumps(tree, separators=(',', ':')) + '\n')
    leaves = [e for e in tree['tree'] if e['type'] != 'tree']
    (destination / (label + '-leaves.json')).write_text(json.dumps({'tree': tree['sha'], 'leaf_count': len(leaves), 'leaves': leaves}, separators=(',', ':')) + '\n')
(ROOT / 'actual-trees-compact-root-proof.json').write_text(json.dumps({'observed_api_utc': d['observed_utc'], 'proofs': proofs}, indent=2) + '\n')
body = (ROOT / 'actual-trees-compact.json').read_bytes()
packed = gzip.compress(body, mtime=0)
encoded = base64.b64encode(packed)
(ROOT / 'actual-trees-compact.gzip.base64.txt').write_bytes(encoded)
print(json.dumps({'proofs': proofs, 'compact_bytes': len(body), 'gzip_bytes': len(packed), 'base64_bytes': len(encoded), 'directory': str(destination)}))
