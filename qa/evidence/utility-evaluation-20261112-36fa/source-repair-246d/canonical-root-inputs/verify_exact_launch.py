import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-v1')
LAUNCH = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1')
PLAN = ROOT
PREP = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1')
FMT = Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pins_node(text):
    return next(node.value for node in ast.parse(text).body
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'PINS')


def main():
    manifest_raw = (LAUNCH / 'EXACT_LAUNCH_MANIFEST.json').read_bytes()
    manifest = json.loads(manifest_raw)
    assert set(manifest['outputs']) == {'ACTUAL_BOOTSTRAP.py', 'ACTUAL_STDIN.json', 'ACTUAL_PROCESS_INPUT.json', 'APPROVED_CONFIG.original.json'}
    for name, row in manifest['outputs'].items():
        raw = (LAUNCH / name).read_bytes()
        assert pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
    code_raw = (LAUNCH / 'ACTUAL_BOOTSTRAP.py').read_bytes()
    code = code_raw.decode()
    expected_template = (LAUNCH / 'BOOTSTRAP_TEMPLATE.HOLD.py').read_text()
    current_pins = ast.literal_eval(pins_node(code))
    original_pins = ast.literal_eval(pins_node(expected_template))
    assert set(current_pins) == set(original_pins)
    assert [k for k in original_pins if original_pins[k] is None] == ['CANONICAL_PACKET.json', 'APPROVED_CONFIG.json']
    lines = code.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    replacements = []
    for key, value in zip(pins_node(code).keys, pins_node(code).values):
        name = ast.literal_eval(key)
        if original_pins[name] is None:
            replacements.append((offsets[value.lineno - 1] + value.col_offset,
                                 offsets[value.end_lineno - 1] + value.end_col_offset))
        else:
            assert current_pins[name] == original_pins[name]
    restored = code
    for start, end in sorted(replacements, reverse=True):
        restored = restored[:start] + 'None' + restored[end:]
    assert restored == expected_template, 'Only the two approved None pins may change'
    typed_raw = (LAUNCH / 'ACTUAL_PROCESS_INPUT.json').read_bytes()
    assert pin(typed_raw) == {'bytes': 655471, 'sha256': 'd15e1528129c039a2e532d9c0dc5e6f195f054b8a8c3d8ec98a691905f7631f5', 'git_blob': '87bdc70f82bc46f94bcce496559c9805bf764b89'}
    typed = json.loads(typed_raw)
    assert set(typed) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
    assert typed['host'] == 'desktop' and typed['cwd'] == '/home/qian-qi'
    assert typed['executable'] == '/usr/bin/python3' and typed['args'] == ['-B', '-c', code]
    assert typed['idempotency_key'] == 'hepta-utility-36fa-source-repair-canonical-alignment-v1'
    assert typed['timeout_seconds'] == 900
    stdin_raw = (LAUNCH / 'ACTUAL_STDIN.json').read_bytes()
    assert typed['stdin'].encode() == stdin_raw and len(stdin_raw) <= 1048576
    payload = json.loads(stdin_raw)
    assert set(payload) == {'format', 'files'}
    assert payload['format'] == 'hepta-final-canonical-alignment-bootstrap-v1'
    expected_files = {
        'driver.py': (PLAN / 'driver.HOLD.py').read_bytes(),
        'FINAL_FORMAT_NORMAL.original.json': (FMT / 'STATUS_01.original.json').read_bytes(),
        'CANONICAL_PACKET.json': (PREP / 'CANONICAL_PACKET.json').read_bytes(),
        'APPROVED_CONFIG.json': (ROOT / 'APPROVED_CONFIG.json').read_bytes(),
    }
    assert set(payload['files']) == set(expected_files) == set(manifest['files'])
    for name, expected in expected_files.items():
        raw = base64.b64decode(payload['files'][name], validate=True)
        if name == 'CANONICAL_PACKET.json':
            assert raw == (PREP / 'CANONICAL_PACKET.json.gz').read_bytes()
            raw = gzip.decompress(raw)
        assert raw == expected and pin(raw) == current_pins[name] == {k: manifest['files'][name][k] for k in ('bytes', 'sha256', 'git_blob')}
    assert pin(expected_files['driver.py'])['git_blob'] == '4952e13c052d9e83d448d09897ff9c09c31552c5'
    assert pin(expected_files['APPROVED_CONFIG.json'])['git_blob'] == '3647755a0c05e818e5a13bea6047346ce7a3eb39'
    assert (LAUNCH / 'APPROVED_CONFIG.original.json').read_bytes() == expected_files['APPROVED_CONFIG.json']
    approval = json.loads((ROOT / 'ROOT_INPUT_APPROVAL.json').read_bytes())
    assert approval['decision'] == 'APPROVED_INPUTS_PENDING_EXACT_TYPED_LAUNCH'
    review = {
        'format': 'hepta-root-source-repair-canonical-exact-launch-review-v1',
        'status': 'APPROVED_ONE_EXACT_900_SECOND_CANONICAL_ALIGNMENT_REQUEST',
        'exact_manifest': pin(manifest_raw), 'bootstrap': pin(code_raw),
        'stdin': pin(stdin_raw), 'typed_request': pin(typed_raw),
        'idempotency_key': typed['idempotency_key'], 'timeout_seconds': typed['timeout_seconds'],
        'four_inputs': current_pins,
        'input_approval': pin((ROOT / 'ROOT_INPUT_APPROVAL.json').read_bytes()),
        'only_bootstrap_changes': ['CANONICAL_PACKET.json pin', 'APPROVED_CONFIG.json pin'],
        'template_inverse_replacement_byte_equal': True,
        'native_execution_approved': 'One invocation of this exact seven-field request after native full Git readback of the immutable launcher; any admission uncertainty reconciles only this same exact request identity.',
        'allowed_transition': 'Only exact missing canonical objects, complete index tree/stat alignment and detached HEAD246d-tocc57 CAS under the unchanged EX lock and live build guard.',
        'required_actual_outcome': 'Normal complete supervisor exit0 AND CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY with all source/Git/input audits verified. Exact expected clean inventory remains a prediction until independently observed.',
        'no_rollback_or_automatic_retry': True,
        'source_branch_ref_updated': False, 'qualification': False,
        'real_qualified_task_chain_results': 0,
    }
    raw = (json.dumps(review, sort_keys=True, indent=2) + '\n').encode()
    path = ROOT / 'ROOT_EXACT_LAUNCH_APPROVAL.json'
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    print(json.dumps(pin(raw), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
