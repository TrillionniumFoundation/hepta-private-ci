"""Read-only three-way manifest and AST profile; never resolves a source merge."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--worktree', required=True, type=Path)
parser.add_argument('--left', required=True)
parser.add_argument('--right', required=True)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--check-working-tree', action='store_true')
options = parser.parse_args()
ROOT = options.worktree.resolve(strict=True)
OUTPUT = options.output.resolve()
if OUTPUT == ROOT or ROOT in OUTPUT.parents:
    parser.error('report output must be outside the source worktree')


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True)


def resolve(ref):
    return git('rev-parse', '--verify', '--end-of-options', ref + '^{commit}').strip()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def records(rows):
    return Counter(canonical(row) for row in rows)


def expanded(counter):
    return [{'count': count, 'record_sha256': hashlib.sha256(raw.encode()).hexdigest(),
             'record': json.loads(raw)} for raw, count in sorted(counter.items())]


def digested(counter):
    return [{'count': count, 'record_sha256': hashlib.sha256(raw.encode()).hexdigest()}
            for raw, count in sorted(counter.items())]


refs = {'left': resolve(options.left), 'right': resolve(options.right)}
bases = git('merge-base', '--all', refs['left'], refs['right']).splitlines()
if len(bases) != 1:
    raise RuntimeError('exactly one actual merge-base is required: ' + repr(bases))
refs['base'] = bases[0]
manifests = {side: tomllib.loads(git('show', ref + ':CALLERS.toml')) for side, ref in refs.items()}
indexed = {}
parent_checks = {}
for side, manifest in manifests.items():
    rows = manifest['boundary']
    indexed[side] = {row['id']: row for row in rows}
    identifiers = manifest['privileged_inventory']['required_boundary_ids']
    parent_checks[side] = {
        'unique_boundary_ids': len(indexed[side]) == len(rows),
        'inventory_exact_counter': Counter(identifiers) == Counter(row['id'] for row in rows),
        'all_authority_flags_false': all(flag is False for flag in manifest['authority'].values()),
        'boundaries': len(rows), 'protected_records': len(manifest['protected_file']),
        'protected_paths': len({row['path'] for row in manifest['protected_file']}),
    }

proposed_boundaries = []
boundary_cases = []
boundary_ambiguities = []
all_ids = sorted(set().union(*(set(rows) for rows in indexed.values())))
for identifier in all_ids:
    before, left, right = (indexed[side].get(identifier) for side in ('base', 'left', 'right'))
    if left == right:
        chosen, reason = left, 'both_identical'
    elif left == before:
        chosen, reason = right, 'right_changed_only'
    elif right == before:
        chosen, reason = left, 'left_changed_only'
    else:
        strip = lambda row: {key: value for key, value in row.items() if key != 'product_callers'}
        if before is not None and left is not None and right is not None and strip(before) == strip(left) == strip(right):
            old = set(before['product_callers'])
            lcall, rcall = left['product_callers'], right['product_callers']
            if old <= set(lcall) and old <= set(rcall):
                chosen = dict(left)
                chosen['product_callers'] = list(lcall) + [path for path in rcall if path not in lcall]
                reason = 'exact_additive_caller_union'
            else:
                chosen, reason = None, 'manual_review_of_shared_caller_removal'
        else:
            chosen, reason = None, 'manual_review_of_noncaller_record_change'
        if chosen is None:
            boundary_ambiguities.append(identifier)
    if chosen is not None:
        proposed_boundaries.append(chosen)
    if left != before or right != before:
        boundary_cases.append({'id': identifier, 'reason': reason,
                               'base': before, 'left': left, 'right': right,
                               'proposed': chosen,
                               'ambiguous': identifier in boundary_ambiguities})

protected = {side: records(manifest['protected_file']) for side, manifest in manifests.items()}
removed = {side: protected['base'] - protected[side] for side in ('left', 'right')}
added = {side: protected[side] - protected['base'] for side in ('left', 'right')}
shared_removed = removed['left'] & removed['right']
shared_added = added['left'] & added['right']
# Duplicate complete additions on both branches require an explicit multiplicity
# decision. A shared path alone is not an overlap and never removes a record.
protected_unambiguous = not shared_removed and not shared_added
expected_protected = None
if protected_unambiguous:
    expected_protected = protected['left'].copy()
    expected_protected.subtract(removed['right'])
    if any(count < 0 for count in expected_protected.values()):
        raise RuntimeError('right removal is absent from the complete left records')
    expected_protected.update(added['right'])
    expected_protected = +expected_protected

outside = lambda manifest: {key: value for key, value in manifest.items()
                             if key not in ('boundary', 'protected_file', 'privileged_inventory')}
other_metadata_equal = outside(manifests['base']) == outside(manifests['left']) == outside(manifests['right'])
parent_integrity = all(all(row[key] for key in (
    'unique_boundary_ids', 'inventory_exact_counter', 'all_authority_flags_false'))
    for row in parent_checks.values())

changed = {side: set(git('diff', '--name-only', refs['base'], refs[side]).splitlines())
           for side in ('left', 'right')}


def ast_nodes(source):
    tree = ast.parse(source)
    result = {'<whole_module>': ast.dump(tree, include_attributes=False)}

    def visit(body, prefix=''):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                key = prefix + node.name
                result[key] = ast.dump(node, include_attributes=False)
                if isinstance(node, ast.ClassDef):
                    visit(node.body, key + '.')
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                if names:
                    result[prefix + 'assign:' + ','.join(names)] = ast.dump(node, include_attributes=False)
    visit(tree.body)
    return result


python_overlap = []
for relative in sorted(changed['left'] & changed['right']):
    if not relative.endswith('.py'):
        continue
    sides = {}
    for side, ref in refs.items():
        probe = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', ref + ':' + relative],
                               capture_output=True)
        sides[side] = ast_nodes(git('show', ref + ':' + relative)) if probe.returncode == 0 else {}
    keys = set().union(*(set(nodes) for nodes in sides.values()))
    joint = []
    for key in sorted(keys):
        before, left, right = (sides[side].get(key) for side in ('base', 'left', 'right'))
        if left != before and right != before:
            joint.append({'node': key, 'same_postimage': left == right,
                          'base_sha256': hashlib.sha256(before.encode()).hexdigest() if before is not None else None,
                          'left_sha256': hashlib.sha256(left.encode()).hexdigest() if left is not None else None,
                          'right_sha256': hashlib.sha256(right.encode()).hexdigest() if right is not None else None})
    python_overlap.append({'path': relative, 'joint_ast_changes': joint})

deterministic = parent_integrity and other_metadata_equal and not boundary_ambiguities and protected_unambiguous
report = {
    'kind': 'read-only merge profile; not a qualification result',
    'refs': refs, 'parent_integrity': parent_checks, 'other_metadata_equal': other_metadata_equal,
    'changed_boundary_records': boundary_cases, 'ambiguous_boundary_ids': boundary_ambiguities,
    'protected': {
        'identity': 'complete canonical record with Counter multiplicity; never path identity',
        'left_removed': expanded(removed['left']), 'left_added': expanded(added['left']),
        'right_removed': expanded(removed['right']), 'right_added': expanded(added['right']),
        'shared_removed_base_records': expanded(shared_removed),
        'shared_added_full_records': expanded(shared_added),
        'unambiguous_disjoint_delta': protected_unambiguous,
        'proposed_record_count': sum(expected_protected.values()) if expected_protected is not None else None,
        'proposed_full_record_counter_digests': digested(expected_protected) if expected_protected is not None else None,
    },
    'deterministic_manifest_profile': deterministic,
    'proposed_boundary_count': len(proposed_boundaries) if not boundary_ambiguities else None,
    'common_changed_rust_files': sorted(path for path in changed['left'] & changed['right'] if path.endswith('.rs')),
    'common_changed_python_ast': python_overlap,
    'source_mutations': 0, 'tests_executed': 0, 'native_executed': False,
}
if options.check_working_tree:
    actual = tomllib.loads((ROOT / 'CALLERS.toml').read_text())
    check = {'eligible_for_exact_expected_comparison': deterministic}
    if deterministic:
        check.update(
            boundary_counter_equal=records(actual['boundary']) == records(proposed_boundaries),
            protected_counter_equal=records(actual['protected_file']) == expected_protected,
            inventory_counter_equal=Counter(actual['privileged_inventory']['required_boundary_ids']) == Counter(row['id'] for row in proposed_boundaries),
            other_metadata_equal=outside(actual) == outside(manifests['base']),
        )
    report['working_tree_manifest_check'] = check
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({
    'refs': refs, 'report': str(OUTPUT),
    'deterministic_manifest_profile': deterministic,
    'boundary_ambiguities': boundary_ambiguities,
    'shared_removed_protected_records': sum(shared_removed.values()),
    'shared_added_protected_records': sum(shared_added.values()),
    'common_changed_rust_files': report['common_changed_rust_files'],
    'working_tree_manifest_check': report.get('working_tree_manifest_check'),
}, indent=2))
