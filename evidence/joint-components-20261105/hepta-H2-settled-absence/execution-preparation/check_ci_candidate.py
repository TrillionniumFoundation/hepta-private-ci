import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import yaml

root = Path(__file__).resolve().parent
rel = Path('.github/workflows/hepta-pq-policy-renewal.yml')
base = yaml.safe_load((root / 'base' / rel).read_text())
new = yaml.safe_load((root / 'candidate' / rel).read_text())
old_job = base['jobs']['policy-renewal']
new_job = new['jobs']['policy-renewal']
assert {k: v for k, v in old_job.items() if k != 'steps'} == {
    k: v for k, v in new_job.items() if k != 'steps'
}
assert old_job['timeout-minutes'] == new_job['timeout-minutes'] == 90
old_steps = {s.get('name', s.get('uses', s.get('run'))): s for s in old_job['steps']}
new_steps = {s.get('name', s.get('uses', s.get('run'))): s for s in new_job['steps']}
added = set(new_steps) - set(old_steps)
assert added == {'Run the two settled absence history and corruption controls'}
changed = [name for name, step in old_steps.items() if new_steps[name] != step]
assert changed == [
    'Require every selected test by name with no selected skip',
    'Run the original scoped linter and retain any source mutation as failure',
]
lint_name = changed[1]
assert new_steps[lint_name]['run'] == old_steps[lint_name]['run'] + ' -p codex-hepta-automation'
assert [s.get('name', s.get('uses', s.get('run'))) for s in new_job['steps'] if s.get('name') not in added] == list(old_steps)

def guard(workflow):
    job = workflow['jobs']['policy-renewal']
    step = next(s for s in job['steps'] if s.get('name') == changed[0])
    code = step['run'].split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    tree = ast.parse(code)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id in {'prefix', 'expected'} for t in node.targets)]
    scope = {}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), '<guard inventory>', 'exec'), scope)
    return code, scope['expected']

old_code, old_expected = guard(base)
code, expected = guard(new)
assert sum(map(len, old_expected.values())) == 69
assert sum(map(len, expected.values())) == 71
assert {k: v for k, v in expected.items() if k != 'effect-settled-absence'} == old_expected
new_names = expected['effect-settled-absence']
assert len(new_names) == 2
source = (root / 'candidate/codex-rs/hepta-automation/tests/support/authorized_owner_recovery_tests.rs').read_text()
for name in new_names:
    assert source.count('async fn ' + name.split('::')[-1] + '(') == 1
step = new_steps[next(iter(added))]
for value in ['--minimum-tests 2 --timeout-seconds 600', '-p codex-hepta-automation --test authorized_effect', '--no-capture --retries 0 --test-threads=1']:
    assert value in step['run']
assert all('test(=' + name + ')' in step['run'] for name in new_names)

out = root / 'ci-static-controls'
out.mkdir(exist_ok=True)
script = out / 'selected-tests-guard.py'
script.write_text(code)
controls = []
for variant in ['complete_inventory', 'missing_new_receipt', 'selected_new_skip', 'duplicate_new_case']:
    fixture = out / variant
    fixture.mkdir(exist_ok=True)
    for gate, names in expected.items():
        cases = [(name, 'ok') for name in sorted(names)]
        if gate == 'effect-settled-absence':
            if variant == 'missing_new_receipt':
                continue
            if variant == 'selected_new_skip':
                cases[0] = (cases[0][0], 'ignored')
            if variant == 'duplicate_new_case':
                cases[1] = cases[0]
        raw = ('Synthetic selected-name guard fixture; this is not native test output.\n'
               + ''.join(f'test {name} ... {status}\n' for name, status in cases)).encode()
        log_name = gate + '.fixture.log'
        (fixture / log_name).write_bytes(raw)
        receipt = {'status': 'passed', 'command_exit_code': 0, 'log_file': log_name,
                   'log_sha256': hashlib.sha256(raw).hexdigest(),
                   'observed_passed_tests': sum(status == 'ok' for _, status in cases),
                   'observed_failed_tests': 0}
        (fixture / (gate + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    ran = subprocess.run([sys.executable, str(script), str(fixture)], capture_output=True, text=True)
    valid = ran.returncode == (0 if variant == 'complete_inventory' else 1)
    controls.append({'name': variant, 'exit_code': ran.returncode, 'expected_behavior_observed': valid,
                     'stdout': ran.stdout, 'stderr': ran.stderr})
    assert valid, controls[-1]
record = {'scope': 'synthetic CI name-guard controls and exact source comparison; zero native credit',
          'original_selected_cases': 69, 'new_selected_cases': 2, 'total_selected_cases': 71,
          'original_test_steps_byte_equivalent_after_yaml_parse': True,
          'job_matrix_environment_and_timeout_unchanged': True,
          'original_step_order_preserved': True,
          'per_test_configuration_unchanged': True,
          'new_step_timeout_seconds': 600, 'job_timeout_seconds': 5400,
          'scoped_lint_change': 'append only codex-hepta-automation; original timeout 1200',
          'guard_sha256': hashlib.sha256(code.encode()).hexdigest(), 'controls': controls,
          'new_names': sorted(new_names)}
(out / 'proof.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
