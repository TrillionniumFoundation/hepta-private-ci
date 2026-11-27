"""Read-only source/receipt binding; no producer import, model, or tests run."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile


BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = Path(__file__).resolve().parent
INPUTS = {}


def read(path):
    path = BASE / path
    data = path.read_bytes()
    INPUTS[str(path.relative_to(BASE))] = {
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return data


def document(path):
    return json.loads(read(path))


class StripReportFields(ast.NodeTransformer):
    def visit_Dict(self, node):
        self.generic_visit(node)
        removed = {'formal_fits_started', 'fresh_independent_fits_started',
                   'continuation_attempts_started', 'optimizer_update_count_scope'}
        pairs = [(k, v) for k, v in zip(node.keys, node.values)
                 if not (isinstance(k, ast.Constant) and k.value in removed)]
        node.keys, node.values = [p[0] for p in pairs], [p[1] for p in pairs]
        return node


def ast_text(data):
    return ast.dump(StripReportFields().visit(ast.parse(data)), include_attributes=False)


def main():
    manifests, sources = {}, {}
    for version in ('v3', 'v4'):
        prefix = f'c2-execution-candidate-{version}/'
        manifests[version] = document(prefix + 'PROGRAM-MANIFEST.json')
        sources[version] = {}
        for name, expected in manifests[version]['files'].items():
            data = read(prefix + name)
            assert INPUTS[prefix + name] == expected, (version, name)
            sources[version][name] = data
    a, b = sources['v3'], sources['v4']
    changed = sorted(n for n in a.keys() & b.keys() if a[n] != b[n])
    assert changed == ['c2_controller.py', 'c2_runner.py', 'test_c2_execution.py'], changed
    assert ast_text(a['c2_runner.py']) == ast_text(b['c2_runner.py'])
    controller = [ast.parse(src['c2_controller.py']) for src in (a, b)]
    functions = [{n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
                 for tree in controller]
    changed_functions = [n for n in functions[0] if ast_text(ast.unparse(functions[0][n]))
                         != ast_text(ast.unparse(functions[1][n]))]
    assert sorted(changed_functions) == ['cost_totals', 'terminal_result_gate']
    contract = json.loads(b['CONTRACT.json'])
    assert contract['cumulative_active_wall_seconds'] == 43200
    assert contract['finalization_reserve_seconds'] == 600
    assert contract['execution_authorized'] is False
    native = document('c2-native-preflight-recovered-v1/RESULT.json')
    assert native['source_before'] == native['source_after'] and native['source_unchanged']
    native_map = {n.split('/program/', 1)[1]: value
                  for n, value in native['source_before'].items() if '/program/' in n}
    for name, expected in manifests['v3']['files'].items():
        assert native_map[name] == expected, ('native-v3', name)
    assert native['status'] == 'passed_native_preflight_only'
    assert native['execution_authorized'] is False and native['real_training_optimizer_steps'] == 0
    assert len(native['attempts']) == 10
    assert all(row['returncode'] == 0 and row['status'] == 'passed' for row in native['attempts'])
    validation = document('c2-execution-validation-attempt-05/RESULT.json')
    assert validation['source_before'] == validation['source_after']
    assert validation['source_unchanged'] and validation['returncode'] == 0
    for name, expected in manifests['v4']['files'].items():
        assert validation['source_before'][name] == expected['sha256']
    capsule_path = 'c2-execution-validation-attempt-05/TESTED-SOURCE.zip'
    read(capsule_path)
    with zipfile.ZipFile(BASE / capsule_path) as capsule:
        assert capsule.testzip() is None
        assert len(capsule.namelist()) == len(set(capsule.namelist()))
        for name, expected in manifests['v4']['files'].items():
            data = capsule.read(name)
            assert len(data) == expected['bytes']
            assert hashlib.sha256(data).hexdigest() == expected['sha256']
    result = {
        'schema': 'c2-v4-budget-reporting-independent-static-review-v1',
        'scope': 'Static source/AST and retained receipts only; no production imports or model execution.',
        'changed_existing_manifest_files': changed,
        'added_manifest_files': sorted(b.keys() - a.keys()),
        'runner_AST_equal_after_stripping_only_reporting_fields': True,
        'controller_changed_functions_after_stripping_reporting_fields': changed_functions,
        'unchanged_boundary_io_recording_contract_policies': all(a[n] == b[n] for n in (
            'c2_boundary.py', 'c2_io.py', 'c2_recording.py', 'CONTRACT.json',
            'POSTERIOR-POLICY.json', 'OPTIMIZATION-POSTERIOR-POLICY-v2.json')),
        'native_v3_source_bound': True,
        'native_v3_validation_scope': '53 synthetic software tests and 6 real-parent validation-only children; no production forward/backward/update.',
        'v4_validation_scope': validation['scope'],
        'v4_fully_tested_natively': False,
        'v4_targeted_validation_original_cost': {
            k: validation[k] for k in ('whole_process_wall_seconds', 'children_cpu_seconds')},
        'slot_soft_budget_seconds': 120,
        'slot_budget_scope': 'One capture slot including all three fixed episodes, not 120 seconds per episode; soft checks, not a preemptive slot timeout.',
        'terminal_slots': ['terminal-last', 'terminal-best'],
        'cumulative_active_wall_cap_seconds': 43200,
        'finalization_reserve_seconds_inside_cap': 600,
        'finalization_completion_guaranteed': False,
        'source_blocker_identified_in_reporting_delta': False,
        'execution_authorized_by_this_review': False,
        'numerical_admission': 'HOLD', 'scientific_admission': 'HOLD',
        'inputs': INPUTS,
    }
    (OUT / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'inputs'}, indent=2))


if __name__ == '__main__':
    main()
