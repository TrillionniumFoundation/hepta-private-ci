#!/usr/bin/env python3
"""Read-only static consistency check for the scoped recovery docs/workflow update."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import yaml

root = Path(__file__).resolve().parent / 'hepta'
BASELINE = '7530e4bc7aa61a0c23a5933fef4a65d86a586cf8'
sys.path.insert(0, str(root / 'scripts'))
from lane_a_foundation_core import EXPECTED_MODULES, MIGRATIONS, SECTIONS
from lane_a_foundation_lib import validate_matrix


def previous(path):
    return subprocess.check_output(['git', 'show', BASELINE + ':' + path], cwd=root).decode()


def workflow(text):
    jobs = yaml.safe_load(text)['jobs']
    job = next(job for job in jobs.values() if any('recovery-owner.json' in step.get('run', '') for step in job['steps']))
    runs = {name: next(step['run'] for step in job['steps'] if name + '.json' in step.get('run', '')) for name in ('recovery-owner', 'recovery-signed')}
    block = next(step['run'] for step in job['steps'] if step.get('name') == 'Require every selected test by name with no selected skip')
    source = block.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    parsed = ast.parse(source)
    compile(parsed, '<workflow-roster>', 'exec')
    bindings = [node for node in parsed.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('prefix', 'expected')]
    allowed = (ast.Module, ast.Assign, ast.Name, ast.Store, ast.Constant, ast.Dict, ast.Set, ast.SetComp, ast.BinOp, ast.Add, ast.BitOr, ast.comprehension, ast.Load, ast.Tuple)
    module = ast.Module(body=bindings, type_ignores=[])
    assert all(isinstance(node, allowed) for node in ast.walk(module))
    namespace = {'__builtins__': {}}
    exec(compile(module, '<workflow-roster-bindings>', 'exec'), namespace)
    for script in [*runs.values(), block]:
        subprocess.run(['bash', '-n'], input=script.encode(), check=True)
    return job, runs, namespace['expected']

path = '.github/workflows/hepta-pq-policy-renewal.yml'
old_job, old_runs, old_roster = workflow(previous(path))
job, runs, roster = workflow((root / path).read_text())
assert job['timeout-minutes'] == old_job['timeout-minutes'] == 90
source_files = {
    'recovery_effect_frontier_tests': 'codex-rs/hepta-evidence/src/recovery_effect_frontier_tests.rs',
    'provider_effect_recovery_provenance_tests': 'codex-rs/hepta-evidence/src/provider_effect_recovery_provenance_tests.rs',
    'recovery_invocation_frontier_tests': 'codex-rs/hepta-evidence/src/recovery_invocation_frontier_tests.rs',
    'recovery_invocation_schema_tests': 'codex-rs/hepta-evidence/src/recovery_invocation_schema_tests.rs',
    'evidence_frontier::tests': 'codex-rs/hepta-agentd/src/evidence_frontier_tests.rs',
}
for name, count, original in [('recovery-owner', 17, 7), ('recovery-signed', 11, 9)]:
    selected = re.findall(r'test\(=([^()]+)\)', runs[name])
    before = re.findall(r'test\(=([^()]+)\)', old_runs[name])
    assert len(before) == original and len(selected) == count
    assert len(set(selected)) == count and set(selected) == roster[name]
    assert old_roster[name] == set(before) and set(before) < set(selected)
    assert int(re.search(r'--minimum-tests (\d+)', runs[name])[1]) == count
    assert re.search(r'--timeout-seconds (\d+)', runs[name])[1] == re.search(r'--timeout-seconds (\d+)', old_runs[name])[1] == '600'
    assert '--no-capture --retries 0 --test-threads=1' in runs[name]
    for test in selected:
        module, function = test.rsplit('::', 1)
        assert re.search(r'async fn\s+' + re.escape(function) + r'\s*\(', (root / source_files[module]).read_text()), test
for name in set(roster) - set(runs):
    assert roster[name] == old_roster[name]
assert 'mod recovery_invocation_schema_tests;' in (root / 'codex-rs/hepta-evidence/src/lib.rs').read_text()
for module, count in [('recovery_invocation_frontier_tests', 7), ('recovery_invocation_schema_tests', 3)]:
    source_tests = re.findall(r'#\[tokio::test\]\s+async fn\s+(\w+)\s*\(', (root / source_files[module]).read_text())
    assert len(source_tests) == count
    assert {module + '::' + test for test in source_tests} <= roster['recovery-owner']
assert 'mod recovery_invocation_frontier_tests;' in (root / 'codex-rs/hepta-evidence/src/lib.rs').read_text()
assert '#[path = "evidence_frontier_tests.rs"]' in (root / 'codex-rs/hepta-agentd/src/evidence_frontier.rs').read_text()

matrix_path = 'docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json'
capability_path = 'docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json'
matrix = json.loads((root / matrix_path).read_text())
old_matrix = json.loads(previous(matrix_path))
capability = json.loads((root / capability_path).read_text())
old_capability = json.loads(previous(capability_path))
evidence = next(row for row in matrix['modules'] if row['module'] == 'kernel.evidence')
old_evidence = next(row for row in old_matrix['modules'] if row['module'] == 'kernel.evidence')
assert evidence['states']['durability'] == 'sqlite_migrations_0001_0016'
assert {k: v for k, v in evidence['states'].items() if k != 'durability'} == {k: v for k, v in old_evidence['states'].items() if k != 'durability'}
assert [m['module'] for m in matrix['modules']] == EXPECTED_MODULES
old_modules = {m['module']: m for m in old_matrix['modules']}
assert set(old_modules) == set(EXPECTED_MODULES)
for module in matrix['modules']:
    if module['module'] != 'kernel.evidence':
        assert {k: v for k, v in module.items() if k != 'sourceAnchors'} == {k: v for k, v in old_modules[module['module']].items() if k != 'sourceAnchors'}
assert {k: v for k, v in matrix.items() if k != 'modules'} == {k: v for k, v in old_matrix.items() if k != 'modules'}
entries = [e for e in capability['entries'] if e['module'] == 'kernel.evidence']
old_entries = [e for e in old_capability['entries'] if e['module'] == 'kernel.evidence']
assert len(entries) == len(old_entries) == 5
old_by_id = {e['capabilityId']: e for e in old_capability['entries']}
assert set(old_by_id) == {e['capabilityId'] for e in capability['entries']}
for entry in capability['entries']:
    old = old_by_id[entry['capabilityId']]
    for field in ('activation', 'receiptStatus', 'productionCaller'):
        assert entry[field] == old[field]
    if entry['module'] != 'kernel.evidence':
        updated = {'sourceEvidence', 'positiveTests', 'negativeTests', 'callerEvidence'}
        if entry['capabilityId'] == 'kernel.operations.agentd-daemon-composition.v1':
            updated.add('publicSymbols')
            assert entry['publicSymbols'] == ['AgentdConfig::with_production_operations', 'AgentdProductionOperationRuntimeConfig::new', 'AgentdProductionOperationRuntimeConfig::validate_for']
        assert {k: v for k, v in entry.items() if k not in updated} == {k: v for k, v in old.items() if k not in updated}
for current, old in zip(entries, old_entries):
    assert current['capabilityId'] == old['capabilityId']
    for field in ('activation', 'receiptStatus', 'productionCaller'):
        assert current[field] == old[field]
    if current['capabilityId'] != 'kernel.evidence.recovery-frontier.v1':
        assert {k: v for k, v in current.items() if k != 'durability'} == {k: v for k, v in old.items() if k != 'durability'}
validate_matrix(matrix, root)
old_core = ast.parse(previous('scripts/lane_a_foundation_core.py'))
old_constants = {node.targets[0].id: ast.literal_eval(node.value) for node in old_core.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('SECTIONS', 'EXPECTED_MODULES', 'MIGRATIONS')}
assert SECTIONS == old_constants['SECTIONS'] and EXPECTED_MODULES == old_constants['EXPECTED_MODULES']
assert MIGRATIONS[:len(old_constants['MIGRATIONS'])] == old_constants['MIGRATIONS']
assert MIGRATIONS == sorted(p.name for p in (root / 'codex-rs/hepta-evidence/migrations').glob('*.sql'))
binding_path = 'qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json'
binding = json.loads((root / binding_path).read_text()); old_binding = json.loads(previous(binding_path))
assert {k: v for k, v in binding.items() if k not in ('observations', 'sourceObservationDigest')} == {k: v for k, v in old_binding.items() if k not in ('observations', 'sourceObservationDigest')}
for current, old in zip(binding['observations'], old_binding['observations']):
    if current['module'] == 'kernel.authority':
        assert {k: v for k, v in current.items() if k != 'exports'} == {k: v for k, v in old.items() if k != 'exports'}
        assert set(current['exports']) == (set(old['exports']) - {'verify_strict'}) | {'grant_signing_input', 'PinnedAuthorityKey'}
    else:
        assert current == old
assert binding['sourceObservationDigest'] == hashlib.sha256(json.dumps(binding['observations'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
versions = sorted(int(p.name.split('_', 1)[0]) for p in (root / 'codex-rs/hepta-evidence/migrations').glob('*.sql'))
assert versions == list(range(1, 17))
assert '("kernel.evidence", "durability"): "sqlite_migrations_0001_0016"' in (root / 'scripts/lane_a_foundation_lib.py').read_text()
print('PASS: YAML/shell/Python syntax; original 7+9 IDs retained; exact 17/11 selectors, declared source names, minima and 600s budgets; other rosters unchanged.')
print('PASS: complete Lane-A static gate, canonical 7-module/42-capability order, current callsite/test anchors and migrations 0001..0016; original sections/roster guards and acceptance/activation/receipt boundaries retained.')
print('PASS: native-binding historical commit/blob provenance and false proof states unchanged; current required symbols and observation digest agree with the existing verifier definition.')
print('Scoped static verification only; native execution and independent acceptance are not claimed.')
