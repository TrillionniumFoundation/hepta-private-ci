#!/usr/bin/env python3
"""Bind Root's three actual input files; never execute any prepared launch code."""
import ast
import base64
import copy
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v1')
PRIOR = Path('/tmp/hepta-36fa-final-source-qualification-launch-v1')
HOLD = Path('/tmp/hepta-36fa-source-qualification-cc57-hold-v1')
FORMAL = Path('/tmp/hepta-36fa-cc57-qualification-root-inputs-v1')
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v1'
KEY = 'hepta-utility-36fa-final-source-gates-cc57-v1'
SOURCE = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
ACTUAL = {
    'APPROVED_QUALIFICATION_INPUT.json': {
        'path': FORMAL / 'APPROVED_FINAL_QUALIFICATION_INPUT.json',
        'pin': {'bytes': 10960, 'sha256': '7fec117538bed151be59fdf90ed889f8840ae88832a658aab0d9a8b74b6d38ab', 'git_blob': '2a19b2b6b27f885dc3791897dad8c9e51f305ae0'},
    },
    'APPROVED_SOURCE_GATES_CONFIG.json': {
        'path': FORMAL / 'APPROVED_FINAL_SOURCE_GATES_CONFIG.json',
        'pin': {'bytes': 820, 'sha256': '14b00eb4f614036e58a19c8a2ba087c421fc8d8f57bb562a7b226721159097b9', 'git_blob': 'b312db80c69df6479436a1ae20ad7c716d699f89'},
    },
    'CANONICAL_ALIGNMENT_NORMAL.original.json': {
        'path': Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1/STATUS_01.original.json'),
        'pin': {'bytes': 953, 'sha256': '084fb2db14e845c889ca3be77e10883ee9318b88b0700254f2126aa816a42e83', 'git_blob': '041ee7bcd32bcab8f7bedec17ac998cfd929326f'},
    },
}


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def jbytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def save(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return {'path': str(path), **pin(raw)}


def main():
    OUT.mkdir(exist_ok=True)
    # Import only the pure, retained local preparation helpers; its main is not invoked.
    spec = importlib.util.spec_from_file_location('retained_cc57_hold_helpers', HOLD / 'prepare_hold.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    originals = {name: (PRIOR / name).read_bytes() for name in helper.ORIGINALS}
    for name, raw in originals.items():
        assert pin(raw) == helper.ORIGINALS[name], name
    old = originals['ACTUAL_SOURCE_BOOTSTRAP.py'].decode()
    old_ast = ast.parse(old)
    old_pins = ast.literal_eval(helper.assignment(old_ast, 'PINS').value)
    old_stdin = json.loads(originals['ACTUAL_SOURCE_STDIN.json'])
    old_typed = json.loads(originals['ACTUAL_SOURCE_PROCESS_INPUT.json'])
    old_manifest = json.loads(originals['EXACT_SOURCE_LAUNCH_MANIFEST.json'])
    assert old_manifest['eight_input_pins'] == old_pins
    assert old_typed['args'] == ['-B', '-c', old]
    assert old_typed['stdin'].encode() == originals['ACTUAL_SOURCE_STDIN.json']
    assert old_typed['timeout_seconds'] == 7200 == old_manifest['outer_seconds']
    assert old_typed['idempotency_key'] != KEY
    files = {}
    for name, original_pin in old_pins.items():
        raw = base64.b64decode(old_stdin['files'][name], validate=True)
        assert pin(raw) == original_pin
        if name in ACTUAL:
            raw = ACTUAL[name]['path'].read_bytes()
            assert pin(raw) == ACTUAL[name]['pin'], name
        files[name] = raw
    assert len(files) == 8 and set(files) == set(old_pins)
    inputs = {name: save('inputs/' + name, raw) for name, raw in files.items()}
    new_pins = {name: pin(raw) for name, raw in files.items()}
    assert [name for name in new_pins if new_pins[name] != old_pins[name]] == list(ACTUAL)

    cfg = json.loads(files['APPROVED_QUALIFICATION_INPUT.json'])
    source_cfg = json.loads(files['APPROVED_SOURCE_GATES_CONFIG.json'])
    normal_outer = json.loads(files['CANONICAL_ALIGNMENT_NORMAL.original.json'])
    assert normal_outer['isError'] is False
    normal = json.loads(normal_outer['content'][0]['text'])
    assert normal['job_id'] == cfg['canonical_alignment']['job_id'] == '1a1d223a60b-2564-1ca3'
    assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
    assert normal['output_complete'] and normal['output_durable'] and normal['terminal_publication_confirmed']
    assert not normal['timed_out'] and not normal['cancelled'] and not normal['automatic_retry']
    assert cfg['canonical_alignment']['supervisor'] == new_pins['CANONICAL_ALIGNMENT_NORMAL.original.json']
    assert cfg['canonical_alignment']['supervisor_path'] == BASE + '/CANONICAL_ALIGNMENT_NORMAL.original.json'
    assert cfg['source'] == source_cfg['source_sha'] == SOURCE
    assert cfg['tree'] == source_cfg['source_tree'] == TREE
    assert cfg['parents'] == ['246d8cb614770252ee42029a5c014f2a4904176a']
    assert cfg['root_execution_approved'] is True
    assert cfg['source_gates_config_path'] == BASE + '/APPROVED_SOURCE_GATES_CONFIG.json'
    assert cfg['source_gates_config_pin'] == new_pins['APPROVED_SOURCE_GATES_CONFIG.json']
    assert source_cfg['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
    assert source_cfg['driver_sha256'] == '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2'
    assert cfg['expected_file_count'] == 15188
    assert cfg['expected_inventory_sha256'] == '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9'
    assert cfg['full_physical_inventory']['sha256'] == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
    for name, key in [('qualification-admission.py', 'admission'), ('native-driver.original.py', 'native_driver'), ('PLAN.original.json', 'plan')]:
        assert cfg[key + '_pin'] == new_pins[name]
        assert cfg[key + '_path'] == BASE + '/' + name

    old_base = ast.get_source_segment(old, helper.assignment(old_ast, 'BASE'))
    old_pin_text = ast.get_source_segment(old, helper.assignment(old_ast, 'PINS'))
    new_base = 'BASE = pathlib.Path(' + repr(BASE) + ')'
    new_pin_text = 'PINS = ' + repr(new_pins)
    assert old.count(old_base) == old.count(old_pin_text) == 1
    candidate = old.replace(old_base, new_base, 1).replace(old_pin_text, new_pin_text, 1)
    assert candidate.replace(new_base, old_base, 1).replace(new_pin_text, old_pin_text, 1) == old
    parsed = ast.parse(candidate)
    normalized = copy.deepcopy(parsed)
    for name in ('BASE', 'PINS'):
        helper.assignment(normalized, name).value = copy.deepcopy(helper.assignment(old_ast, name).value)
    assert ast.dump(normalized, include_attributes=False) == ast.dump(old_ast, include_attributes=False)
    assert helper.functions(old) == helper.functions(candidate)
    compile(candidate, str(OUT / 'SOURCE_BOOTSTRAP.candidate.py'), 'exec')  # no execution
    stage_try = next(node for node in parsed.body if isinstance(node, ast.Try))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'exec' for node in ast.walk(stage_try))
    top_exec = [node for node in parsed.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'exec']
    assert len(top_exec) == 1 and parsed.body.index(top_exec[0]) > parsed.body.index(stage_try)
    marker = '# Main failure is owned by the unchanged original wrapper, not the stager.'
    assert candidate.split(marker, 1)[1] == old.split(marker, 1)[1]

    stdin = copy.deepcopy(old_stdin)
    for name in ACTUAL:
        stdin['files'][name] = base64.b64encode(files[name]).decode()
    assert json.dumps(old_stdin, separators=(',', ':')) + '\n' == originals['ACTUAL_SOURCE_STDIN.json'].decode()
    stdin_text = json.dumps(stdin, separators=(',', ':')) + '\n'
    assert len(stdin_text.encode()) <= 1048576
    typed = copy.deepcopy(old_typed)
    typed['args'] = ['-B', '-c', candidate]
    typed['stdin'] = stdin_text
    typed['idempotency_key'] = KEY
    assert list(typed) == ['host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds']
    assert 'env' not in typed
    assert {key: typed[key] for key in typed if key not in ('args', 'stdin', 'idempotency_key')} == {key: old_typed[key] for key in old_typed if key not in ('args', 'stdin', 'idempotency_key')}
    bootstrap_row = save('SOURCE_BOOTSTRAP.candidate.py', candidate.encode())
    stdin_row = save('SOURCE_STDIN.candidate.json', stdin_text.encode())
    typed_row = save('SOURCE_PROCESS_INPUT.candidate.json', (json.dumps(typed, ensure_ascii=False, indent=2) + '\n').encode())
    delta = ''.join(difflib.unified_diff(old.splitlines(keepends=True), candidate.splitlines(keepends=True), fromfile='actual-246d/ACTUAL_SOURCE_BOOTSTRAP.py', tofile='candidate-cc57/SOURCE_BOOTSTRAP.candidate.py'))
    diff_row = save('ACTUAL_246D_TO_CC57_CANDIDATE.diff', delta.encode())
    report = {
        'format': 'hepta-cc57-exact-source-bootstrap-candidate-review-v1',
        'status': 'CANDIDATE_BOUND_TO_ACTUAL_ROOT_INPUTS_AWAITING_EXACT_LAUNCH_APPROVAL',
        'source': SOURCE, 'tree': TREE, 'base': BASE, 'idempotency_key': KEY,
        'actual_prior_references': helper.ORIGINALS,
        'eight_input_pins': new_pins,
        'three_bound_actual_files': {name: {'local_path': str(value['path']), **value['pin']} for name, value in ACTUAL.items()},
        'bootstrap': bootstrap_row, 'stdin': stdin_row, 'typed_request': typed_row, 'difference': diff_row,
        'bootstrap_only_changed_assignments': ['BASE', 'PINS'],
        'only_three_pin_payload_changes': list(ACTUAL),
        'five_fixed_inputs_byte_identical': True,
        'exact_inverse_two_assignment_edits_restores_entire_original': True,
        'normalized_module_AST_identical': True,
        'all_function_source_and_AST_identical': list(helper.functions(old)),
        'source_wrapper_execution_outside_staging_try': True,
        'source_wrapper_execution_tail_byte_identical': True,
        'eight_file_layout_unchanged': True,
        'typed_seven_fields_exact_original_order': list(typed),
        'typed_changed_fields_only': ['args', 'stdin', 'idempotency_key'],
        'host_executable_cwd_timeout_unchanged': {key: typed[key] for key in ('host', 'executable', 'cwd', 'timeout_seconds')},
        'outer_seconds': 7200, 'budget_arithmetic_inference_used': False,
        'historical_outer_budget_evidence': old_manifest['historical_outer_budget_evidence'],
        'original_gate_budgets': source_cfg['budgets_seconds'],
        'no_env_field_added': True,
        'original_failure_retention_bounds_permissions_and_fsync_unchanged': True,
        'source_first_native_only_after_complete_source_terminal_and_review': True,
        'local_compile_only': True, 'H_calls': 0, 'gate_or_native_main_calls': 0,
        'source_or_ref_changes': False, 'qualifications_passed': False,
        'launch_approval_for_this_exact_typed_candidate': None,
    }
    review_row = save('STATIC_REVIEW.json', jbytes(report))
    manifest = {
        'format': 'hepta-cc57-exact-source-launch-candidate-manifest-v1',
        'status': 'PREPARED_NOT_DISPATCHED_NOT_QUALIFIED',
        'inputs': inputs, 'bootstrap': bootstrap_row, 'stdin': stdin_row,
        'typed_request': typed_row, 'static_review': review_row, 'difference': diff_row,
        'generator': pin(Path(__file__).read_bytes()), 'source': SOURCE, 'tree': TREE,
        'base': BASE, 'outer_seconds': 7200, 'idempotency_key': KEY,
        'exact_launch_approval': None, 'dispatch': False,
    }
    manifest_row = save('EXACT_SOURCE_LAUNCH_MANIFEST.candidate.json', jbytes(manifest))
    print(json.dumps({'bootstrap': bootstrap_row, 'stdin': stdin_row, 'typed': typed_row, 'review': review_row, 'manifest': manifest_row, 'H_calls': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
