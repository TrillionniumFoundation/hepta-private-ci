#!/usr/bin/env python3
"""Local-only exact preparation. Never dispatch an H request or execute the driver."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path('/tmp/hepta-36fa-cc57-isolated-materialization-launch-v1')
ORIGINAL = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1')
CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1')
FILES = {
    'driver.py': Path('/tmp/hepta-36fa-cc57-isolated-materializer-v1/driver-v4.HOLD.py'),
    'MATERIALIZATION_PACKET.json': Path('/tmp/hepta-36fa-cc57-isolated-materializer-v1/MATERIALIZATION_PACKET.HOLD.json'),
    'AVAILABILITY_RESULT.original.json': Path('/tmp/hepta-36fa-cc57-isolated-recovery-plan-v1/STDOUT.complete.log'),
    'AVAILABILITY_SUPERVISOR.original.json': Path('/tmp/hepta-36fa-cc57-isolated-recovery-plan-v1/STATUS_01.original.json'),
    'APPROVED_CONFIG.json': Path('/tmp/hepta-36fa-cc57-isolated-materializer-v1/APPROVED_CONFIG_V4.json'),
}
EXPECTED = {
    'driver.py': {'bytes': 57607, 'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436', 'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'},
    'MATERIALIZATION_PACKET.json': {'bytes': 13764, 'sha256': 'b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3', 'git_blob': '06503652a2895120daf8b66e42b3a01cefeaf4fb'},
    'AVAILABILITY_RESULT.original.json': {'bytes': 11954, 'sha256': '7631a19a48c56b4a37b396b97d57f19793baa67cdb37e31acb7a3dd79f397a22', 'git_blob': '365a11bbfc183a05d76076da08301ce227847191'},
    'AVAILABILITY_SUPERVISOR.original.json': {'bytes': 956, 'sha256': '417a8191432b901a1b1c625518e31ae77e51150ee9494c616fe16da04a56c3de', 'git_blob': '432eeed53c480af77bd3b79fef43d3f96f1ca22c'},
    'APPROVED_CONFIG.json': {'bytes': 992, 'sha256': '414a52cdd7802f5d84de65ee70422a14eb93d799ca46912a9d618f734bffe6a0', 'git_blob': '692d2b825dcbb38eb95e91c0fb5f67afa39d0518'},
}


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def functions(code):
    lines = code.splitlines(keepends=True)
    return {n.name: ''.join(lines[n.lineno - 1:n.end_lineno]) for n in ast.parse(code).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


raws = {name: path.read_bytes() for name, path in FILES.items()}
assert {name: pin(raw) for name, raw in raws.items()} == EXPECTED
config = json.loads(raws['APPROVED_CONFIG.json'])
assert config['status'] == 'APPROVED_ISOLATED_MATERIALIZATION'
assert config['root_execution_approved'] is True
assert config['driver'] == EXPECTED['driver.py'] and config['packet'] == EXPECTED['MATERIALIZATION_PACKET.json']
assert (config['action_seconds'], config['record_seconds'], config['outer_seconds']) == (600, 180, 900)
old = (ORIGINAL / 'ACTUAL_BOOTSTRAP.py').read_text()
bootstrap = old
tree = ast.parse(bootstrap)
lines = bootstrap.splitlines(keepends=True)
replace = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == 'BASE':
            replace[node.lineno] = (node.end_lineno, 'BASE = pathlib.Path(' + repr(str(CONTROL)) + ')\n')
        elif node.targets[0].id == 'PINS':
            body = 'PINS = {\n' + ''.join('    ' + repr(name) + ': ' + repr(value) + ',\n'
                                            for name, value in EXPECTED.items()) + '}\n'
            replace[node.lineno] = (node.end_lineno, body)
for start, (end, raw) in sorted(replace.items(), reverse=True):
    lines[start-1:end] = [raw]
bootstrap = ''.join(lines)
substitutions = {
    'hepta-final-canonical-alignment-bootstrap-v1': 'hepta-isolated-cc57-materialization-bootstrap-v1',
    'hepta-final-canonical-alignment-bootstrap-readback-v1': 'hepta-isolated-cc57-materialization-bootstrap-readback-v1',
    'fixed_canonical_alignment_bootstrap_verified': 'fixed_isolated_cc57_materialization_bootstrap_verified',
    'exact four input files': 'exact five input files',
    "if name == 'CANONICAL_PACKET.json':": "if name == 'MATERIALIZATION_PACKET.json':",
    "os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'driver.py'),\n             '--config-sha256', PINS['APPROVED_CONFIG.json']['sha256']])":
        "os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'driver.py')])",
}
for before, after in substitutions.items():
    assert bootstrap.count(before) == 1, before
    bootstrap = bootstrap.replace(before, after)
assert functions(bootstrap) == functions(old)
assert len(functions(old)) == 4
compile(bootstrap, 'ACTUAL_BOOTSTRAP.py', 'exec')
compressed = gzip.compress(raws['MATERIALIZATION_PACKET.json'], mtime=0)
payload = encode({'format': 'hepta-isolated-cc57-materialization-bootstrap-v1',
                  'files': {name: base64.b64encode(compressed if name == 'MATERIALIZATION_PACKET.json' else raw).decode()
                            for name, raw in raws.items()}})
assert len(payload) <= 1048576
roundtrip = json.loads(payload)
for name, encoded in roundtrip['files'].items():
    decoded = base64.b64decode(encoded, validate=True)
    if name == 'MATERIALIZATION_PACKET.json':
        decoded = gzip.decompress(decoded)
    assert decoded == raws[name] and pin(decoded) == EXPECTED[name]
prior = json.loads((ORIGINAL / 'ACTUAL_PROCESS_INPUT.json').read_bytes())
assert set(prior) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert prior['host'] == 'desktop' and prior['executable'] == '/usr/bin/python3'
assert prior['args'][:2] == ['-B', '-c'] and len(prior['args']) == 3
assert prior['cwd'] == '/home/qian-qi' and prior['timeout_seconds'] == 900
typed = dict(prior)
typed.update(args=['-B', '-c', bootstrap], stdin=payload.decode(),
             idempotency_key='hepta-utility-36fa-cc57-isolated-materialization-v1')
outputs = {'ACTUAL_BOOTSTRAP.py': bootstrap.encode(), 'ACTUAL_STDIN.json': payload,
           'ACTUAL_PROCESS_INPUT.json': encode(typed),
           'FROM_ORIGINAL_BOOTSTRAP.diff': ''.join(difflib.unified_diff(old.splitlines(keepends=True),
                  bootstrap.splitlines(keepends=True), fromfile='actual-canonical-bootstrap',
                  tofile='isolated-materialization-bootstrap')).encode()}
manifest = {
    'format': 'hepta-isolated-cc57-materialization-exact-launch-preparation-v1',
    'status': 'SEALED_WAIT_ROOT_EXACT_LAUNCH_APPROVAL',
    'typed_fields': sorted(typed), 'idempotency_key': typed['idempotency_key'],
    'host': typed['host'], 'executable': typed['executable'], 'cwd': typed['cwd'],
    'outer_timeout_seconds': 900, 'action_seconds': 600, 'record_seconds': 180,
    'control_directory': str(CONTROL), 'source_repo': config['source_repo'],
    'destination_repo': config['destination_repo'],
    'original_bootstrap': {'local': str(ORIGINAL / 'ACTUAL_BOOTSTRAP.py'), **pin(old.encode())},
    'all_four_original_helper_functions_byte_identical': True,
    'bootstrap_changes': ['fixed new BASE', 'five exact input pins', 'scope-specific schema and event labels',
                          'compressed packet filename and count',
                          'exec exact driver without unused config CLI argument; all five staged bytes fully checked'],
    'files': {name: {'local': str(FILES[name]), **EXPECTED[name]} for name in FILES},
    'compressed_materialization_packet': pin(compressed),
    'outputs': {name: pin(raw) for name, raw in outputs.items()},
    'H_main_dispatched': False, 'source_writes': 0, 'ref_updates': 0, 'qualification': False,
}
outputs['EXACT_LAUNCH_MANIFEST.json'] = encode(manifest)
for name, raw in outputs.items():
    with (HERE / name).open('xb') as stream:
        stream.write(raw)
    assert (HERE / name).read_bytes() == raw
print(json.dumps({name: pin(raw) for name, raw in outputs.items()}, indent=2))
