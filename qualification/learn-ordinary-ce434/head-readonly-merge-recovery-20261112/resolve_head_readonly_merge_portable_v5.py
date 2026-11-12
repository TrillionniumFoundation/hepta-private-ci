"""Resolve the actual 32c0160 + 57ffff merge by full record identity."""
import ast
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

import argparse

FROZEN_REFS = {
    'base': 'dd4b6c17344986a3a9379e372bf19d282f812a30',
    'left': '32c0160e60d377eb79983abc394832efce12c988',
    'right': '57ffff832355d75937045f240fed2c2d48783029',
}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--worktree', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
for name, value in FROZEN_REFS.items():
    parser.add_argument('--' + name, default=value)
options = parser.parse_args()
ROOT = options.worktree.resolve(strict=True)
OUT = options.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
    parser.error('audit output must be outside the source worktree')
REFS = {}
for name, expected in FROZEN_REFS.items():
    actual = subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', '--verify', '--end-of-options',
         getattr(options, name) + '^{commit}'], text=True).strip()
    if actual != expected:
        parser.error(name + ' ref differs from the frozen 32c0160/57ffff/dd4 source graph')
    REFS[name] = actual
SHARED = 'learning_original_owner_command_channel'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True)


def canonical(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':'))


def fingerprint(row):
    return hashlib.sha256(canonical(row).encode()).hexdigest()


def full_counter(rows):
    return Counter(map(canonical, rows))


def counter_rows(counter):
    return [{'count': count, 'record_sha256': hashlib.sha256(raw.encode()).hexdigest(),
             'record': json.loads(raw)} for raw, count in sorted(counter.items())]


def blocks(text):
    matches = list(re.finditer(r'^(?:\[\[(boundary|protected_file)\]\]|\[(authority)\])[ \t]*$', text, re.M))
    result = {'prefix': text[:matches[0].start()], 'boundary': [], 'protected_file': [], 'authority': [], 'sequence': []}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[match.start():end]
        parsed = tomllib.loads(raw)
        kind = match.group(1) or match.group(2)
        assert list(parsed) == [kind]
        if kind == 'authority':
            row = parsed[kind]
        else:
            assert len(parsed[kind]) == 1
            row = parsed[kind][0]
        result[kind].append((row, raw))
        result['sequence'].append((kind, row, raw))
    return result


assert git('merge-base', '--all', REFS['left'], REFS['right']).splitlines() == [REFS['base']]
assert git('rev-parse', 'HEAD').strip() == REFS['left']
assert git('rev-parse', 'MERGE_HEAD').strip() == REFS['right']
OUT.mkdir(parents=True, exist_ok=True)
texts = {side: git('show', ref + ':CALLERS.toml') for side, ref in REFS.items()}
manifests = {side: tomllib.loads(text) for side, text in texts.items()}
pieces = {side: blocks(text) for side, text in texts.items()}
by_id = {side: {row['id']: row for row in value['boundary']} for side, value in manifests.items()}
raw_by_id = {side: {row['id']: raw for row, raw in value['boundary']} for side, value in pieces.items()}
for side, value in manifests.items():
    assert len(by_id[side]) == len(value['boundary'])
    inventory = value['privileged_inventory']['required_boundary_ids']
    assert len(inventory) == len(set(inventory))
    assert set(inventory) == set(by_id[side])
    assert all(flag is False for flag in value['authority'].values())
    for key in manifests['base']:
        if key not in ('boundary', 'protected_file', 'privileged_inventory'):
            assert value[key] == manifests['base'][key], (side, key)
    assert set(by_id['base']) <= set(by_id[side])

new_left = set(by_id['left']) - set(by_id['base'])
new_right = set(by_id['right']) - set(by_id['base'])
assert not new_left & new_right
assert len(new_left) == 24 and len(new_right) == 14
order = list(by_id['left']) + [key for key in by_id['right'] if key not in by_id['left']]
resolved_boundaries = []
resolved_boundary_text = {}
boundary_provenance = []
for identifier in order:
    before = by_id['base'].get(identifier)
    left = by_id['left'].get(identifier)
    right = by_id['right'].get(identifier)
    if right is None or right == before:
        selected, origin = left, 'left'
        raw = raw_by_id['left'][identifier]
    elif left is None or left == before:
        selected, origin = right, 'right'
        raw = raw_by_id['right'][identifier]
    elif left == right:
        selected, origin = left, 'both_identical'
        raw = raw_by_id['left'][identifier]
    else:
        assert identifier == SHARED
        without = lambda row: {key: value for key, value in row.items() if key != 'product_callers'}
        assert without(before) == without(left) == without(right)
        assert set(before['product_callers']) <= set(left['product_callers'])
        assert set(before['product_callers']) <= set(right['product_callers'])
        selected = copy.deepcopy(left)
        selected['product_callers'] += [path for path in right['product_callers']
                                       if path not in selected['product_callers']]
        assert len(selected['product_callers']) == 32
        raw, count = re.subn(r'(?m)^product_callers\s*=\s*\[[^\]]*\]',
                            'product_callers = ' + json.dumps(selected['product_callers']),
                            raw_by_id['left'][identifier])
        assert count == 1
        assert tomllib.loads(raw)['boundary'][0] == selected
        origin = 'exact_caller_union_only'
    resolved_boundaries.append(selected)
    resolved_boundary_text[identifier] = raw
    boundary_provenance.append({'id': identifier, 'origin': origin,
                                'record_sha256': fingerprint(selected)})

# Preserve complete protected records and multiplicity. No map is keyed by path.
protected = {side: full_counter(value['protected_file']) for side, value in manifests.items()}
left_removed = protected['base'] - protected['left']
left_added = protected['left'] - protected['base']
right_removed = protected['base'] - protected['right']
right_added = protected['right'] - protected['base']
assert not left_removed
assert sum(left_added.values()) == 14
assert sum(right_removed.values()) == 3 and sum(right_added.values()) == 11
assert not left_added & right_added
expected_protected = protected['left'].copy()
expected_protected.subtract(right_removed)
assert all(count >= 0 for count in expected_protected.values())
expected_protected.update(right_added)
expected_protected = +expected_protected
pending_removed = right_removed.copy()
pending_added = right_added.copy()
resolved_body = []
for kind, row, raw in pieces['left']['sequence']:
    if kind == 'boundary':
        resolved_body.append(resolved_boundary_text[row['id']])
    elif kind == 'authority':
        resolved_body.append(raw)
    else:
        key = canonical(row)
        if pending_removed[key]:
            pending_removed[key] -= 1
        else:
            resolved_body.append(raw)
for kind, row, raw in pieces['right']['sequence']:
    if kind == 'boundary' and row['id'] in new_right:
        resolved_body.append(resolved_boundary_text[row['id']])
    elif kind == 'protected_file':
        key = canonical(row)
        if pending_added[key]:
            resolved_body.append(raw)
            pending_added[key] -= 1
assert not +pending_removed and not +pending_added

inventory = list(manifests['left']['privileged_inventory']['required_boundary_ids'])
inventory += [identifier for identifier in manifests['right']['privileged_inventory']['required_boundary_ids']
              if identifier not in inventory]
prefix, count = re.subn(r'(?m)^required_boundary_ids\s*=\s*\[[^\]]*\]',
                       'required_boundary_ids = ' + json.dumps(inventory), pieces['left']['prefix'])
assert count == 1
resolved = prefix + ''.join(resolved_body)
value = tomllib.loads(resolved)
assert full_counter(value['boundary']) == full_counter(resolved_boundaries)
assert full_counter(value['protected_file']) == expected_protected
assert Counter(value['privileged_inventory']['required_boundary_ids']) == Counter(order)
assert len(value['boundary']) == 554 and len(value['protected_file']) == 400
(ROOT / 'CALLERS.toml').write_text(resolved)

# Resolve only the shared tuple conflict. Every other statement must retain
# the right parent's AST, which already contains all nonshared guard changes.
shared_callers = next(row for row in resolved_boundaries if row['id'] == SHARED)['product_callers']
python_changes = []
unmerged = git('diff', '--name-only', '--diff-filter=U').splitlines()
for relative in unmerged:
    if relative == 'CALLERS.toml':
        continue
    assert relative.startswith('qa/b4-no-bypass/') and relative.endswith('.py')
    # A conflict hunk can include adjacent nonshared tuples. Start from the
    # complete readonly postimage; below we independently prove that the HEAD
    # parent's only AST change in this module was the shared caller tuple.
    (ROOT / relative).write_text(git('show', REFS['right'] + ':' + relative))


def shared_value(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, val in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == SHARED:
                    found.append(val)
    assert len(found) <= 1
    return found[0] if found else None


def masked_ast(text):
    tree = ast.parse(text)
    target = shared_value(tree)
    if target is not None:
        target.elts = []
    return ast.dump(tree, include_attributes=False)


for path in sorted((ROOT / 'qa/b4-no-bypass').glob('*.py')):
    text = path.read_text()
    if SHARED not in text:
        continue
    tree = ast.parse(text)
    node = shared_value(tree)
    if node is None:
        continue
    relative = str(path.relative_to(ROOT))
    text = git('show', REFS['right'] + ':' + relative)
    left_exists = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e',
                                  REFS['left'] + ':' + relative], capture_output=True).returncode == 0
    if left_exists:
        assert masked_ast(git('show', REFS['left'] + ':' + relative)) == masked_ast(
            git('show', REFS['base'] + ':' + relative)), relative
    tree = ast.parse(text)
    node = shared_value(tree)
    assert isinstance(node, ast.Tuple)
    before = ast.literal_eval(node)
    if tuple(shared_callers) == before:
        continue
    assert set(before) <= set(shared_callers)
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[:node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[:node.end_lineno - 1]) + node.end_col_offset
    after = text[:start] + repr(tuple(shared_callers)) + text[end:]
    assert masked_ast(text) == masked_ast(after)
    parent = git('show', REFS['right'] + ':' + relative)
    assert masked_ast(parent) == masked_ast(after), relative
    path.write_text(after)
    python_changes.append({'path': relative, 'old_callers': len(before), 'new_callers': 32,
                           'only_shared_tuple_ast_changed': True,
                           'head_other_ast_matches_base': left_exists,
                           'all_other_ast_matches_right_parent': True})
assert len(python_changes) == 8

# All production/fixture Rust changes must remain exact side postimages.
changed = {side: git('diff', '--name-only', REFS['base'], REFS[side]).splitlines()
           for side in ('left', 'right')}
rust = {side: {path for path in paths if path.endswith('.rs')} for side, paths in changed.items()}
assert not rust['left'] & rust['right']
rust_checks = []
for side in ('left', 'right'):
    for relative in sorted(rust[side]):
        expected = subprocess.check_output(['git', '-C', str(ROOT), 'show', REFS[side] + ':' + relative])
        actual = (ROOT / relative).read_bytes()
        assert actual == expected, relative
        rust_checks.append({'path': relative, 'side': side, 'bytes': len(actual),
                            'sha256': hashlib.sha256(actual).hexdigest(), 'exact_parent_postimage': True})
coverage = 'scripts/hepta_c_observer_coverage.py'
assert (ROOT / coverage).read_text() == git('show', REFS['left'] + ':' + coverage)

audit = {
    'refs': REFS, 'actual_merge_base': REFS['base'], 'actual_merge_head_before_commit': REFS['right'],
    'manifest': {
        'boundary_counts': {side: len(manifest['boundary']) for side, manifest in manifests.items()} | {'merged': 554},
        'protected_record_counts': {side: len(manifest['protected_file']) for side, manifest in manifests.items()} | {'merged': 400},
        'protected_distinct_paths': len({row['path'] for row in value['protected_file']}),
        'boundary_counter_exact': True, 'protected_full_record_counter_exact': True,
        'inventory_counter_exact': True, 'all_authority_flags_false': True,
        'new_left_boundary_ids': sorted(new_left), 'new_right_boundary_ids': sorted(new_right),
        'protected_formula': 'Counter(left complete records) - Counter(right removals from base) + Counter(right additions to base)',
        'left_added_protected': counter_rows(left_added),
        'right_removed_protected': counter_rows(right_removed),
        'right_added_protected': counter_rows(right_added),
        'merged_full_protected_record_counter': counter_rows(expected_protected),
        'merged_boundary_provenance': boundary_provenance,
        'shared_boundary_record': next(row for row in resolved_boundaries if row['id'] == SHARED),
        'missing_protected_records': [], 'extra_protected_records': [],
    },
    'python_tuple_changes': python_changes, 'rust_postimages': rust_checks,
    'coverage_exact_root_parent': True,
    'scope': 'real Git merge, record/AST/postimage audit; no H, Rust, native or full QA execution',
    'ordinary_acceptance': {'positive': 0, 'no_update_or_fallback': 0, 'fresh_session_c': 0, 'daemon_root_cold_restart': 0},
}
(OUT / 'three-way-record-audit-v1.json').write_text(json.dumps(audit, indent=2) + '\n')
subprocess.run(['git', '-C', str(ROOT), 'add', '--', 'CALLERS.toml', *[item['path'] for item in python_changes]], check=True)
assert not git('diff', '--name-only', '--diff-filter=U').strip()
subprocess.run(['git', '-C', str(ROOT), 'diff', '--cached', '--check'], check=True)
print(json.dumps({'boundaries': 554, 'protected_records': 400,
                  'protected_paths': audit['manifest']['protected_distinct_paths'],
                  'shared_callers': len(shared_callers), 'python_tuple_changes': python_changes,
                  'exact_rust_postimages': len(rust_checks), 'remaining_conflicts': []}, indent=2))
