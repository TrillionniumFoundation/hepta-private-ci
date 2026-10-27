#!/usr/bin/env python3
"""Seal a v5 successor with only SDK startup finalization and its regression."""
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/workspace/scratch/95988d8d3ab1')
REPO = ROOT / 'hepta-private-ci'
OWN = ROOT / 'ndu-matrix-gap-fill-019-001'
OUT = OWN / 'assembly-v5-001'
PORT = 'experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/'
PROPOSAL = ROOT / 'ndu-matrix-reopen-diagnosis-v4-001/startup-budget-proposal-002'
SDK = 'codex-rs/hepta-matrix-sdk/src/sdk.rs'
TESTS = 'codex-rs/hepta-matrix-sdk/src/startup_deadline_tests.rs'


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def git(args, index=None):
    environment = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    if index:
        environment['GIT_INDEX_FILE'] = str(index)
    process = subprocess.run(['git', *args], cwd=REPO, env=environment, capture_output=True)
    report['commands'].append({'args': args, 'index': str(index) if index else None,
        'exit_code': process.returncode, 'stdout': identity(process.stdout),
        'stderr': process.stderr.decode(errors='replace')})
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors='replace'))
    return process.stdout


def entries(index):
    result = {}
    for line in git(['ls-files', '--stage', '-z'], index).split(b'\0'):
        if not line:
            continue
        header, name = line.split(b'\t', 1)
        mode, blob, stage = header.decode().split()
        assert stage == '0'
        result[name.decode()] = {'mode': mode, 'blob': blob}
    return result


OUT.mkdir(exist_ok=False)
report = {'schema': 'hepta.port-v5.source-assembly.v1',
          'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'started',
          'source': identity(Path(__file__).read_bytes()), 'commands': []}
try:
    base = git(['rev-parse', 'HEAD']).decode().strip()
    original_index = REPO / git(['rev-parse', '--git-path', 'index']).decode().strip()
    original_identity = identity(original_index.read_bytes())
    recipe_path = REPO / PORT / 'RECIPE.v4.json'
    previous_bytes = recipe_path.read_bytes()
    assert identity(previous_bytes)['sha256'] == '5bd5cd193ba9824c2010157be58bc775c984fd8211d77c6e8df0d4c1b275e2d5'
    previous = json.loads(previous_bytes)
    previous_patch = REPO / previous['patch_path']
    assert identity(previous_patch.read_bytes())['sha256'] == previous['patch_sha256']
    review_path = PROPOSAL / 'FINALIZATION_DEADLINE_REVIEW.json'
    review = json.loads(review_path.read_text())
    delta = PROPOSAL / 'FINALIZATION_DEADLINE_FORMATTED.patch'
    assert identity(delta.read_bytes())['sha256'] == review['patch']['sha256']
    assert set(review['before']) == set(review['after']) == {SDK, TESTS}
    for name, expected in review['after'].items():
        assert identity((PROPOSAL / 'proposed-formatted' / name).read_bytes())['sha256'] == expected['sha256']
    indices = [OUT / name for name in ('base.index', 'v4.index', 'v5.index')]
    for index in indices:
        git(['read-tree', base], index)
    inherited = entries(indices[0])
    for index in indices[1:]:
        git(['apply', '--cached', str(previous_patch)], index)
    prior = entries(indices[1])
    for name, expected in review['before'].items():
        assert identity(git(['cat-file', 'blob', prior[name]['blob']]))['sha256'] == expected['sha256']
    git(['apply', '--cached', str(delta)], indices[2])
    current = entries(indices[2])
    differences = {name for name in set(prior) | set(current) if prior.get(name) != current.get(name)}
    assert differences == {SDK, TESTS}
    allowed = set(previous['allowed_paths'])
    changed = {name for name in set(inherited) | set(current) if inherited.get(name) != current.get(name)}
    assert changed == allowed and len(allowed) == 31
    assert all(current.get(name) == value for name, value in inherited.items() if name not in allowed)
    assert all(current[name] == prior[name] for name in allowed - differences)
    inventory = {}
    for name in sorted(allowed):
        row = current[name]
        data = git(['cat-file', 'blob', row['blob']])
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == row['blob']
        assert row['mode'] == '100644'
        if name in differences:
            assert data == (PROPOSAL / 'proposed-formatted' / name).read_bytes()
        inventory[name] = {**row, **identity(data)}
    patch = git(['diff', '--cached', '--binary', '--full-index', '--no-renames', base, '--'], indices[2])
    new_patch_path = REPO / PORT / 'combined-source-v5.patch'
    new_recipe_path = REPO / PORT / 'RECIPE.v5.json'
    assert not new_patch_path.exists() and not new_recipe_path.exists()
    recipe = copy.deepcopy(previous)
    recipe['patch_path'] = str(new_patch_path.relative_to(REPO))
    recipe['patch_sha256'] = identity(patch)['sha256']
    recipe['revision'] = {'number': 5,
        'previous_recipe_sha256': identity(previous_bytes)['sha256'],
        'previous_patch_sha256': previous['patch_sha256'], 'failed_run_id': 40503203294,
        'purpose': 'Complete the shared startup deadline acceptance check after session persistence and around identity/cache finalization on all three success routes. Add one regression preserving an already written private session after an expired completion. V4 and all earlier source/evidence remain frozen; dependency, vendor, fixture and request-budget constraints are unchanged.'}
    assert {name for name in recipe if recipe[name] != previous[name]} == {'patch_path', 'patch_sha256', 'revision'}
    assert len(recipe['expected_packages']) == 52
    assert [recipe['aws_qualification'][key] for key in ('expected_total', 'expected_executed', 'expected_ignored')] == [245, 244, 1]
    count = 0
    for directory, files in recipe['vendor_dirs'].items():
        for name, expected in files.items():
            assert identity((REPO / directory / name).read_bytes()) == expected
            count += 1
    assert count == 1971
    assert recipe_path.read_bytes() == previous_bytes
    assert identity(previous_patch.read_bytes())['sha256'] == previous['patch_sha256']
    assert identity(original_index.read_bytes()) == original_identity
    assert git(['rev-parse', 'HEAD']).decode().strip() == base
    tree = git(['write-tree', '--missing-ok'], indices[2]).decode().strip()
    with new_patch_path.open('xb') as stream:
        stream.write(patch)
    with new_recipe_path.open('xb') as stream:
        stream.write((json.dumps(recipe, indent=2) + '\n').encode())
    report.update(status='source_candidate_assembled_not_runtime_qualified', source_commit=base,
        source_only_candidate_tree=tree, candidate_v4_differences=sorted(differences),
        allowed_path_count=31, unchanged_candidate_paths_from_v4=29,
        vendor_files_verified=1971, package_constraints=52, aws_constraints=[245, 244, 1],
        previous_recipe=identity(previous_bytes), previous_patch=identity(previous_patch.read_bytes()),
        recipe_v5={'path': str(new_recipe_path.relative_to(REPO)), **identity(new_recipe_path.read_bytes())},
        patch_v5={'path': str(new_patch_path.relative_to(REPO)), **identity(patch)},
        delta_patch=identity(delta.read_bytes()), source_inventory=inventory,
        original_index_unchanged=True, original_head_unchanged=True,
        actual_cargo_bazel_or_test_execution=False, dependency_or_policy_activation=False,
        promisor_boundary='All 31 changed blobs were read and independently rehashed. Only unchanged inherited path/mode/OID entries may remain unmaterialized before write-tree --missing-ok.')
except Exception as error:
    report.update(status='failed', error_type=type(error).__name__, error=str(error))
    raise
finally:
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    (OUT / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'result': str(OUT / 'RESULT.json'),
                      **identity((OUT / 'RESULT.json').read_bytes())}))
