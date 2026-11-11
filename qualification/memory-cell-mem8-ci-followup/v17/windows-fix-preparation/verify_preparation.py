#!/usr/bin/env python3
"""Verify frozen preparation bytes only; never import or execute the lint driver."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import yaml


def ident(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def merkle(rows):
    nodes = {'': {}}
    for name, (mode, sha) in rows.items():
        parent = ''
        parts = name.split('/')
        assert all(p not in ('', '.', '..') for p in parts)
        for p in parts[:-1]:
            child = parent + '/' + p if parent else p
            nodes.setdefault(child, {})
            nodes[parent][p] = ('40000', child)
            parent = child
        assert parts[-1] not in nodes[parent]
        nodes[parent][parts[-1]] = (mode, sha)
    sums = {}
    for path in sorted(nodes, key=lambda x: (x.count('/'), len(x)), reverse=True):
        raw = bytearray()
        for name, (mode, ref) in sorted(nodes[path].items(), key=lambda x: (x[0] + ('/' if x[1][0] == '40000' else '')).encode()):
            raw.extend(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sums[ref] if mode == '40000' else ref))
        sums[path] = hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return sums['']


def main(root):
    manifest = json.loads((root / 'FILE_MANIFEST.json').read_bytes())
    for row in manifest['files']:
        path = Path(row['path'])
        assert not path.is_absolute() and '..' not in path.parts
        assert ident((root / path).read_bytes()) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
    final = json.loads((root / 'FINAL_PREPARATION.json').read_bytes())
    for row in final['files']:
        assert ident((root / 'rendered' / row['path']).read_bytes()) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
    plan = json.loads((root / 'rendered/.github/fixtures/mem-windows-sandbox-fix-plan.json').read_bytes())
    assert plan['source_head'] == final['source_head'] == 'd0f6507e08f7f5c5855f5164d07c049a34d1a6d9'
    assert plan['source_tree'] == final['source_tree'] == '658fa040046285116b1fd81b94ff8c96444072ad'
    tree_raw = (root / 'reference/CANDIDATE_TREE.ls-tree').read_bytes()
    assert ident(tree_raw) == plan['complete_tree_inventory']
    rows = {}
    for part in tree_raw.split(b'\0'):
        if not part:
            continue
        left, name = part.split(b'\t', 1)
        mode, kind, sha = left.decode().split()
        name = name.decode()
        assert kind == 'blob' and name not in rows
        rows[name] = mode, sha
    assert len(rows) == 14053 and merkle(rows) == plan['source_tree']
    assert len(plan['files']) == 20
    for path, pin in plan['files'].items():
        assert rows[path] == (pin['mode'], pin['git_blob'])
    support = (root / 'rendered/.github/scripts/mem_windows_sandbox_fix_support.py').read_bytes()
    assert support == (root / 'reference/.github/scripts/mem_native_five_support.py').read_bytes()
    driver = (root / 'rendered/.github/scripts/mem_windows_sandbox_fix.py').read_text()
    old = (root / 'reference/.github/scripts/mem_native_five.py').read_text()
    changes = json.loads((root / 'TEMPLATE_STATIC_REVIEW.json').read_bytes())['driver_derivation']
    for change in changes:
        assert old.count(change['old']) == change['count']
        old = old.replace(change['old'], change['new'])
    assert old == driver
    ast.parse(driver)
    ast.parse(support)
    wf = yaml.safe_load((root / 'rendered/.github/workflows/hepta-mem-windows-sandbox-fix.yml').read_bytes())
    assert wf['on'] == {'push': {'branches': ['codex/mem8-windows-sandbox-fix-v10-20261111-ed353817']}}
    assert wf['permissions'] == {'contents': 'read'} and wf['jobs']['sandbox-fix']['timeout-minutes'] == 65
    assert plan['native_test_commands'] == [] and plan['scoped_fix_command'] == ['just', 'fix', '--locked', '-p', 'codex-windows-sandbox']
    return {'status': 'PASS_OFFLINE_PREPARATION_BYTES_ONLY', 'members': len(manifest['files']) + 1,
            'source': plan['source_head'], 'tree': plan['source_tree'], 'full_entries': len(rows),
            'four_objects': final['files'], 'native_execution': 0, 'model_requests': 0, 'workflow_admission': False}


if __name__ == '__main__':
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=2, sort_keys=True))
