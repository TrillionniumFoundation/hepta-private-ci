from pathlib import Path
import ast
import collections
import hashlib
import json
import subprocess
import sys
import tomllib

root = Path.cwd()
left, right, base, output = sys.argv[1:]


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def manifest(sha):
    return tomllib.loads(git('show', sha + ':CALLERS.toml'))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def counter(rows):
    return collections.Counter(canonical(row) for row in rows)


def select(old, a, b):
    if a == b:
        return a
    if a == old:
        return b
    if b == old:
        return a
    raise ValueError('Concurrent semantic edit requires explicit review')


assert git('rev-parse', 'HEAD') == left
assert git('rev-parse', 'MERGE_HEAD') == right
assert git('merge-base', '--all', left, right) == base
b, l, r = manifest(base), manifest(left), manifest(right)
actual = tomllib.loads((root / 'CALLERS.toml').read_text())
assert b.keys() == l.keys() == r.keys() == actual.keys()
boundary_changes = []
for key in b:
    if key == 'protected_file':
        continue
    if key == 'boundary':
        maps = [{row['id']: row for row in source[key]} for source in (b, l, r)]
        assert maps[0].keys() == maps[1].keys() == maps[2].keys()
        expected = []
        for row in b[key]:
            identifier = row['id']
            chosen = select(*(mapping[identifier] for mapping in maps))
            expected.append(chosen)
            if chosen != row:
                boundary_changes.append({'id': identifier, 'before': row, 'after': chosen})
        assert actual[key] == expected
    else:
        assert actual[key] == select(b[key], l[key], r[key]), key
expected_rows = (counter(b['protected_file']) & counter(l['protected_file']) & counter(r['protected_file'])) + (
    (counter(l['protected_file']) - counter(b['protected_file'])) | (counter(r['protected_file']) - counter(b['protected_file']))
)
assert expected_rows == counter(actual['protected_file'])
assert len(actual['boundary']) == 480
assert len(actual['protected_file']) == 368
assert set(row['id'] for row in actual['boundary']) == set(actual['privileged_inventory']['required_boundary_ids'])
entries = []
for path in git('diff', '--cached', '--name-only', left).splitlines():
    assert path == 'CALLERS.toml' or (path.startswith('qa/b4-no-bypass/test_') and path.endswith('.py')), path
    data = (root / path).read_bytes()
    blob = git('hash-object', '--', path)
    existing = False
    for sha in (left, right):
        if subprocess.run(['git', 'cat-file', '-e', sha + ':' + path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            existing = existing or git('rev-parse', sha + ':' + path) == blob
    if path.endswith('.py'):
        old_tree = ast.parse(git('show', base + ':' + path))
        new_tree = ast.parse(data.decode())
        names = lambda tree: sorted(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
        assert names(old_tree) == names(new_tree), path
    entries.append({'path': path, 'sha': blob, 'mode': '100644', 'type': 'blob', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'novel': not existing})
report = {'left': left, 'right': right, 'merge_base': base, 'tree': git('write-tree'), 'boundaries': len(actual['boundary']), 'protected_rows': len(actual['protected_file']), 'full_row_multiset_verified': True, 'boundary_representation_changes': boundary_changes, 'entries': entries}
Path(output).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({**report, 'boundary_representation_changes': [row['id'] for row in boundary_changes]}))
