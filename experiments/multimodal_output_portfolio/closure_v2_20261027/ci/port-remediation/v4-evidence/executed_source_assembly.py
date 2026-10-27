#!/usr/bin/env python3
"""Create a source-only v4 successor without mutating any frozen recipe."""
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
OUT = OWN / 'assembly-v4-001'
PORT = 'experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/'
GAP = 'codex-rs/hepta-matrix-sdk/src/gap_fill_tests.rs'
SDK = 'codex-rs/hepta-matrix-sdk/src/sdk.rs'
DEADLINE_TESTS = 'codex-rs/hepta-matrix-sdk/src/startup_deadline_tests.rs'
STARTUP_INPUT = OWN / 'STARTUP_FINAL_INPUT.json'


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
report = {'schema': 'hepta.port-v4.source-assembly.v1', 'started_at': datetime.now(timezone.utc).isoformat(),
          'status': 'started', 'source': identity(Path(__file__).read_bytes()), 'commands': []}
try:
    base = git(['rev-parse', 'HEAD']).decode().strip()
    original_index = REPO / git(['rev-parse', '--git-path', 'index']).decode().strip()
    original_identity = identity(original_index.read_bytes())
    v3_path = REPO / PORT / 'RECIPE.v3.json'
    previous_bytes = v3_path.read_bytes()
    assert identity(previous_bytes)['sha256'] == 'b3936e6c2385d8fe93e30cc2ebb904dda43a9e86174fd3e9d427459ddd69629c'
    previous = json.loads(previous_bytes)
    previous_patch = REPO / previous['patch_path']
    assert identity(previous_patch.read_bytes())['sha256'] == previous['patch_sha256']
    gap_patch = OWN / 'GAP_FILL_019_FORMATTED.patch'
    proposed = OWN / 'proposed-formatted' / GAP
    review = json.loads((OWN / 'GAP_FILL_019_FORMATTED_REVIEW.json').read_text())
    assert identity(gap_patch.read_bytes())['sha256'] == review['patch_sha256']
    assert identity(proposed.read_bytes())['sha256'] == review['after_sha256']
    startup = json.loads(STARTUP_INPUT.read_text())
    startup_patch = Path(startup['patch_path'])
    assert identity(startup_patch.read_bytes())['sha256'] == startup['patch_sha256']
    assert set(startup['sources']) == {SDK, DEADLINE_TESTS}
    for name, entry in startup['sources'].items():
        assert identity(Path(entry['path']).read_bytes())['sha256'] == entry['sha256']
    baseline_index, v3_index, v4_index = (OUT / n for n in ['base.index', 'v3.index', 'v4.index'])
    for index in [baseline_index, v3_index, v4_index]:
        git(['read-tree', base], index)
    inherited = entries(baseline_index)
    for index in [v3_index, v4_index]:
        git(['apply', '--cached', str(previous_patch)], index)
    git(['apply', '--cached', str(gap_patch)], v4_index)
    git(['apply', '--cached', str(startup_patch)], v4_index)
    prior, current = entries(v3_index), entries(v4_index)
    differences = {name for name in set(prior) | set(current) if prior.get(name) != current.get(name)}
    assert differences == {GAP, SDK, DEADLINE_TESTS}
    assert git(['cat-file', 'blob', current[GAP]['blob']]) == proposed.read_bytes()
    for name, entry in startup['sources'].items():
        assert git(['cat-file', 'blob', current[name]['blob']]) == Path(entry['path']).read_bytes()
    allowed = set(previous['allowed_paths']) | {GAP, DEADLINE_TESTS}
    changed = {name for name in set(inherited) | set(current) if inherited.get(name) != current.get(name)}
    assert changed == allowed and len(allowed) == 31
    assert all(current.get(name) == value for name, value in inherited.items() if name not in allowed)
    inventory = {}
    for name in sorted(allowed):
        row = current[name]
        data = git(['cat-file', 'blob', row['blob']])
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == row['blob']
        assert row['mode'] == '100644'
        inventory[name] = {**row, **identity(data)}
    patch_path = REPO / PORT / 'combined-source-v4.patch'
    assert not patch_path.exists()
    patch = git(['diff', '--cached', '--binary', '--full-index', '--no-renames', base, '--'], v4_index)
    recipe = copy.deepcopy(previous)
    recipe['patch_path'] = str(patch_path.relative_to(REPO))
    recipe['patch_sha256'] = identity(patch)['sha256']
    recipe['allowed_paths'] = sorted(allowed)
    recipe['revision'] = {
        'number': 4,
        'previous_recipe_sha256': identity(previous_bytes)['sha256'],
        'previous_patch_sha256': previous['patch_sha256'],
        'failed_run_id': 40503203294,
        'purpose': 'Port the actual SDK 0.19 TimelineEvent metadata test while retaining out-of-raw retention and in-raw bundle bounds. Separate encrypted store initialization from the five-second request budget using one shared startup deadline across authentication and fresh-client fallback, with expiry regression tests. V3 source and failure evidence remain preserved; old-state artifact permission restoration is separately repaired in the source-bound base driver.'}
    recipe_path = REPO / PORT / 'RECIPE.v4.json'
    assert not recipe_path.exists()
    recipe_bytes = (json.dumps(recipe, indent=2) + '\n').encode()
    assert {name for name in recipe if recipe[name] != previous[name]} == {'patch_path', 'patch_sha256', 'allowed_paths', 'revision'}
    assert len(recipe['expected_packages']) == 52
    count = 0
    for directory, files in recipe['vendor_dirs'].items():
        for name, expected in files.items():
            assert identity((REPO / directory / name).read_bytes()) == expected
            count += 1
    assert count == 1971
    assert v3_path.read_bytes() == previous_bytes
    assert identity(previous_patch.read_bytes())['sha256'] == previous['patch_sha256']
    assert identity(original_index.read_bytes()) == original_identity
    assert git(['rev-parse', 'HEAD']).decode().strip() == base
    candidate_tree = git(['write-tree', '--missing-ok'], v4_index).decode().strip()
    with patch_path.open('xb') as stream:
        stream.write(patch)
    with recipe_path.open('xb') as stream:
        stream.write(recipe_bytes)
    report.update(status='source_candidate_assembled_not_runtime_qualified', source_commit=base,
        source_only_candidate_tree=candidate_tree,
        candidate_v3_differences=sorted(differences), allowed_path_count=31, vendor_files_verified=1971,
        package_constraints=52, unchanged_inherited_entries=len(set(inherited) - allowed),
        previous_recipe=identity(previous_bytes), previous_patch=identity(previous_patch.read_bytes()),
        recipe_v4={'path': str(recipe_path.relative_to(REPO)), **identity(recipe_path.read_bytes())},
        patch_v4={'path': str(patch_path.relative_to(REPO)), **identity(patch)},
        source_inventory=inventory, original_index_unchanged=True, original_head_unchanged=True,
        dependency_or_policy_activation=False, actual_cargo_bazel_or_test_execution=False,
        promisor_boundary='Only unchanged inherited path/mode/OID entries may remain unmaterialized; all 31 changed blobs were read and independently rehashed before write-tree --missing-ok.')
except Exception as error:
    report.update(status='failed', error_type=type(error).__name__, error=str(error))
    raise
finally:
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    (OUT / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'result': str(OUT / 'RESULT.json'),
                      **identity((OUT / 'RESULT.json').read_bytes())}))
