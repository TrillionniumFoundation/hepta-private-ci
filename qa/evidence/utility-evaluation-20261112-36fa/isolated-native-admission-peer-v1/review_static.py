"""Read-only identity/AST review. Does not import or execute a control module."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-isolated-native-admission-v1')
BASE = Path('/tmp/hepta-36fa-cc57-admission-successor-v2')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def definitions(raw):
    source = raw.decode()
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.get_source_segment(source, node)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[node.name + '.' + child.name] = ast.get_source_segment(source, child)
    return out


def review():
    old = (BASE / 'qualification-admission.cc57.HOLD.py').read_bytes()
    v1 = (ROOT / 'qualification-admission.isolated.HOLD.py').read_bytes()
    v2 = (ROOT / 'qualification-admission.isolated-v2.HOLD.py').read_bytes()
    assert pin(old)['git_blob'] == 'a8be08b6cb00536817e2d68c42fa4b90d1e9ff72'
    assert pin(v1)['git_blob'] == 'a529365ee8305b9a76fcdbfe3be8b19527d03591'
    assert pin(v2)['git_blob'] == '23d412ed67927a6cbfa5f521884e891afc93eb6f'
    before, after = definitions(old), definitions(v2)
    changed = sorted(k for k in before if before[k] != after[k])
    assert changed == ['Admission.__init__', 'Admission.acquire_and_validate',
                       'Admission.before_native_stage', 'Admission.finish']
    assert set(after) - set(before) == {'Admission.validate_materialization'}
    first = definitions(v1)
    assert [k for k in first if first[k] != after[k]] == ['Admission.validate_materialization']
    previous = json.loads((BASE / 'QUALIFICATION_INPUT.cc57-v2.HOLD.json').read_bytes())
    config = json.loads((ROOT / 'WAITING_QUALIFICATION_INPUT_V2.json').read_bytes())
    preserved = ['runtime_guard', 'full_physical_inventory', 'expected_inventory_sha256',
                 'expected_file_count', 'final_format', 'canonical_alignment', 'source',
                 'tree', 'parents', 'coordination_lock', 'positive_eval_cases',
                 'native_driver_pin', 'plan_pin', 'maintenance_guard_path',
                 'inventory_driver_path', 'actual_final_format_postimages_reviewed',
                 'reviewed_formatter_changed_paths', 'source_gates_config_path',
                 'source_gates_config_pin', 'source_gates_handoff_records', 'records_parent']
    for name in preserved:
        assert previous[name] == config[name], name
    assert config['root_execution_approved'] is False
    assert config['state'] != 'READY_FOR_FINAL_SOURCE_QUALIFICATION'
    assert all(config['isolated_materialization'][k] is None for k in ('job_id', 'result', 'supervisor'))
    assert config['runtime_guard']['minimum_target_free_bytes'] == 32 * 1024**3
    assert config['runtime_guard']['create_target_if_absent'] is False
    return {'format': 'hepta-isolated-native-admission-independent-static-review-v1',
            'base': pin(old), 'v1': pin(v1), 'v2': pin(v2),
            'config': pin((ROOT / 'WAITING_QUALIFICATION_INPUT_V2.json').read_bytes()),
            'old_definitions': len(before), 'changed_definitions': changed,
            'unchanged_definitions': sorted(set(before) - set(changed)),
            'added_definitions': sorted(set(after) - set(before)),
            'unchanged_configuration_keys': preserved,
            'actual_success_proofs_null': True, 'HOLD': True,
            'admission_constructor_called': False, 'control_main_called': False,
            'H_calls': 0, 'source_mutations': 0, 'qualification': False}


if __name__ == '__main__':
    print(json.dumps(review(), indent=2, sort_keys=True))
