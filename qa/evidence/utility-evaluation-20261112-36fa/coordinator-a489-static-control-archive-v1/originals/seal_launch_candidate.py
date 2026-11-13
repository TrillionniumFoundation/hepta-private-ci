#!/usr/bin/env python3
"""Seal concrete candidate bytes for Root's exact review; never dispatch."""
from __future__ import annotations
import ast, base64, difflib, hashlib, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent
def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
def enc(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
def save(name, raw):
    with (ROOT / name).open('xb') as stream:
        stream.write(raw)
    return pin(raw)
waiting_raw = (ROOT / 'WAITING_CONFIG.json').read_bytes()
waiting = json.loads(waiting_raw)
assert waiting['status'] == 'WAITING_ROOT_EXACT_APPROVAL' and waiting['root_execution_approved'] is False
candidate = dict(waiting)
candidate.update(status='APPROVED_CANDIDATE_ISOLATED_MATERIALIZATION', root_execution_approved=True)
inverse = dict(candidate)
inverse.update(status=waiting['status'], root_execution_approved=False)
assert enc(inverse) == waiting_raw
config_raw = enc(candidate)
config_pin = save('APPROVAL_CANDIDATE_CONFIG.json', config_raw)
template = (ROOT / 'MATERIALIZATION_BOOTSTRAP.HOLD.py').read_text()
marker = "    'APPROVED_CONFIG.json': None,"
assert template.count(marker) == 1
bootstrap = template.replace(marker, "    'APPROVED_CONFIG.json': " + repr(config_pin) + ",", 1)
assert bootstrap.replace("    'APPROVED_CONFIG.json': " + repr(config_pin) + ",", marker, 1) == template
compile(bootstrap, 'MATERIALIZATION_BOOTSTRAP.candidate.py', 'exec')
bootstrap_pin = save('MATERIALIZATION_BOOTSTRAP.candidate.py', bootstrap.encode())
payload_template_raw = (ROOT / 'MATERIALIZATION_STDIN.HOLD.json').read_bytes()
payload = json.loads(payload_template_raw)
assert payload['files']['APPROVED_CONFIG.json'] is None
payload['files']['APPROVED_CONFIG.json'] = base64.b64encode(config_raw).decode()
payload_raw = enc(payload)
assert len(payload_raw) <= 1048576
payload_pin = save('MATERIALIZATION_STDIN.candidate.json', payload_raw)
reverse = json.loads(payload_raw)
reverse['files']['APPROVED_CONFIG.json'] = None
assert enc(reverse) == payload_template_raw
hold_request = json.loads((ROOT / 'MATERIALIZATION_PROCESS_INPUT.HOLD.json').read_bytes())
assert hold_request['stdin'] is None
request = dict(hold_request)
request['args'] = ['-B', '-c', bootstrap]
request['stdin'] = payload_raw.decode()
assert set(request) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert request['host'] == 'desktop' and request['executable'] == '/usr/bin/python3' and request['cwd'] == '/home/qian-qi'
assert request['timeout_seconds'] == 900 and request['idempotency_key'] == 'hepta-utility-36fa-provider-coordinator-a489-isolated-materialization-v1'
request_raw = enc(request)
assert len(request_raw) <= 1048576
request_pin = save('MATERIALIZATION_PROCESS_INPUT.candidate.json', request_raw)
node = next(node for node in ast.parse(bootstrap).body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PINS' for target in node.targets))
pins = ast.literal_eval(node.value)
files = {
    'driver.py': (ROOT / 'driver.HOLD.py').read_bytes(),
    'MATERIALIZATION_PACKET.json': (ROOT / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes(),
    'DONOR_RESULT.original.json': (ROOT / 'DONOR_RESULT.original.json').read_bytes(),
    'DONOR_SUPERVISOR.original.json': (ROOT / 'DONOR_NORMAL_SUPERVISOR.original.json').read_bytes(),
    'APPROVED_CONFIG.json': config_raw,
}
import gzip
decoded = []
for name, text in payload['files'].items():
    raw = base64.b64decode(text, validate=True)
    if name == 'MATERIALIZATION_PACKET.json':
        raw = gzip.decompress(raw)
    assert raw == files[name] and pin(raw) == pins[name]
    decoded.append({'name': name, **pin(raw), 'whole_bytes_equal': True})
review = {
    'format': 'hepta-concrete-candidate-launch-byte-review-v1', 'status': 'WAITING_ROOT_EXACT_HASH_APPROVAL',
    'approval_true_is_candidate_data_only_not_dispatch_authorization': True,
    'native_calls_made': 0, 'materialization_or_staging_main_executed': False,
    'config_only_two_approval_fields_changed': True, 'config_full_inverse_equal': True,
    'bootstrap_only_config_none_pin_replaced': True, 'bootstrap_full_inverse_equal': True,
    'payload_only_config_none_replaced': True, 'payload_full_inverse_equal': True,
    'original_budgets_action_record_outer_seconds': [600, 180, 900],
    'host': request['host'], 'cwd': request['cwd'], 'executable': request['executable'],
    'idempotency_key': request['idempotency_key'], 'typed_field_count': len(request), 'environment_overrides': False,
    'five_original_files': decoded, 'decoded_staged_chunks_are_separate_fixed_create_only_requests': 5,
    'config': config_pin, 'bootstrap': bootstrap_pin, 'stdin': payload_pin, 'typed_request': request_pin,
    'existing_HOLD_controls_preserved': True,
    'materializer_driver_is_fixed': pins['driver.py'],
    'whole_request_with_stdin_below_1MiB': len(request_raw) <= 1048576,
}
save('EXACT_LAUNCH_CANDIDATE_REVIEW.json', enc(review))
save('CONFIG_CANDIDATE_FROM_WAITING.diff', ''.join(difflib.unified_diff(waiting_raw.decode().splitlines(True), config_raw.decode().splitlines(True), fromfile='WAITING_CONFIG.json', tofile='APPROVAL_CANDIDATE_CONFIG.json')).encode())
print(json.dumps(review, sort_keys=True))
