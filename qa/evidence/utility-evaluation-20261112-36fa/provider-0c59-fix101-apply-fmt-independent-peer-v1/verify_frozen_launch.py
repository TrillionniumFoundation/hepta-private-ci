"""Read frozen scratch evidence only; never import or execute either launcher/driver."""
import ast
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTHOR = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')
CANDIDATE = AUTHOR / 'execution-candidate-v1'
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')

def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def fixed(path, blob):
    raw = path.read_bytes()
    assert ident(raw)['git_blob'] == blob, (str(path), ident(raw))
    return raw

def defs(text):
    lines = text.splitlines(keepends=True)
    return {n.name: ''.join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(text).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def assignment(text, name):
    lines = text.splitlines(keepends=True)
    nodes = [n for n in ast.parse(text).body if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id == name]
    assert len(nodes) == 1
    node = nodes[0]
    return node.value, ''.join(lines[node.lineno-1:node.end_lineno])

def literal_changes(left, right, path=''):
    if isinstance(left, dict) and isinstance(right, dict):
        assert set(left) == set(right), path
        return sum((literal_changes(left[k], right[k], path + '/' + k) for k in sorted(left)), [])
    return [] if left == right else [{'path': path, 'before': left, 'after': right}]

def main():
    old_raw = fixed(AUTHOR / 'ORIGINAL_9101_BOOTSTRAP.py', '9ca752893983b582f2394c054e92a0adc265cb8f')
    boot_raw = fixed(CANDIDATE / 'ACTUAL_BOOTSTRAP.candidate.py', 'ab06aa07a11ab2b6739a7203dab0a1ba6f0deb29')
    typed_raw = fixed(CANDIDATE / 'ACTUAL_PROCESS_INPUT.candidate.json', 'b63bd0d12684a3ba39e63f1f12fef56cb56cb3d9')
    stdin_raw = fixed(CANDIDATE / 'ACTUAL_STDIN.candidate.json', '347d63ee5af1c0f5826b02add02f2f322a4aefbe')
    cfg_raw = fixed(CANDIDATE / 'APPROVED_CONFIG.candidate.json', '38a177082b23477a74fbd2db7d5061c9e9eff79c')
    hold_raw = fixed(AUTHOR / 'WAITING_CONFIG.json', '0beff4136fc11d35513f2f16d7a26a0c30d77802')
    driver_raw = fixed(AUTHOR / 'driver-apply-fmt.HOLD.py', '0938761e369ddfa215da98b70423cfd5d48ac819')
    normal_raw = fixed(RUNTIME / 'MAIN_STATUS_06.original.json', '5980149603c1ab8f2a4a7aa7f21e9822c28c4c51')
    repair_raw = fixed(REPAIR / 'SOURCE_PACKET.json', '12a664ce2905feb8107ae66b303c4975f17a9fe3')
    old, boot = old_raw.decode('utf-8'), boot_raw.decode('utf-8')
    typed = json.loads(typed_raw)
    assert typed == {
        'host': 'desktop', 'cwd': '/home/qian-qi', 'executable': '/usr/bin/python3',
        'args': ['-B', '-c', boot], 'stdin': stdin_raw.decode('utf-8'),
        'timeout_seconds': 2100,
        'idempotency_key': 'hepta-utility-36fa-provider-0c59-fix101-apply-fmt-v1'}, typed.keys()
    assert len(typed) == 7 and 'env' not in typed
    assert len(stdin_raw) <= 1048576 and len(typed_raw) <= 1048576
    hold, cfg = json.loads(hold_raw), json.loads(cfg_raw)
    changes = literal_changes(hold, cfg)
    assert changes == [
        {'path': '/root_execution_approved', 'before': False, 'after': True},
        {'path': '/status', 'before': 'HOLD_ROOT_EXACT_REVIEW_REQUIRED', 'after': 'ROOT_APPROVED_TO_EXECUTE'}]
    inverse_cfg = cfg_raw.replace(b'"root_execution_approved": true', b'"root_execution_approved": false')
    inverse_cfg = inverse_cfg.replace(b'"status": "ROOT_APPROVED_TO_EXECUTE"', b'"status": "HOLD_ROOT_EXACT_REVIEW_REQUIRED"')
    assert inverse_cfg == hold_raw
    pins = ast.literal_eval(assignment(boot, 'PINS')[0])
    expected_inputs = {'driver.py': driver_raw,
                       'FAILED_MAINTENANCE_SUPERVISOR.original.json': normal_raw,
                       'REPAIR_PROPOSAL.original.json': repair_raw,
                       'APPROVED_CONFIG.json': cfg_raw}
    assert pins == {k: ident(v) for k, v in expected_inputs.items()}
    packet = json.loads(stdin_raw)
    assert set(packet) == {'format', 'files'}
    assert packet['format'] == 'hepta-fix101-repair-format-bootstrap-v1'
    assert set(packet['files']) == set(expected_inputs)
    decoded = {}
    for name, original in expected_inputs.items():
        encoded = packet['files'][name]
        assert isinstance(encoded, str)
        transported = base64.b64decode(encoded, validate=True)
        raw = transported
        if name == 'REPAIR_PROPOSAL.original.json':
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                expanded = stream.read(len(original) + 1)
                assert len(expanded) == len(original) and stream.read(1) == b''
            raw = expanded
        assert raw == original and ident(raw) == pins[name], name
        decoded[name] = {'raw': ident(raw), 'transport': ident(transported), 'full_bytes_equal': True,
                         'gzip': name == 'REPAIR_PROPOSAL.original.json'}
    replacements = []
    for name in ['BASE', 'PINS']:
        replacements.append((assignment(old, name)[1], assignment(boot, name)[1]))
    replacements += [
        ('hepta-final-nonrust-format-bootstrap-v1', 'hepta-fix101-repair-format-bootstrap-v1'),
        ("if name == 'NONRUST_PACKET.json':", "if name == 'REPAIR_PROPOSAL.original.json':"),
        ('hepta-final-nonrust-format-bootstrap-readback-v1', 'hepta-fix101-repair-format-bootstrap-readback-v1'),
        ('fixed_final_nonrust_format_bootstrap_verified', 'fixed_fix101_repair_format_bootstrap_verified')]
    forward = old
    inverse = boot
    for before, after in replacements:
        assert forward.count(before) == 1
        forward = forward.replace(before, after)
    for before, after in reversed(replacements):
        assert inverse.count(after) == 1
        inverse = inverse.replace(after, before)
    assert forward == boot and inverse == old
    old_defs, new_defs = defs(old), defs(boot)
    assert set(old_defs) == set(new_defs) == {'check', 'identity', 'real_parents', 'retain'}
    assert all(old_defs[n] == new_defs[n] for n in old_defs)
    tree = ast.parse(boot)
    calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert calls.count('os.execv') == 1
    assert not any('flock' in n or 'set_inheritable' in n for n in calls)
    assert 'fcntl' not in boot and 'SOURCE_COORDINATION.lock' not in boot
    before_exec = old[old.index("    os.execv('/usr/bin/python3'"):]
    after_exec = boot[boot.index("    os.execv('/usr/bin/python3'"):]
    assert before_exec == after_exec
    assert boot.index('for name, pin in PINS.items():') < boot.index('    real_parents()') < boot.index('    os.mkdir(BASE, 0o700)')
    assert boot.index('rows += [retain(name, raw) for name, raw in files.items()]') < boot.index("    os.execv('/usr/bin/python3'")
    driver_tree = ast.parse(driver_raw)
    main_node = next(n for n in driver_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    flock_calls = [n for n in ast.walk(main_node) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'fcntl.flock']
    assert len(flock_calls) == 1
    assert ast.unparse(flock_calls[0].args[1]) == 'fcntl.LOCK_EX | fcntl.LOCK_NB'
    result = {
        'schema': 'hepta-fix101-fmt-only-independent-launch-proof-v1',
        'original_bootstrap': ident(old_raw), 'bootstrap': ident(boot_raw), 'typed_request': ident(typed_raw),
        'stdin': ident(stdin_raw), 'candidate_config': ident(cfg_raw), 'driver': ident(driver_raw),
        'exact_seven_typed_fields': sorted(typed), 'no_environment_override': True,
        'outer_seconds': 2100, 'request_and_stdin_within_unchanged_1_mib': True,
        'all_four_inputs_decoded_and_full_bytes_equal': decoded,
        'only_two_config_leaf_changes': changes, 'full_config_inverse_bytes_equal': True,
        'six_explicit_bootstrap_replacements_forward_and_inverse_equal': True,
        'four_original_helpers_byte_equal': {k: ident(v.encode()) for k, v in old_defs.items()},
        'exec_and_failure_tail_byte_equal': True,
        'all_four_inputs_validated_before_create_only_staging': True,
        'full_readback_precedes_exec': True,
        'bootstrap_has_no_lock_or_inherited_extra_lock_fd': True,
        'thin_main_has_one_original_ex_nb_lock_call': True,
        'candidate_scope': 'One exact reviewed four-path repair, then one original fmt --base c0f with 900 seconds; no second fix or tests.',
        'dispatch_authorized_by_this_review': False, 'runtime_execution': False,
        'qualification': False,
        'scope': 'Only bytes, JSON, AST and bounded gzip/base64 of frozen local evidence. No bootstrap/driver/prepare/main/Git/H/source action executed.'}
    raw = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    out = HERE / 'FROZEN_LAUNCH_PROOF.json'
    with out.open('xb') as f:
        f.write(raw)
    print(json.dumps({'path': str(out), **ident(raw)}))

if __name__ == '__main__':
    main()
