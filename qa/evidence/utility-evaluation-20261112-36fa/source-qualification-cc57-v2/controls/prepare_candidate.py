import ast
import base64
import copy
import difflib
import hashlib
import json
from pathlib import Path

PRIOR = Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v1')
ROOT = Path('/tmp/hepta-36fa-cc57-admission-successor-v2')
OUT = Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v2')
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2'
KEY = 'hepta-utility-36fa-final-source-gates-cc57-v2'
REPLACEMENTS = {
    'qualification-admission.py': ('qualification-admission.cc57.HOLD.py', 14294, 'f2a4a3b666c28605c9e7c48fe8e0c8c1910e5d8443ded456a67ff81c99cc697c', 'a8be08b6cb00536817e2d68c42fa4b90d1e9ff72'),
    'APPROVED_QUALIFICATION_INPUT.json': ('QUALIFICATION_INPUT.cc57-v2.HOLD.json', 10960, '38169c3726baaf32eb55218bbb3e274d2f40d4957630b253d5d31bad48828365', '9cd798c77f3cf9f3139c4f0b345bcc3be2b894da'),
    'APPROVED_SOURCE_GATES_CONFIG.json': ('SOURCE_GATES_CONFIG.cc57-v2.HOLD.json', 820, 'f9bab5b64869c5b8a51545a73c6d1fe7e14767ead25239e8e8b718ff73f5c61c', 'a6dbed0b4eea650f1af616df5dd1e9719475dff4'),
}


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def assignment(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.Assign)
                and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == name)


def save(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    assert path.read_bytes() == raw
    return {'path': str(path), **pin(raw)}


def jbytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def main():
    old_request_raw = (PRIOR / 'SOURCE_PROCESS_INPUT.candidate.json').read_bytes()
    assert pin(old_request_raw) == {'bytes': 131345, 'sha256': 'a75a1c40a743997daf2b374cd6a10e75846cc25698af84a5472e9c965923d190', 'git_blob': '2153b3aba2bfcaaa44123e53ec370004c22d66dd'}
    old_request = json.loads(old_request_raw)
    old = old_request['args'][2]
    assert old_request['args'][:2] == ['-B', '-c']
    assert old.encode() == (PRIOR / 'SOURCE_BOOTSTRAP.candidate.py').read_bytes()
    assert old_request['stdin'].encode() == (PRIOR / 'SOURCE_STDIN.candidate.json').read_bytes()
    original_ast = ast.parse(old)
    old_pins = ast.literal_eval(assignment(original_ast, 'PINS').value)
    packet = json.loads(old_request['stdin'])
    assert set(packet) == {'format', 'files'} and len(packet['files']) == 8
    assert packet['format'] == 'hepta-final-source-qualification-bootstrap-v1'
    assert set(packet['files']) == set(old_pins)
    assert json.dumps(packet, separators=(',', ':')) + '\n' == old_request['stdin']
    files = {name: base64.b64decode(value, validate=True) for name, value in packet['files'].items()}
    for name, raw in files.items():
        assert pin(raw) == old_pins[name], name
    for name, (filename, length, sha256, git_blob) in REPLACEMENTS.items():
        raw = (ROOT / filename).read_bytes()
        assert pin(raw) == {'bytes': length, 'sha256': sha256, 'git_blob': git_blob}, name
        files[name] = raw
    new_pins = {name: pin(files[name]) for name in old_pins}
    changed = [name for name in old_pins if old_pins[name] != new_pins[name]]
    assert set(changed) == set(REPLACEMENTS) and len(changed) == 3
    for name in set(old_pins) - set(REPLACEMENTS):
        assert new_pins[name] == old_pins[name]
    assert new_pins['CANONICAL_ALIGNMENT_NORMAL.original.json'] == {'bytes': 953, 'sha256': '084fb2db14e845c889ca3be77e10883ee9318b88b0700254f2126aa816a42e83', 'git_blob': '041ee7bcd32bcab8f7bedec17ac998cfd929326f'}
    cfg = json.loads(files['APPROVED_QUALIFICATION_INPUT.json'])
    source_cfg = json.loads(files['APPROVED_SOURCE_GATES_CONFIG.json'])
    assert cfg['admission_path'] == BASE + '/qualification-admission.py'
    assert cfg['admission_pin'] == new_pins['qualification-admission.py']
    assert cfg['source_gates_config_path'] == BASE + '/APPROVED_SOURCE_GATES_CONFIG.json'
    assert cfg['source_gates_config_pin'] == new_pins['APPROVED_SOURCE_GATES_CONFIG.json']
    assert cfg['source'] == source_cfg['source_sha'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
    assert cfg['tree'] == source_cfg['source_tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    assert source_cfg['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
    old_base = ast.get_source_segment(old, assignment(original_ast, 'BASE'))
    old_pin_text = ast.get_source_segment(old, assignment(original_ast, 'PINS'))
    new_base = 'BASE = pathlib.Path(' + repr(BASE) + ')'
    new_pin_text = 'PINS = ' + repr(new_pins)
    assert old.count(old_base) == old.count(old_pin_text) == 1
    bootstrap = old.replace(old_base, new_base, 1).replace(old_pin_text, new_pin_text, 1)
    assert bootstrap.replace(new_base, old_base, 1).replace(new_pin_text, old_pin_text, 1) == old
    tree = ast.parse(bootstrap)
    normalized = copy.deepcopy(tree)
    for name in ['BASE', 'PINS']:
        assignment(normalized, name).value = copy.deepcopy(assignment(original_ast, name).value)
    assert ast.dump(normalized, include_attributes=False) == ast.dump(original_ast, include_attributes=False)
    old_functions = {n.name: ast.get_source_segment(old, n) for n in original_ast.body if isinstance(n, ast.FunctionDef)}
    new_functions = {n.name: ast.get_source_segment(bootstrap, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert old_functions == new_functions
    compile(bootstrap, str(OUT / 'SOURCE_BOOTSTRAP.candidate.py'), 'exec')
    marker = '# Main failure is owned by the unchanged original wrapper, not the stager.'
    assert bootstrap.split(marker, 1)[1] == old.split(marker, 1)[1]
    stage_try = next(n for n in tree.body if isinstance(n, ast.Try))
    exec_call = next(n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == 'exec')
    assert exec_call.lineno > stage_try.end_lineno
    for name in REPLACEMENTS:
        packet['files'][name] = base64.b64encode(files[name]).decode()
    stdin = json.dumps(packet, separators=(',', ':')) + '\n'
    assert len(stdin.encode()) <= 1048576
    typed = copy.deepcopy(old_request)
    typed['args'] = ['-B', '-c', bootstrap]
    typed['stdin'] = stdin
    typed['idempotency_key'] = KEY
    assert list(typed) == ['host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds']
    assert typed['timeout_seconds'] == 7200 and 'env' not in typed
    assert {k: v for k, v in typed.items() if k not in ('args', 'stdin', 'idempotency_key')} == {k: v for k, v in old_request.items() if k not in ('args', 'stdin', 'idempotency_key')}
    rows = [save('inputs/' + name, raw) for name, raw in files.items()]
    br = save('SOURCE_BOOTSTRAP.candidate.py', bootstrap.encode())
    sr = save('SOURCE_STDIN.candidate.json', stdin.encode())
    tr = save('SOURCE_PROCESS_INPUT.candidate.json', (json.dumps(typed, ensure_ascii=False, indent=2) + '\n').encode())
    dr = save('ACTUAL_CC57_V1_TO_V2.diff', ''.join(difflib.unified_diff(old.splitlines(keepends=True), bootstrap.splitlines(keepends=True), fromfile='actual-cc57-v1/bootstrap.py', tofile='candidate-cc57-v2/bootstrap.py')).encode())
    report = {'format': 'hepta-cc57-v2-source-exact-candidate-review-v1', 'status': 'HOLD_AWAITING_ROOT_EXACT_LAUNCH_APPROVAL', 'source': cfg['source'], 'tree': cfg['tree'], 'base': BASE, 'idempotency_key': KEY, 'original_request': pin(old_request_raw), 'three_updated_inputs': changed, 'five_inputs_byte_identical': True, 'bootstrap_changed_assignments_only': ['BASE', 'PINS'], 'inverse_assignment_edits_restore_entire_original': True, 'normalized_AST_equal': True, 'all_original_helpers_byte_identical': list(old_functions), 'source_exec_outside_staging_try': True, 'source_driver_and_budgets_unchanged': True, 'outer_seconds': 7200, 'native_outer_seconds_unchanged': 45000, 'H_calls': 0, 'main_executed': False, 'source_writes': False, 'old_v1_unknown_and_secondary_error_preserved': True, 'eight_input_pins': new_pins, 'bootstrap': br, 'stdin': sr, 'typed_request': tr, 'diff': dr, 'staged_candidate_inputs': rows}
    rr = save('STATIC_REVIEW.json', jbytes(report))
    manifest = {'format': 'hepta-cc57-v2-source-exact-candidate-manifest-v1', 'status': report['status'], 'bootstrap': br, 'stdin': sr, 'typed_request': tr, 'review': rr, 'diff': dr, 'eight_input_pins': new_pins, 'generator': pin(Path(__file__).read_bytes()), 'outer_seconds': 7200, 'idempotency_key': KEY, 'exact_launch_approval': None, 'dispatch': False}
    mr = save('EXACT_SOURCE_LAUNCH_MANIFEST.candidate.json', jbytes(manifest))
    print(json.dumps({'bootstrap': br, 'stdin': sr, 'typed': tr, 'review': rr, 'manifest': mr, 'H_calls': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
