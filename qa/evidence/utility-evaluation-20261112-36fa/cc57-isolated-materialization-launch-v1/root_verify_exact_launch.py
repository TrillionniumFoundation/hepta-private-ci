"""Pure local review of frozen bytes. Never execute bootstrap, driver or H."""
from pathlib import Path
import ast
import base64
import datetime
import gzip
import hashlib
import io
import json

HERE = Path('/tmp/hepta-36fa-cc57-isolated-materialization-launch-v1')
ORIGINAL = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def functions(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    return {n.name: ''.join(lines[n.lineno - 1:n.end_lineno])
            for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}


def matching_fields(value, wanted, at='$'):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            found += matching_fields(child, wanted, at + '.' + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += matching_fields(child, wanted, at + '[' + str(index) + ']')
    elif isinstance(value, str) and value.encode() == wanted:
        found.append(at)
    return found


request_raw = (HERE / 'ACTUAL_PROCESS_INPUT.json').read_bytes()
request = json.loads(request_raw)
assert pin(request_raw) == {'bytes': 109095,
    'sha256': '7e8caf48364c4b58a737af0a1b888e97730e7b53d0c23bdb79dc786031e704a5',
    'git_blob': '163e69e0e1002f70dc6d8e71ff3354ff95607647'}
assert set(request) == {'args', 'cwd', 'executable', 'host', 'idempotency_key', 'stdin', 'timeout_seconds'}
assert request['args'][:2] == ['-B', '-c'] and len(request['args']) == 3
assert request['cwd'] == '/home/qian-qi' and request['host'] == 'desktop'
assert request['executable'] == '/usr/bin/python3' and request['timeout_seconds'] == 900
assert request['idempotency_key'] == 'hepta-utility-36fa-cc57-isolated-materialization-v1'
bootstrap = (HERE / 'ACTUAL_BOOTSTRAP.py').read_bytes()
assert request['args'][2].encode() == bootstrap
assert request['stdin'].encode() == (HERE / 'ACTUAL_STDIN.json').read_bytes()
assert len(request['stdin'].encode()) <= 1048576
old = (ORIGINAL / 'ACTUAL_BOOTSTRAP.py').read_bytes()
assert functions(old) == functions(bootstrap) and len(functions(old)) == 4
compile(bootstrap, 'ACTUAL_BOOTSTRAP.py', 'exec')
manifest = json.loads((HERE / 'EXACT_LAUNCH_MANIFEST.json').read_bytes())
pins_node = next(n.value for n in ast.parse(bootstrap).body
    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PINS' for t in n.targets))
pins = ast.literal_eval(pins_node)
payload = json.loads(request['stdin'])
assert set(payload) == {'format', 'files'}
assert payload['format'] == 'hepta-isolated-cc57-materialization-bootstrap-v1'
assert set(payload['files']) == set(pins) == set(manifest['files']) and len(pins) == 5
decoded_inputs = {}
for name, expected in pins.items():
    raw = base64.b64decode(payload['files'][name], validate=True)
    if name == 'MATERIALIZATION_PACKET.json':
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            expanded = stream.read(expected['bytes'] + 1)
            assert len(expanded) == expected['bytes'] and stream.read(1) == b''
        raw = expanded
    assert pin(raw) == expected
    assert Path(manifest['files'][name]['local']).read_bytes() == raw
    decoded_inputs[name] = raw
cfg = json.loads(decoded_inputs['APPROVED_CONFIG.json'])
waiting = json.loads(Path('/tmp/hepta-36fa-cc57-isolated-materializer-v1/WAITING_CONFIG_V4.json').read_bytes())
assert {k for k in cfg if cfg[k] != waiting[k]} == {'root_execution_approved', 'status'}
assert cfg['root_execution_approved'] is True and cfg['status'] == 'APPROVED_ISOLATED_MATERIALIZATION'
assert cfg['qualification'] is False
assert (cfg['action_seconds'], cfg['record_seconds'], cfg['outer_seconds']) == (600, 180, 900)
assert cfg['driver'] == pins['driver.py'] and cfg['packet'] == pins['MATERIALIZATION_PACKET.json']
assert cfg['source_repo'] == '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
assert cfg['destination_repo'] == '/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
assert cfg['control'] == '/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1'
assert "os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'driver.py')])" in bootstrap.decode()
assert '--config-sha256' not in bootstrap.decode()
assert 'argparse' not in decoded_inputs['driver.py'].decode()
full_readbacks = {}
for name in ['ACTUAL_BOOTSTRAP.py', 'ACTUAL_PROCESS_INPUT.json', 'ACTUAL_STDIN.json',
             'EXACT_LAUNCH_MANIFEST.json', 'FROM_ORIGINAL_BOOTSTRAP.diff', 'seal_exact_launch.py']:
    raw = (HERE / name).read_bytes()
    sdk = json.loads((HERE / (name + '.GITHUB.original.json')).read_bytes())
    fields = matching_fields(sdk, raw)
    assert fields, name
    full_readbacks[name] = {'identity': pin(raw), 'actual_full_payload_fields': fields}
report = {
    'format': 'hepta-root-exact-isolated-materialization-launch-approval-v1',
    'reviewed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'decision': 'APPROVE_ONE_EXACT_ISOLATED_MATERIALIZATION_REQUEST',
    'request': pin(request_raw), 'idempotency_key': request['idempotency_key'],
    'host': request['host'], 'executable': request['executable'], 'cwd': request['cwd'],
    'budgets_seconds': {'action': 600, 'records': 180, 'outer': 900},
    'five_exact_decoded_inputs': pins,
    'original_four_bootstrap_helpers_byte_identical': True,
    'complete_actual_git_readbacks': full_readbacks,
    'root_full_driver_review_precedes_this_exact_launcher_review': True,
    'independent_driver_review_git_blob': '27817d854b232280025ab3195fa383b6c1985e61',
    'actual_availability_root_review_git_blob': '7d8a96cfce3531592c634e8de7d661b5cd44c668',
    'authority_scope': 'The user-authorized engineering recovery is limited to the fixed create-only isolated source and control directory, using the reviewed v4 driver. No old source/ref/index repair, rollback, retry, test, activation, merge, remote ref update or new task authority is authorized by this record.',
    'required_completion': 'Actual normal supervisor plus full RESULT, commands, mutation intents, inputs and artifacts; all original final audits verified and complete canonical inventory/raw-Git readback before a separate native admission.',
    'unknown_admission_rule': 'Reconcile this same exact idempotency key. Never submit another key to bypass an unobserved admission or a partial destination.',
    'qualification': False, 'real_qualified_task_chains': 0,
    'H_calls_by_this_review': 0,
    'verification_script': pin(Path(__file__).read_bytes()),
}
output = HERE / 'ROOT_EXACT_MATERIALIZATION_LAUNCH_APPROVAL.json'
with output.open('xb') as stream:
    stream.write((json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps({'approval': str(output), **pin(output.read_bytes()), 'checked_actual_readbacks': len(full_readbacks)}))
