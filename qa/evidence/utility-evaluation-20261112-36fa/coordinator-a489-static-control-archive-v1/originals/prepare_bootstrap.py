#!/usr/bin/env python3
"""Prepare the unchanged original five-file bootstrap for exact review only."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = Path('/tmp/hepta-36fa-new-source-materializer-hold-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1'
KEY = 'hepta-utility-36fa-provider-coordinator-a489-isolated-materialization-v1'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def enc(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def write(name, raw):
    with (HERE / name).open('xb') as stream:
        stream.write(raw)
    return pin(raw)


def pins_node(source):
    return next(node for node in ast.parse(source).body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'PINS' for target in node.targets))


def replace_pins(source, replacement):
    node = pins_node(source)
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [replacement + '\n']
    return ''.join(lines)


original_request_raw = (ORIGINAL / 'MATERIALIZATION_PROCESS_INPUT.candidate.json').read_bytes()
assert pin(original_request_raw)['git_blob'] == 'a34c8779fca77cbf1dd7e26e5516efcfb654c191'
original_request = json.loads(original_request_raw)
assert set(original_request) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert original_request['timeout_seconds'] == 900
assert original_request['host'] == 'desktop' and original_request['executable'] == '/usr/bin/python3'
assert original_request['cwd'] == '/home/qian-qi'
assert original_request['args'][:2] == ['-B', '-c'] and len(original_request['args']) == 3
before = original_request['args'][2]
assert before.encode() == (ORIGINAL / 'MATERIALIZATION_BOOTSTRAP.candidate.py').read_bytes()
original_pins = ast.get_source_segment(before, pins_node(before))
files = {
    'driver.py': (HERE / 'driver.HOLD.py').read_bytes(),
    'MATERIALIZATION_PACKET.json': (HERE / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes(),
    'DONOR_RESULT.original.json': (HERE / 'DONOR_RESULT.original.json').read_bytes(),
    'DONOR_SUPERVISOR.original.json': (HERE / 'DONOR_NORMAL_SUPERVISOR.original.json').read_bytes(),
}
pins = {name: pin(raw) for name, raw in files.items()}
pins['APPROVED_CONFIG.json'] = None
replacement = 'PINS = {\n' + ''.join('    ' + repr(name) + ': ' + repr(value) + ',\n'
                                    for name, value in pins.items()) + '}'
after = replace_pins(before, replacement)
old_base = "BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1')"
new_base = 'BASE = pathlib.Path(' + repr(CONTROL) + ')'
assert after.count(old_base) == 1
after = after.replace(old_base, new_base, 1)
ast.parse(after)
inverse = replace_pins(after.replace(new_base, old_base, 1), original_pins)
assert inverse == before
before_defs = {node.name: ast.get_source_segment(before, node) for node in ast.parse(before).body
               if isinstance(node, ast.FunctionDef)}
after_defs = {node.name: ast.get_source_segment(after, node) for node in ast.parse(after).body
              if isinstance(node, ast.FunctionDef)}
assert before_defs == after_defs
payload = {'format': 'hepta-complete-candidate-materialization-bootstrap-v1', 'files': {
    name: base64.b64encode(gzip.compress(raw, mtime=0) if name == 'MATERIALIZATION_PACKET.json' else raw).decode()
    for name, raw in files.items()
}}
payload['files']['APPROVED_CONFIG.json'] = None
request = dict(original_request)
request.update(args=['-B', '-c', after], stdin=None, idempotency_key=KEY)
bootstrap_pin = write('MATERIALIZATION_BOOTSTRAP.HOLD.py', after.encode())
payload_pin = write('MATERIALIZATION_STDIN.HOLD.json', enc(payload))
request_pin = write('MATERIALIZATION_PROCESS_INPUT.HOLD.json', enc(request))
write('BOOTSTRAP_FROM_A34C8779.diff', ''.join(difflib.unified_diff(
    before.splitlines(keepends=True), after.splitlines(keepends=True),
    fromfile='a34c8779/ACTUAL_BOOTSTRAP.py', tofile='d256-a489/MATERIALIZATION_BOOTSTRAP.HOLD.py')).encode())
report = {
    'status': 'HOLD_FINAL_CONFIG_PIN_AND_STDIN_NULL',
    'original_actual_request': pin(original_request_raw),
    'bootstrap': bootstrap_pin, 'payload_template': payload_pin, 'request_template': request_pin,
    'only_base_and_five_pin_block_replaced': True, 'whole_bootstrap_inverse_equal': True,
    'all_four_helper_definitions_byte_equal': sorted(before_defs),
    'five_inputs': pins, 'environment_overrides': False,
    'original_outer_seconds': 900, 'source_actions_or_H_calls': 0,
    'materializer_body_not_invoked': True, 'historical_0c59_run_not_replayed': True,
}
write('BOOTSTRAP_TEMPLATE_REVIEW.json', enc(report))
seal_original = (ORIGINAL / 'seal_launch_candidate.py').read_text()
old_key = 'hepta-utility-36fa-provider-0c59-isolated-materialization-v1'
assert seal_original.count(old_key) == 1
seal = seal_original.replace(old_key, KEY, 1)
assert seal.replace(KEY, old_key, 1) == seal_original
ast.parse(seal)
write('seal_launch_candidate.py', seal.encode())
write('SEAL_SCRIPT_FROM_ORIGINAL.diff', ''.join(difflib.unified_diff(
    seal_original.splitlines(keepends=True), seal.splitlines(keepends=True),
    fromfile='a34c8779/seal_launch_candidate.py', tofile='d256-a489/seal_launch_candidate.py')).encode())
print(json.dumps(report, sort_keys=True))
